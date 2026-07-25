from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "SKILLS" / "spritesheet-expert" / "scripts" / "build_motion_sequence_review.py"


def make_frame(path: Path, *, top: int, bottom: int, belt_y: int) -> None:
    image = Image.new("RGB", (512, 512), (247, 243, 234))
    draw = ImageDraw.Draw(image)
    draw.ellipse((220, top, 292, top + 72), fill=(65, 55, 48))
    draw.rectangle((210, top + 70, 302, bottom - 100), fill=(210, 120, 40))
    draw.rectangle((190, belt_y, 320, belt_y + 14), fill=(12, 12, 12))
    draw.line((235, bottom - 100, 220, bottom), fill=(25, 50, 70), width=24)
    draw.line((275, bottom - 100, 292, bottom), fill=(25, 50, 70), width=24)
    image.save(path)


def test_baseline_uses_lowest_subject_row_not_darkest_lower_row(tmp_path: Path) -> None:
    first = tmp_path / "frame-1.png"
    second = tmp_path / "frame-2.png"
    make_frame(first, top=30, bottom=470, belt_y=360)
    make_frame(second, top=45, bottom=485, belt_y=350)
    report = tmp_path / "review-report.json"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--frame",
            str(first),
            "--frame",
            str(second),
            "--selected-dir",
            str(tmp_path / "selected"),
            "--sheet",
            str(tmp_path / "sheet.png"),
            "--report",
            str(report),
            "--columns",
            "2",
            "--cell-size",
            "256",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["frames"][0]["source_baseline_y"] >= 465
    assert payload["frames"][1]["translation_y"] < 0
    assert payload["frames"][1]["subject_bbox"][1] > 0

