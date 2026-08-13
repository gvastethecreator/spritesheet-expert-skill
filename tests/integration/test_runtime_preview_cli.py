from __future__ import annotations

from hashlib import sha256
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (
    REPO_ROOT
    / "SKILLS"
    / "spritesheet-expert"
    / "scripts"
    / "render_runtime_preview.py"
)
VALIDATE_RUN = (
    REPO_ROOT / "SKILLS" / "spritesheet-expert" / "scripts" / "validate_run.py"
)


def _write_run(run_dir: Path) -> tuple[Path, Path]:
    atlas = Image.new("RGBA", (16, 8), (0, 0, 0, 0))
    draw = ImageDraw.Draw(atlas)
    draw.rectangle((1, 2, 5, 7), fill=(220, 70, 40, 255))
    draw.rectangle((10, 1, 14, 7), fill=(40, 160, 230, 255))
    atlas_path = run_dir / "sprite-sheet-alpha.png"
    run_dir.mkdir(parents=True)
    atlas.save(atlas_path)
    manifest = {
        "version": 2,
        "kind": "sprite-atlas-manifest",
        "asset_kind": "sprite",
        "frame_semantics": "animation",
        "atlas": {"path": "sprite-sheet-alpha.png", "width": 16, "height": 8},
        "cell": {"width": 8, "height": 8},
        "frame_layout": {
            "rows": {
                "idle": [
                    {"x": 0, "y": 0, "w": 8, "h": 8},
                    {"x": 8, "y": 0, "w": 8, "h": 8},
                ]
            },
            "packing": {"atlas_gutter": 1, "atlas_extrusion": 1},
        },
        "sampling_policy": {
            "filter": "nearest",
            "wrap": "clamp-to-edge",
            "mipmaps": False,
            "pixel_snap": True,
        },
        "animation": {
            "rows": {
                "idle": {"row": 0, "frames": 2, "fps": 5, "loop": True}
            }
        },
    }
    manifest_path = run_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    request = {
        "version": 2,
        "kind": "sprite-gen-request",
        "asset_kind": "sprite",
        "frame_semantics": "animation",
        "extraction_mode": "components",
        "raw_layout_policy": "compact-body-grids",
        "source_type": "fixture",
        "cell": {"width": 8, "height": 8},
        "states": {
            "idle": {
                "frames": 2,
                "fps": 5,
                "loop": True,
                "raw_layout": {
                    "kind": "strip",
                    "columns": 2,
                    "rows": 1,
                    "order": "left-to-right",
                    "delivery": "compose-runtime-row",
                },
            }
        },
        "sampling_policy": manifest["sampling_policy"],
    }
    (run_dir / "sprite-request.json").write_text(json.dumps(request), encoding="utf-8")
    return atlas_path, manifest_path


