"""End-to-end atlas lane: loose items on a flat gray sheet, separated by shape and packed.

The fixture is test geometry, not art: a bottle with a detached cork, a big crate, a
small coin, and one far speck.
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

GRAY = (128, 128, 128)
CORK = (150, 90, 40)


def loose_sheet(touching: bool = False) -> Image.Image:
    img = Image.new("RGB", (900, 600), GRAY)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([90, 140, 190, 330], radius=30, fill=(60, 140, 200))   # bottle
    d.rectangle([120, 112, 160, 132], fill=CORK)                                  # cork, 8 px above
    crate_x = 192 if touching else 380
    d.rectangle([crate_x, 90, crate_x + 260, 350], fill=(170, 110, 60))          # crate
    d.ellipse([720, 190, 800, 270], fill=(230, 190, 60))                          # coin
    d.ellipse([450, 520, 454, 524], fill=(20, 20, 20))                            # speck
    return img


def plan(tmp_path: Path) -> Path:
    run = tmp_path / "run"
    assert cli.main(["plan", "--out", str(run), "--lane", "atlas", "--subject", "test props", "--cell", "128",
                     "--set", "props=bottle,crate,coin"]) == 0
    return run


def test_atlas_separates_loose_items_and_packs_them(tmp_path: Path) -> None:
    run = plan(tmp_path)
    assert (run / "prompts" / "props.txt").exists() and not (run / "guides" / "props.png").exists()
    loose_sheet().save(tmp_path / "props.png")
    assert cli.main(["build", str(run), "--source", f"props={tmp_path / 'props.png'}"]) == 0

    atlas = json.loads((run / "atlas.json").read_text())
    items = {f["name"]: f for f in atlas["states"]["props"]["frames"]}
    assert list(items) == ["bottle", "crate", "coin"]
    # One shared scale: the crate stays the biggest, the coin the smallest.
    assert items["crate"]["w"] > items["bottle"]["w"] > items["coin"]["w"]
    # The detached cork belongs to the bottle.
    bottle = np.asarray(Image.open(run / "frames" / "props" / "01.png").convert("RGB"))
    assert (np.abs(bottle.astype(int) - CORK).sum(axis=2) < 30).any()

    built = json.loads((run / "run.json").read_text())["build"]["states"]["props"]
    assert built["cutout"]["specks"] == 1
    assert next(c for c in built["checks"] if c["id"] == "items")["status"] == "pass"
    assert cli.main(["check", str(run), "--strict"]) == 0


def test_touching_items_fail_the_count(tmp_path: Path) -> None:
    run = plan(tmp_path)
    loose_sheet(touching=True).save(tmp_path / "props.png")
    assert cli.main(["build", str(run), "--source", f"props={tmp_path / 'props.png'}"]) == 0
    checks = json.loads((run / "run.json").read_text())["build"]["states"]["props"]["checks"]
    assert next(c for c in checks if c["id"] == "items")["status"] == "fail"
    assert cli.main(["check", str(run), "--strict"]) == 1
