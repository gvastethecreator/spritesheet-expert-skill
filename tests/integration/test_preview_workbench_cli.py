from __future__ import annotations

from hashlib import sha256
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "SKILLS" / "spritesheet-expert" / "scripts" / "build_preview_workbench.py"


def _write_run(run_dir: Path) -> tuple[Path, Path]:
    run_dir.mkdir(parents=True)
    atlas = Image.new("RGBA", (48, 32), (0, 0, 0, 0))
    draw = ImageDraw.Draw(atlas)
    for index, color in enumerate(((220, 70, 40, 255), (235, 120, 45, 255), (220, 70, 40, 255))):
        left = index * 16
        draw.rectangle((left + 4, 5, left + 11, 15), fill=color)
    for index, color in enumerate(((70, 150, 230, 255), (35, 85, 160, 255))):
        left = index * 16
        draw.rectangle((left + 3, 21, left + 12, 30), fill=color)
    atlas_path = run_dir / "sprite-sheet-alpha.png"
    atlas.save(atlas_path)
    manifest = {
        "version": 2,
        "kind": "sprite-atlas-manifest",
        "asset_kind": "sprite",
        "frame_semantics": "animation",
        "atlas": {"path": "sprite-sheet-alpha.png", "width": 48, "height": 32},
        "cell": {"width": 16, "height": 16},
        "frame_layout": {
            "rows": {
                "idle": [
                    {"x": 0, "y": 0, "w": 16, "h": 16},
                    {"x": 16, "y": 0, "w": 16, "h": 16},
                    {"x": 32, "y": 0, "w": 16, "h": 16},
                ],
                "blink": [
                    {"x": 0, "y": 16, "w": 16, "h": 16},
                    {"x": 16, "y": 16, "w": 16, "h": 16},
                ],
            },
            "packing": {"atlas_gutter": 0, "atlas_extrusion": 0},
        },
        "sampling_policy": {
            "filter": "nearest",
            "wrap": "clamp-to-edge",
            "mipmaps": False,
            "pixel_snap": True,
        },
        "animation": {
            "rows": {
                "idle": {"row": 0, "frames": 3, "fps": 6, "loop": True},
                "blink": {
                    "row": 1,
                    "frames": 2,
                    "fps": 4,
                    "loop": True,
                    "durations_ms": [120, 380],
                },
            }
        },
    }
    manifest_path = run_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    qa_dir = run_dir / "qa"
    qa_dir.mkdir()
    (qa_dir / "frame-alignment-report.json").write_text(
        json.dumps({"ok": True, "engine": "test-alignment"}),
        encoding="utf-8",
    )
    return atlas_path, manifest_path


def _run(run_dir: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--run-dir", str(run_dir), *extra],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_workbench_is_self_contained_hash_bound_and_covers_every_state(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    atlas_path, manifest_path = _write_run(run_dir)

    completed = _run(run_dir)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    response = json.loads(completed.stdout)
    html_path = run_dir / response["artifact"]["path"]
    report_path = run_dir / response["report_path"]
    html = html_path.read_text(encoding="utf-8")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["kind"] == "sprite-preview-workbench"
    assert report["states"] == ["idle", "blink"]
    assert report["initial_zoom"] == 8
    assert report["artifact"]["sha256"] == sha256(html_path.read_bytes()).hexdigest()
    sources = {item["role"]: item for item in report["sources"]}
    assert sources["atlas"]["sha256"] == sha256(atlas_path.read_bytes()).hexdigest()
    assert sources["manifest"]["sha256"] == sha256(manifest_path.read_bytes()).hexdigest()
    assert report["evidence"] == [
        {
            "role": "evidence",
            "path": "qa/frame-alignment-report.json",
            "sha256": sha256(
                (run_dir / "qa" / "frame-alignment-report.json").read_bytes()
            ).hexdigest(),
            "size_bytes": (
                run_dir / "qa" / "frame-alignment-report.json"
            ).stat().st_size,
            "label": "Alignment report",
        }
    ]
    assert 'src="data:image/png;base64,' in html
    assert 'data-testid="preview-stage"' in html
    assert 'tabindex="0"' in html
    assert 'aria-label="Play animation"' in html
    assert 'aria-label="Animation frame"' in html
    assert 'data-background="checker"' in html
    assert 'data-background="black"' in html
    assert 'data-background="gray"' in html
    assert 'data-background="white"' in html
    assert 'id="preview-data"' in html
    assert "link.target = '_blank'" in html
    assert "link.rel = 'noopener'" in html
    assert "prefers-reduced-motion:reduce" in html
    assert "if (!reducedMotion)" in html
    assert "querySelectorAll('.backgrounds button[data-background]')" in html
    assert "filmstrip.dataset.state !== state" in html
    assert "filmstrip.dataset.state = state" in html
    assert "zoomSelect.value = String(data.initialZoom)" in html
    assert 'canvas[data-sampling="nearest"]' in html
    assert 'canvas[data-sampling="linear"]' in html
    assert "https://" not in html and "http://" not in html


def test_workbench_refuses_stale_atlas_dimensions_before_writing(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _atlas, manifest_path = _write_run(run_dir)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["atlas"]["width"] = 49
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    completed = _run(run_dir)

    assert completed.returncode == 3
    assert not (run_dir / "qa" / "preview-workbench").exists()


def test_workbench_starts_large_provider_frames_at_a_fitted_zoom(tmp_path: Path) -> None:
    run_dir = tmp_path / "large-run"
    atlas_path, manifest_path = _write_run(run_dir)
    Image.new("RGBA", (576, 384), (0, 0, 0, 0)).save(atlas_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["atlas"].update({"width": 576, "height": 384})
    manifest["cell"] = {"width": 192, "height": 192}
    for row_index, state in enumerate(("idle", "blink")):
        for frame_index, rect in enumerate(manifest["frame_layout"]["rows"][state]):
            rect.update(
                {
                    "x": frame_index * 192,
                    "y": row_index * 192,
                    "w": 192,
                    "h": 192,
                }
            )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    completed = _run(run_dir)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    response = json.loads(completed.stdout)
    report = json.loads((run_dir / response["report_path"]).read_text(encoding="utf-8"))
    assert report["initial_zoom"] == 2
    html = (run_dir / response["artifact"]["path"]).read_text(encoding="utf-8")
    assert "function fitInitialZoom()" in html
    assert "stage.dataset.initialZoom = zoomSelect.value" in html
    assert "scrollbar-color:var(--line) #0d0d0c" in html
