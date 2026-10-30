from __future__ import annotations

import json
import base64
from io import BytesIO
from pathlib import Path
import re
import subprocess
import sys

from PIL import Image, ImageDraw
import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "SKILLS" / "spritesheet-expert" / "scripts"
INGEST = SCRIPTS / "ingest_video_animation.py"


def _request() -> dict[str, object]:
    return {
        "version": 2,
        "kind": "sprite-gen-request",
        "asset_kind": "sprite",
        "frame_semantics": "animation",
        "extraction_mode": "components",
        "raw_layout_policy": "compact-body-grids",
        "cell": {"width": 32, "height": 32, "safe_margin": 2},
        "generation_background": {
            "family": "neutral",
            "name": "black",
            "hex": "#000000",
            "rgb": [0, 0, 0],
        },
        "states": {
            "walk": {
                "frames": 4,
                "fps": 8,
                "loop": True,
                "action": "walk in place",
                "raw_layout": {
                    "kind": "compact-grid",
                    "columns": 2,
                    "rows": 2,
                    "order": "row-major",
                    "delivery": "compose-runtime-row",
                },
            }
        },
    }


def test_imported_video_builds_raw_provenance_and_required_selector(tmp_path: Path) -> None:
    imageio_ffmpeg = pytest.importorskip("imageio_ffmpeg")
    run_dir = tmp_path / "run ' [review] $cash"
    run_dir.mkdir()
    (run_dir / "sprite-request.json").write_text(
        json.dumps(_request()), encoding="utf-8"
    )
    first_frame = tmp_path / "first.png"
    first = Image.new("RGB", (32, 32), "black")
    ImageDraw.Draw(first).rectangle((7, 8, 18, 25), fill=(60, 195, 75))
    first.save(first_frame)
    video_path = tmp_path / "walk.mp4"
    writer = imageio_ffmpeg.write_frames(
        str(video_path),
        (32, 32),
        fps=12,
        codec="libx264",
        quality=8,
        macro_block_size=16,
    )
    writer.send(None)
    try:
        for index in range(36):
            frame = Image.new("RGB", (32, 32), "black")
            draw = ImageDraw.Draw(frame)
            offset = (index % 12) - 6
            draw.rectangle((10 + offset // 2, 8, 21 + offset // 2, 25), fill=(190, 90, 45))
            writer.send(frame.tobytes())
    finally:
        writer.close()

    completed = subprocess.run(
        [
            sys.executable,
            str(INGEST),
            "--run-dir",
            str(run_dir),
            "--state",
            "walk",
            "--video",
            str(video_path),
            "--first-frame",
            str(first_frame),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    response = json.loads(completed.stdout)
    report_path = run_dir / response["report_path"]
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["kind"] == "sprite-video-source"
    assert report["origin"] == "imported"
    assert report["independent_frame_background_removal"] is True
    assert len(report["selection_metrics"]["candidate_sets"]) >= 2
    assert (run_dir / "raw" / "walk.png").is_file()
    assert (run_dir / report["video"]["path"]).is_file()
    selector = run_dir / "qa" / "walk-video-frame-selector" / "index.html"
    evidence_path = selector.parent / "selector.evidence.json"
    assert selector.is_file()
    selector_html = selector.read_text(encoding="utf-8")
    assert "unsafeFrames" in selector_html
    assert "scaleUnsafeFrames" in selector_html
    assert "EDGE" in selector_html
    assert "SCALE" in selector_html
    assert "no source-edge flags" in selector_html
    payload = json.loads(re.search(r"const data=(\{.*\});", selector_html).group(1))
    with Image.open(BytesIO(base64.b64decode(payload["idleThumbnail"].split(",", 1)[1]))) as idle:
        red, green, blue = idle.getpixel((78, 22))
        assert green > red + 70 and green > blue + 70
    assert payload["idleThumbnail"] != payload["thumbnails"][0]
    assert payload["videoUrl"] == "../../provider/video/walk/source.mp4"
    assert "Copy reviewed command" in selector_html
    assert "reviewContract" in selector_html
    assert "confirm all review checks" in selector_html
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["status"] == "pass"
    assert evidence["decoded_frame_count"] == 36
    provenance = json.loads((run_dir / "source-provenance.json").read_text(encoding="utf-8"))
    assert provenance["source_type"] == "imported"
    assert provenance["accepted_sources"][0]["upstream_report"] == report_path.relative_to(run_dir).as_posix()
    provenance_gate = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "check_generation_provenance.py"),
            "--run-dir",
            str(run_dir),
            "--allow-imported-source",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert provenance_gate.returncode == 0, provenance_gate.stdout + provenance_gate.stderr
    gate_report = json.loads(provenance_gate.stdout)
    assert gate_report["evidence"]["video_selectors"][0]["candidate_count"] >= 2
    for label in ("video", "first_frame", "sprite_request"):
        source_path = run_dir / report[label]["path"]
        original = source_path.read_bytes()
        try:
            source_path.write_bytes(original + b"\n")
            changed = subprocess.run(
                provenance_gate.args, cwd=REPO_ROOT, capture_output=True, text=True, check=False,
            )
            assert changed.returncode == 1, changed.stdout + changed.stderr
            assert f"video source {label} bytes changed" in changed.stdout
        finally:
            source_path.write_bytes(original)
    extracted = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "extract_sprite_row_frames.py"),
            "--run-dir",
            str(run_dir),
            "--min-used-pixels",
            "8",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert extracted.returncode == 0, extracted.stdout + extracted.stderr
    frame_manifest = json.loads(
        (run_dir / "frames" / "frames-manifest.json").read_text(encoding="utf-8")
    )
    row = frame_manifest["rows"][0]
    assert row["method"] == "video-independent-adaptive"
    assert row["segmentation"]["boundary_policy"] == "fail-on-source-edge-contact"
    assert all(
        frame["safe_margin_pixels"] == 0 for frame in row["frame_records"]
    )
    selector.write_text(selector.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    stale_gate = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "check_generation_provenance.py"),
            "--run-dir",
            str(run_dir),
            "--allow-imported-source",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert stale_gate.returncode == 1
    assert "selector HTML is missing or changed" in stale_gate.stdout
