from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from PIL import Image


REPO_ROOT = Path(__file__).resolve().parents[2]
CHECK = (
    REPO_ROOT
    / "SKILLS"
    / "spritesheet-expert"
    / "scripts"
    / "check_asset_slots.py"
)


def _write_texture_run(run_dir: Path, *, broken_seam: bool) -> None:
    frame_path = run_dir / "frames" / "materials" / "frame-0.png"
    frame_path.parent.mkdir(parents=True)
    image = Image.new("RGBA", (32, 32), (70, 120, 45, 255))
    if broken_seam:
        for x in range(32):
            for y in range(32):
                image.putpixel((x, y), (20 + x * 7, 70 + y % 5, 40, 255))
    image.save(frame_path)
    request = {
        "asset_kind": "texture",
        "frame_semantics": "seamless-textures",
        "cell": {"width": 32, "height": 32, "safe_margin": 0},
        "sampling_policy": {
            "filter": "linear",
            "wrap": "repeat",
            "mipmaps": False,
            "pixel_snap": False,
        },
        "states": {
            "materials": {
                "frames": 1,
                "asset_labels": ["moss-material"],
            }
        },
        "asset_catalog": {
            "items": {
                "moss-material": {
                    "category": "materials",
                    "pivot": [16, 16],
                    "repeat_mode": "self",
                }
            }
        },
    }
    (run_dir / "sprite-request.json").write_text(
        json.dumps(request), encoding="utf-8"
    )
    (run_dir / "frames" / "frames-manifest.json").write_text(
        json.dumps(
            {
                "ok": True,
                "rows": [
                    {
                        "state": "materials",
                        "files": [frame_path.relative_to(run_dir).as_posix()],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def _run(run_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CHECK), "--run-dir", str(run_dir)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_texture_repeat_gate_accepts_full_bleed_matching_edges(tmp_path: Path) -> None:
    run_dir = tmp_path / "seamless"
    _write_texture_run(run_dir, broken_seam=False)

    result = _run(run_dir)

    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads((run_dir / "qa" / "asset-slot-review.json").read_text())
    repeat = report["repeat_validation"]
    assert repeat["ok"] is True
    assert repeat["records"][0]["edge_coverage"] == 1.0
    assert repeat["records"][0]["horizontal_edge_error"] == 0.0
    assert repeat["records"][0]["vertical_edge_error"] == 0.0


def test_texture_repeat_gate_rejects_opposite_edge_mismatch(tmp_path: Path) -> None:
    run_dir = tmp_path / "broken"
    _write_texture_run(run_dir, broken_seam=True)

    result = _run(run_dir)

    assert result.returncode == 1, result.stdout + result.stderr
    report = json.loads((run_dir / "qa" / "asset-slot-review.json").read_text())
    repeat = report["repeat_validation"]
    assert repeat["ok"] is False
    assert any("opposite" in error.lower() for error in report["errors"])


def test_texture_repeat_gate_rejects_missing_repeat_mode_metadata(tmp_path: Path) -> None:
    run_dir = tmp_path / "missing-mode"
    _write_texture_run(run_dir, broken_seam=False)
    request_path = run_dir / "sprite-request.json"
    request = json.loads(request_path.read_text())
    del request["asset_catalog"]["items"]["moss-material"]["repeat_mode"]
    request_path.write_text(json.dumps(request), encoding="utf-8")

    result = _run(run_dir)

    assert result.returncode == 1, result.stdout + result.stderr
    report = json.loads((run_dir / "qa" / "asset-slot-review.json").read_text())
    assert any("repeat_mode" in error for error in report["errors"])


def test_adjacency_gate_rejects_catalog_collapsed_to_one_role(tmp_path: Path) -> None:
    run_dir = tmp_path / "collapsed-adjacency"
    files = []
    labels = ["ground-center", "ground-top"]
    for index, label in enumerate(labels):
        frame = run_dir / "frames" / "tiles" / f"frame-{index}.png"
        frame.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGBA", (32, 32), (40 + index * 20, 100, 60, 255)).save(frame)
        files.append(frame.relative_to(run_dir).as_posix())
    request = {
        "asset_kind": "tileset",
        "cell": {"width": 32, "height": 32},
        "states": {"tiles": {"frames": 2, "asset_labels": labels}},
        "asset_catalog": {
            "items": {
                label: {
                    "category": "tiles",
                    "pivot": [16, 16],
                    "repeat_mode": "adjacency",
                    "tile_role": "base",
                }
                for label in labels
            }
        },
    }
    (run_dir / "sprite-request.json").write_text(json.dumps(request), encoding="utf-8")
    (run_dir / "frames" / "frames-manifest.json").write_text(
        json.dumps({"ok": True, "rows": [{"state": "tiles", "files": files}]}),
        encoding="utf-8",
    )

    result = _run(run_dir)

    assert result.returncode == 1, result.stdout + result.stderr
    report = json.loads((run_dir / "qa" / "asset-slot-review.json").read_text())
    assert any("tile_role values must be unique" in error for error in report["errors"])


def test_asset_repeat_gate_rejects_manifest_path_escape_before_preview(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    _write_texture_run(run_dir, broken_seam=False)
    outside = tmp_path / "outside.png"
    Image.new("RGBA", (32, 32), (70, 120, 45, 255)).save(outside)
    before = outside.read_bytes()
    manifest_path = run_dir / "frames" / "frames-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["rows"][0]["files"] = ["../outside.png"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = _run(run_dir)

    assert result.returncode != 0
    assert "path traversal" in result.stderr
    assert outside.read_bytes() == before
    assert not (run_dir / "qa").exists()
