from __future__ import annotations

import subprocess
import sys
import json
from pathlib import Path

from PIL import Image, ImageDraw


REPO_ROOT = Path(__file__).resolve().parents[2]
UNPACK = REPO_ROOT / "SKILLS" / "spritesheet-expert" / "scripts" / "unpack_atlas_run.py"


def run_unpack(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(UNPACK), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_unpack_validates_source_before_creating_output(tmp_path: Path) -> None:
    out_dir = tmp_path / "run"

    result = run_unpack(
        "--atlas",
        str(tmp_path / "missing.png"),
        "--grid",
        "1x1",
        "--out-dir",
        str(out_dir),
    )

    assert result.returncode != 0
    assert not out_dir.exists()

    atlas = tmp_path / "one.png"
    _write_atlas(atlas, 1, 1)
    valid = run_unpack("--atlas", str(atlas), "--grid", "1x1", "--background-removal", "none", "--out-dir", str(out_dir))
    assert valid.returncode == 0, valid.stdout + valid.stderr
    before = {path.relative_to(out_dir): path.read_bytes() for path in out_dir.rglob("*") if path.is_file()}
    boxes = tmp_path / "boxes.json"
    for row, cell in [
        ({"rects": [[0.9, 0, 8, 8]]}, {}),
        ({"rects": [[True, 0, 8, 8]]}, {}),
        ({"rects": [[0, 0, -1, 8]]}, {}),
        ({"rects": [[12, 0, 8, 8]]}, {}),
        ({"rects": [[0, 0, 16, 16]]}, {"width": 8, "height": 8}),
        ({"rects": [[0, 0, 16, 16]], "loop": "false"}, {}),
    ]:
        boxes.write_text(json.dumps({"rows": [{"state": "idle", **row}], "cell": cell}))
        invalid = run_unpack("--atlas", str(atlas), "--boxes-file", str(boxes), "--background-removal", "none", "--out-dir", str(out_dir), "--force")
        assert invalid.returncode != 0, row
        assert {path.relative_to(out_dir): path.read_bytes() for path in out_dir.rglob("*") if path.is_file()} == before
    invalid_grid = run_unpack("--atlas", str(atlas), "--grid", "0x1", "--out-dir", str(out_dir), "--force")
    assert invalid_grid.returncode != 0
    assert {path.relative_to(out_dir): path.read_bytes() for path in out_dir.rglob("*") if path.is_file()} == before


def test_unpack_writes_a_v2_request_contract(tmp_path: Path) -> None:
    atlas = tmp_path / "one.png"
    _write_atlas(atlas, 1, 1)
    out_dir = tmp_path / "run"

    result = run_unpack(
        "--atlas",
        str(atlas),
        "--grid",
        "1x1",
        "--states",
        "idle",
        "--background-removal",
        "none",
        "--out-dir",
        str(out_dir),
    )

    assert result.returncode == 0, result.stderr
    request = json.loads((out_dir / "sprite-request.json").read_text(encoding="utf-8"))
    assert request["version"] == 2
    assert request["kind"] == "sprite-gen-request"


def test_labeled_static_grid_keeps_semantics_and_import_evidence(tmp_path: Path) -> None:
    from spritecore.workflow_lanes import describe_run
    from spritecore.item_delivery import digest_file
    import pytest
    atlas, run = tmp_path / "variants.png", tmp_path / "static"
    _write_atlas(atlas, 2, 1)
    labels = tmp_path / "labels.json"
    labels.write_text(json.dumps({"poses": ["front", "side"]}))
    result = run_unpack("--atlas", str(atlas), "--grid", "2x1", "--states", "poses", "--asset-labels-file", str(labels),
        "--source-type", "fixture", "--out-dir", str(run))
    assert result.returncode == 0, result.stdout + result.stderr
    request = json.loads((run / "sprite-request.json").read_text())
    assert request["frame_semantics"] == "variants" and request["states"]["poses"]["loop"] is False
    assert describe_run(run)[0] == "true-grid"
    with pytest.raises(ValueError, match="conflicts"):
        describe_run(run, lane="animation")
    provenance = json.loads((run / "source-provenance.json").read_text())
    assert provenance["fixture"] is True
    accepted = provenance["accepted_sources"][0]
    assert digest_file(run / accepted["path"]) == digest_file(atlas) == accepted["sha256"]


def _write_atlas(path: Path, columns: int, rows: int) -> None:
    image = Image.new("RGBA", (columns * 16, rows * 16), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    for row in range(rows):
        for column in range(columns):
            index = row * columns + column
            left = column * 16 + 3
            top = row * 16 + 3
            draw.rectangle((left, top, left + 9, top + 10), fill=(40 + index * 80, 120, 220, 255))
    image.save(path)


def test_unpack_force_removes_stale_known_outputs_and_preserves_unknown_files(tmp_path: Path) -> None:
    first_atlas = tmp_path / "two.png"
    second_atlas = tmp_path / "one.png"
    _write_atlas(first_atlas, 1, 2)
    _write_atlas(second_atlas, 1, 1)
    out_dir = tmp_path / "run"

    first = run_unpack(
        "--atlas",
        str(first_atlas),
        "--grid",
        "1x2",
        "--states",
        "idle,run",
        "--background-removal",
        "none",
        "--out-dir",
        str(out_dir),
    )
    assert first.returncode == 0, first.stderr
    assert (out_dir / "frames" / "run").is_dir()
    sentinel = out_dir / "caller-note.txt"
    sentinel.write_text("keep", encoding="utf-8")

    second = run_unpack(
        "--atlas",
        str(second_atlas),
        "--grid",
        "1x1",
        "--states",
        "idle",
        "--background-removal",
        "none",
        "--out-dir",
        str(out_dir),
        "--force",
    )

    assert second.returncode == 0, second.stderr
    assert sentinel.read_text(encoding="utf-8") == "keep"
    assert not (out_dir / "frames" / "run").exists()

    # A live writer and an input in the cleanup set both protect prior frames.
    from spritecore.locks import acquire_run_lock
    frame = out_dir / "frames/idle/frame-0.png"
    prior = frame.read_bytes()
    lease = acquire_run_lock(out_dir, "unpack-test")
    try:
        locked = run_unpack("--atlas", str(second_atlas), "--grid", "1x1", "--background-removal", "none", "--out-dir", str(out_dir), "--force")
        assert locked.returncode != 0 and "locked" in (locked.stdout + locked.stderr)
        assert frame.read_bytes() == prior
    finally:
        lease.release()
    overlap = run_unpack("--atlas", str(frame), "--grid", "1x1", "--background-removal", "none", "--out-dir", str(out_dir), "--force")
    assert overlap.returncode != 0 and "overlaps output" in (overlap.stdout + overlap.stderr)
    assert frame.read_bytes() == prior


def test_unpack_force_refuses_an_unowned_output_directory(tmp_path: Path) -> None:
    atlas = tmp_path / "one.png"
    _write_atlas(atlas, 1, 1)
    out_dir = tmp_path / "run"
    out_dir.mkdir()
    sentinel = out_dir / "caller-note.txt"
    sentinel.write_text("keep", encoding="utf-8")

    result = run_unpack(
        "--atlas",
        str(atlas),
        "--grid",
        "1x1",
        "--states",
        "idle",
        "--background-removal",
        "none",
        "--out-dir",
        str(out_dir),
        "--force",
    )

    assert result.returncode != 0
    assert "marker" in (result.stdout + result.stderr).lower()
    assert sentinel.read_text(encoding="utf-8") == "keep"


def test_unpack_manifest_cell_override_and_renaming_preserve_input(tmp_path: Path) -> None:
    from spritecore.paths import create_run_marker
    atlas = tmp_path / "atlas.png"
    _write_atlas(atlas, 2, 1)
    run = tmp_path / "run"
    create_run_marker(run, run_id=run.name)
    manifest = run / "manifest.json"
    payload = {"game_input": str(atlas), "cell": {}, "animation": {"rows": {"idle": {"row": 0, "frames": 2, "fps": 9, "loop": False}}}}
    manifest.write_text(json.dumps(payload))
    original = manifest.read_bytes()
    result = run_unpack("--manifest", str(manifest), "--cell", "16x16", "--states", "resting", "--background-removal", "none", "--out-dir", str(run), "--force")
    assert result.returncode == 0, result.stdout + result.stderr
    request = json.loads((run / "sprite-request.json").read_text())
    assert request["states"]["resting"]["fps"] == 9
    assert request["states"]["resting"]["loop"] is False
    assert request["cell"]["width"] == 16
    assert manifest.read_bytes() == original
    assert (run / "source/imported-atlas.png").read_bytes() == atlas.read_bytes()


def test_unpack_sources_use_one_snapshot_for_pixels_and_provenance(tmp_path: Path, monkeypatch) -> None:
    from hashlib import sha256
    from unpack_atlas_run import import_pngs, main

    read_bytes = Path.read_bytes
    for mode in ("atlas", "pngs"):
        source = tmp_path / f"{mode}.png"
        _write_atlas(source, 1, 1)
        original = read_bytes(source)
        original_pixels = Image.open(source).convert("RGBA").tobytes()
        run = tmp_path / mode
        calls = []

        def changing_read(path):
            data = read_bytes(path)
            if path == source:
                calls.append(path)
                Image.new("RGBA", (16, 16), (200, 90, 20, 255)).save(source)
            return data

        with monkeypatch.context() as patch:
            patch.setattr(Path, "read_bytes", changing_read)
            if mode == "pngs":
                import_pngs(run, [source], "idle", ["token"], source_type="fixture")
                snapshot = run / "source/imported-0000.png"
            else:
                patch.setattr(sys, "argv", [str(UNPACK), "--atlas", str(source), "--grid", "1x1", "--states", "idle", "--background-removal", "none", "--out-dir", str(run)])
                assert main() == 0
                snapshot = run / "source/imported-atlas.png"
        assert len(calls) == 1
        assert read_bytes(snapshot) == original
        with Image.open(run / "frames/idle/frame-0.png") as frame:
            assert frame.convert("RGBA").tobytes() == original_pixels
        provenance = json.loads((run / "source-provenance.json").read_text())
        assert provenance["accepted_sources"][0]["sha256"] == sha256(original).hexdigest()
        assert read_bytes(source) != original


def test_unpack_grid_preserves_interior_empty_positions() -> None:
    from unpack_atlas_run import grid_layout
    image = Image.new("RGBA", (64, 32), (0, 0, 0, 0))
    image.paste((120, 70, 30, 255), (0, 0, 16, 16))
    image.paste((70, 120, 30, 255), (32, 0, 48, 16))
    states, cell = grid_layout(image, 4, 2)
    assert cell == (16, 16)
    assert states[0]["rects"] == [(0, 0, 16, 16), (16, 0, 16, 16), (32, 0, 16, 16), (48, 0, 16, 16)]
    assert states[1]["rects"] == [(0, 16, 16, 16), (16, 16, 16, 16), (32, 16, 16, 16), (48, 16, 16, 16)]
