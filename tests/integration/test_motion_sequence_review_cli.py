from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw
import pytest


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


def run_review(first: Path, second: Path, selected: Path, sheet: Path, report: Path, cell_size: int = 256) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--frame", str(first), "--frame", str(second),
         "--selected-dir", str(selected), "--sheet", str(sheet), "--report", str(report),
         "--columns", "2", "--cell-size", str(cell_size)],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )


def test_baseline_uses_lowest_subject_row_not_darkest_lower_row(tmp_path: Path) -> None:
    first = tmp_path / "frame-1.png"
    second = tmp_path / "frame-2.png"
    make_frame(first, top=30, bottom=470, belt_y=360)
    make_frame(second, top=45, bottom=485, belt_y=350)
    report = tmp_path / "review-report.json"
    result = run_review(first, second, tmp_path / "selected", tmp_path / "sheet.png", report)
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["frames"][0]["source_baseline_y"] >= 465
    assert payload["frames"][1]["translation_y"] < 0
    assert payload["frames"][1]["subject_bbox"][1] > 0

    before = first.read_bytes()
    collision = run_review(first, second, tmp_path / "selected", first, report)
    assert collision.returncode != 0
    assert "cannot overwrite source frames" in collision.stderr
    assert first.read_bytes() == before


def test_translation_rejects_clipping_and_preserves_alpha() -> None:
    from build_motion_sequence_review import translate_to_baseline

    image = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle((4, 0, 15, 31), fill=(100, 40, 20, 255))
    with pytest.raises(ValueError, match="clip detected foreground"):
        translate_to_baseline(image, 31, 15)
    image = Image.new("RGBA", (64, 32), (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle((4, 8, 15, 20), fill=(100, 40, 20, 128))
    translated = translate_to_baseline(image, 20, 25)
    assert translated.getpixel((4, 13)) == image.getpixel((4, 8))
    assert translated.getchannel("A").histogram() == image.getchannel("A").histogram()


def test_contact_sheet_keeps_non_square_geometry_and_selected_transparency(tmp_path: Path) -> None:
    first, second = tmp_path / "first.png", tmp_path / "second.png"
    for path, offset in ((first, 0), (second, 5)):
        image = Image.new("RGBA", (96, 64), (0, 0, 0, 0))
        ImageDraw.Draw(image).rectangle((20, 10 + offset, 40, 50 + offset), fill=(100, 40, 20, 128))
        image.save(path)
    selected, sheet = tmp_path / "selected", tmp_path / "sheet.png"
    result = run_review(first, second, selected, sheet, tmp_path / "report.json", cell_size=96)
    assert result.returncode == 0, result.stdout + result.stderr
    with Image.open(selected / "frame-02.png") as frame:
        assert frame.mode == "RGBA"
        assert frame.getpixel((20, 10)) == (100, 40, 20, 128)
        assert frame.getpixel((0, 0))[3] == 0
    with Image.open(sheet) as board:
        foreground = [(x, y) for y in range(96) for x in range(96) if board.getpixel((x, y)) != (17, 17, 17)]
    assert (min(x for x, _ in foreground), max(x for x, _ in foreground)) == (20, 40)
    assert (min(y for _, y in foreground), max(y for _, y in foreground)) == (26, 66)

