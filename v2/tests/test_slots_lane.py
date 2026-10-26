"""End-to-end slots lane: icons that fill their cells, UI states at one size, a stretchable panel.

The fixture is test geometry, not art: shapes of different sizes on one transparent sheet.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

SKILL = Path(__file__).resolve().parents[1] / "spritesheet-expert"
sys.path.insert(0, str(SKILL))

from spritekit import cli  # noqa: E402

CELL = 200


def combined_sheet() -> Image.Image:
    img = Image.new("RGBA", (3 * CELL, 3 * CELL), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # Row 1, icons drawn at very different sizes.
    d.ellipse([80, 80, 120, 120], fill=(220, 60, 60, 255))
    d.rectangle([CELL + 20, 20, CELL + 180, 180], fill=(60, 160, 90, 255))
    d.polygon([(2 * CELL + 100, 50), (2 * CELL + 160, 150), (2 * CELL + 40, 150)], fill=(60, 90, 200, 255))
    # Row 2, one button in two states at the same size.
    for k, color in enumerate([(90, 140, 230, 255), (60, 100, 190, 255)]):
        d.rounded_rectangle([k * CELL + 30, CELL + 70, k * CELL + 170, CELL + 130], radius=14, fill=color)
    # Row 3, a panel: thick border, plain middle.
    d.rounded_rectangle([20, 2 * CELL + 30, 180, 2 * CELL + 170], radius=18, fill=(70, 60, 50, 255))
    d.rectangle([34, 2 * CELL + 44, 166, 2 * CELL + 156], fill=(235, 225, 205, 255))
    return img


def test_slots_build_names_fills_and_nine_slices(tmp_path: Path) -> None:
    run = tmp_path / "run"
    assert cli.main(["plan", "--out", str(run), "--lane", "slots", "--subject", "a test ui kit", "--cell", "128",
                     "--set", "icons:fill=heart,crate,arrow", "--set", "button=normal,pressed",
                     "--set", "panel:nine=window"]) == 0
    assert (run / "prompts" / "_all.txt").exists() and not (run / "prompts" / "icons").exists()
    combined_sheet().save(tmp_path / "all.png")
    assert cli.main(["build", str(run), "--source", f"all={tmp_path / 'all.png'}"]) == 0

    atlas = json.loads((run / "atlas.json").read_text())
    assert [f["name"] for f in atlas["states"]["icons"]["frames"]] == ["heart", "crate", "arrow"]
    window = atlas["states"]["panel"]["frames"][0]["nine_slice"]
    assert window and all(m > 0 for m in window["slice"])

    # Icons fill their cells whatever size they were drawn at; button states keep one size.
    def extent(name: str) -> list[int]:
        out = []
        for png in sorted((run / "frames" / name).glob("*.png")):
            box = Image.open(png).getchannel("A").getbbox()
            out.append(max(box[2] - box[0], box[3] - box[1]))
        return out
    icons, buttons = extent("icons"), extent("button")
    assert max(icons) / min(icons) < 1.1 and max(buttons) / min(buttons) < 1.05

    built = json.loads((run / "run.json").read_text())["build"]["states"]
    assert {c["id"] for c in built["icons"]["checks"]}.isdisjoint({"color", "identity", "motion", "scale"})
    assert next(c for c in built["panel"]["checks"] if c["id"] == "stretch")["status"] == "pass"
    assert cli.main(["check", str(run), "--strict"]) == 0
    assert np.asarray(Image.open(run / "atlas.png")).shape[:2] == (3 * 128, 3 * 128)