def _run(run_dir: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--run-dir",
            str(run_dir),
            "--state",
            "idle",
            *extra,
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_runtime_preview_renders_hash_bound_deterministic_playback(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    atlas_path, manifest_path = _write_run(run_dir)

    completed = _run(
        run_dir,
        "--kind",
        "runtime-playback",
        "--viewport",
        "32x24",
        "--dpr",
        "2",
        "--scale",
        "2",
        "--background",
        "#101018",
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    response = json.loads(completed.stdout)
    assert response["status"] == "pass"
    artifact_path = run_dir / response["artifact"]["path"]
    report_path = run_dir / response["report_path"]
    assert artifact_path.suffix == ".gif"
    assert artifact_path.is_file() and report_path.is_file()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["kind"] == "screenshot-evidence"
    assert report["evidence_kind"] == "runtime-playback"
    assert report["artifact"]["sha256"] == sha256(artifact_path.read_bytes()).hexdigest()
    assert report["artifact"]["width"] == 64
    assert report["artifact"]["height"] == 48
    assert report["viewport"] == {"width": 32, "height": 24, "dpr": 2.0}
    assert report["sampling"] == "nearest"
    assert report["frames"] == [0, 1]
    assert report["durations_ms"] == [200, 200]
    sources = {source["role"]: source for source in report["sources"]}
    assert sources["atlas"]["sha256"] == sha256(atlas_path.read_bytes()).hexdigest()
    assert sources["manifest"]["sha256"] == sha256(manifest_path.read_bytes()).hexdigest()
    assert all(not Path(source["path"]).is_absolute() for source in report["sources"])

    original = artifact_path.read_bytes()
    repeated = _run(
        run_dir,
        "--kind",
        "runtime-playback",
        "--viewport",
        "32x24",
        "--dpr",
        "2",
        "--scale",
        "2",
        "--background",
        "#101018",
        "--force",
    )
    assert repeated.returncode == 0, repeated.stdout + repeated.stderr
    assert artifact_path.read_bytes() == original


def test_runtime_preview_renders_one_runtime_still(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _write_run(run_dir)

    completed = _run(
        run_dir,
        "--kind",
        "runtime-still",
        "--frame",
        "1",
        "--viewport",
        "16x16",
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    response = json.loads(completed.stdout)
    assert response["artifact"]["path"].endswith(".png")
    report = json.loads((run_dir / response["report_path"]).read_text(encoding="utf-8"))
    assert report["frames"] == [1]
    assert report["durations_ms"] == [200]


def test_runtime_preview_auto_fits_manifest_cell(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _write_run(run_dir)

    completed = _run(run_dir, "--kind", "runtime-playback")

    assert completed.returncode == 0, completed.stdout + completed.stderr
    report = json.loads(
        (run_dir / json.loads(completed.stdout)["report_path"]).read_text(
            encoding="utf-8"
        )
    )
    assert report["viewport"] == {"width": 8, "height": 8, "dpr": 1.0}
    assert report["placements"][0]["width"] == 8
    assert report["placements"][0]["height"] == 8


def test_runtime_preview_rejects_stale_or_wrong_atlas_before_mutation(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    _atlas_path, manifest_path = _write_run(run_dir)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["atlas"]["width"] = 17
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    completed = _run(run_dir)

    assert completed.returncode == 3
    response = json.loads(completed.stdout)
    assert response["status"] == "operational-error"
    assert "dimensions" in response["errors"][0]
    assert not (run_dir / "qa" / "runtime-preview").exists()


def test_runtime_preview_rejects_unsafe_or_source_output_paths(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    _write_run(run_dir)
    sentinel = tmp_path / "outside.gif"

    traversal = _run(run_dir, "--out", "../outside.gif")
    raw_source = _run(run_dir, "--out", "raw/idle.png")

    assert traversal.returncode == 3
    assert raw_source.returncode == 3
    assert not sentinel.exists()
    assert not (run_dir / "raw").exists()


def test_runtime_preview_refuses_overwrite_without_force(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _write_run(run_dir)
    first = _run(run_dir)
    assert first.returncode == 0
    artifact = run_dir / json.loads(first.stdout)["artifact"]["path"]
    before = artifact.read_bytes()

    second = _run(run_dir)

    assert second.returncode == 3
    assert artifact.read_bytes() == before


def test_prepackage_runtime_gate_consumes_current_playback_evidence(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    _write_run(run_dir)
    rendered = _run(run_dir)
    assert rendered.returncode == 0, rendered.stdout + rendered.stderr

    completed = subprocess.run(
        [
            sys.executable,
            str(VALIDATE_RUN),
            "--run-dir",
            str(run_dir),
            "--stage",
            "pre-package",
            "--gate",
            "runtime-preview",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 2
    report = json.loads(
        (run_dir / "qa" / "run-validation-report.json").read_text(encoding="utf-8")
    )
    runtime = next(item for item in report["results"] if item["id"] == "runtime-preview")
    assert runtime["status"] == "pass"
    assert runtime["checked_items"] == ["idle"]
    assert any("partial" in blocker for blocker in report["blockers"])
