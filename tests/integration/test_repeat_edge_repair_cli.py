from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

from PIL import Image
import pytest
import repair_repeat_edges as repair


REPO_ROOT = Path(__file__).resolve().parents[2]
REPAIR = (
    REPO_ROOT
    / "SKILLS"
    / "spritesheet-expert"
    / "scripts"
    / "repair_repeat_edges.py"
)


def _write_run(run_dir: Path, relative: str = "frames/materials/moss.png") -> tuple[Path, Path]:
    (run_dir / "frames").mkdir(parents=True)
    (run_dir / "raw").mkdir()
    source = run_dir / "raw" / "accepted.png"
    image = Image.new("RGBA", (32, 32))
    for y in range(32):
        for x in range(32):
            image.putpixel((x, y), (20 + x * 6, 60 + y * 3, 40, 255))
    image.save(source)
    frame = run_dir / "frames/materials/moss.png"
    frame.parent.mkdir()
    image.save(frame)
    request = {
        "version": 2,
        "kind": "sprite-gen-request",
        "asset_kind": "texture",
        "frame_semantics": "seamless-textures",
        "extraction_mode": "slots",
        "raw_layout_policy": "compact-body-grids",
        "cell": {"width": 32, "height": 32, "safe_margin": 0},
        "states": {
            "materials": {
                "frames": 1,
                "fps": 1,
                "asset_labels": ["moss"],
                "raw_layout": {
                    "kind": "strip",
                    "columns": 1,
                    "rows": 1,
                    "order": "left-to-right",
                    "delivery": "compose-runtime-row",
                },
            }
        },
        "sampling_policy": {
            "filter": "linear",
            "wrap": "repeat",
            "mipmaps": False,
            "pixel_snap": False,
        },
        "asset_catalog": {
            "items": {
                "moss": {
                    "category": "materials",
                    "pivot": [16, 16],
                    "repeat_mode": "self",
                }
            }
        },
    }
    provenance = {
        "version": 2,
        "kind": "sprite-source-provenance",
        "source_type": "imagegen",
        "art_engine": "imagegen",
        "fixture": False,
        "verification_status": "verified",
        "accepted_sources": [
            {
                "path": "raw/accepted.png",
                "sha256": sha256(source.read_bytes()).hexdigest(),
                "size_bytes": source.stat().st_size,
                "states": ["materials"],
            }
        ],
        "state_coverage": ["materials"],
    }
    (run_dir / "sprite-request.json").write_text(
        json.dumps(request), encoding="utf-8"
    )
    (run_dir / "source-provenance.json").write_text(
        json.dumps(provenance), encoding="utf-8"
    )
    (run_dir / "frames" / "frames-manifest.json").write_text(
        json.dumps(
            {
                "ok": True,
                "rows": [
                    {"state": "materials", "files": [relative]}
                ],
            }
        ),
        encoding="utf-8",
    )
    return source, frame


def test_repeat_repair_rejects_manifest_path_escape_before_mutation(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    _write_run(run_dir, "../outside.png")
    outside = tmp_path / "outside.png"
    Image.new("RGBA", (32, 32), (70, 120, 45, 255)).save(outside)
    before = sha256(outside.read_bytes()).hexdigest()

    result = subprocess.run(
        [sys.executable, str(REPAIR), "--run-dir", str(run_dir), "--labels", "moss"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "path traversal" in result.stderr
    assert sha256(outside.read_bytes()).hexdigest() == before
    assert not (run_dir / "provider").exists()


def test_repeat_repair_records_actual_widths_and_keeps_immutable_inputs_on_replay(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    source, frame = _write_run(run_dir)
    original = frame.read_bytes()
    command = [sys.executable, str(REPAIR), "--run-dir", str(run_dir), "--labels", "moss"]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    report_path = run_dir / "qa/repeat-edge-repair-report.json"
    report = json.loads(report_path.read_text())
    record = report["records"][0]
    assert report["blend_width"] == 20
    assert record["effective_blend_width"] == 10
    assert record["effective_edge_strip"] == 2
    assert record["center_preserved"] is report["center_preserved"] is True
    backup = run_dir / record["prior_frame_source"]
    assert backup.read_bytes() == source.read_bytes() == original
    with Image.open(backup) as before, Image.open(frame) as after:
        assert before.crop((10, 10, 22, 22)).tobytes() == after.crop((10, 10, 22, 22)).tobytes()
    phase_dir = tmp_path / "phase"
    phase_dir.mkdir()
    phase_image = Image.new("RGBA", (64, 64), (140, 120, 90, 255))
    phase_image.save(phase_dir / "moss.png")
    command += ["--force", "--phase-source-dir", str(phase_dir), "--provider", "imagegen", "--phase-max-trim-ratio", "0"]
    previous_output = None
    for _ in range(2):
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        assert completed.returncode == 0, completed.stdout + completed.stderr
        report = json.loads(report_path.read_text())
        record = report["records"][0]
        assert record["effective_blend_width"] == record["effective_edge_strip"] == 2
        assert record["center_preserved"] is report["center_preserved"] is False
        assert (run_dir / record["source"]).read_bytes() == (phase_dir / "moss.png").read_bytes()
        assert backup.read_bytes() == source.read_bytes() == original
        if previous_output is not None:
            assert frame.read_bytes() == previous_output
        previous_output = frame.read_bytes()
    provenance = json.loads((run_dir / "source-provenance.json").read_text())
    assert len(provenance["accepted_sources"]) == 2


@pytest.mark.parametrize("relative", ["raw/accepted.png", "qa/repeat-edge-repair-report.json"])
def test_repeat_repair_preserves_a_source_or_report_used_as_a_frame(tmp_path: Path, relative: str) -> None:
    run_dir = tmp_path / "run"
    source, _ = _write_run(run_dir, relative)
    target = run_dir / relative
    target.parent.mkdir(exist_ok=True)
    target.write_bytes(source.read_bytes())
    before = target.read_bytes()
    completed = subprocess.run(
        [sys.executable, str(REPAIR), "--run-dir", str(run_dir), "--labels", "moss"],
        capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 3
    assert target.read_bytes() == before
    assert not (run_dir / "provider").exists()


def test_repeat_repair_stops_if_the_manifest_changes_during_preflight(tmp_path: Path, monkeypatch) -> None:
    run_dir = tmp_path / "run"
    _, frame = _write_run(run_dir)
    before = frame.read_bytes()
    manifest_path = run_dir / "frames/frames-manifest.json"
    original = repair.harmonize_repeat_edges

    def change_manifest(image, **kwargs):
        result = original(image, **kwargs)
        manifest = json.loads(manifest_path.read_text())
        manifest["ok"] = False
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        return result

    monkeypatch.setattr(repair, "harmonize_repeat_edges", change_manifest)
    monkeypatch.setattr(sys, "argv", [str(REPAIR), "--run-dir", str(run_dir), "--labels", "moss"])
    with pytest.raises(ValueError, match="input changed during preflight"):
        repair.main()
    assert frame.read_bytes() == before
    assert not (run_dir / "provider").exists()
