"""End-to-end animation lane: plan → build → check on a synthetic sheet.

The fixture is test geometry, not art: a figure with swinging legs drawn in a
4x2 grid with per-cell jitter, a per-cell scale change and an enclosed ring.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

SKILL = Path(__file__).resolve().parents[1] / "spritesheet-expert"
sys.path.insert(0, str(SKILL))

from spritekit import cli, planner  # noqa: E402

CELL = 300
GRAY = (128, 128, 128)


def figure(draw: ImageDraw.ImageDraw, ox: float, oy: float, s: float, phase: float) -> None:
    body = (40, 90, 160)
    draw.ellipse([ox - 22 * s, oy - 170 * s, ox + 22 * s, oy - 126 * s], fill=(230, 180, 140))
    draw.rectangle([ox - 26 * s, oy - 126 * s, ox + 26 * s, oy - 60 * s], fill=body)
    for side in (-1, 1):
        angle = math.sin(phase) * 0.5 * side
        fx, fy = ox + math.sin(angle) * 60 * s, oy - 60 * s + math.cos(angle) * 60 * s
        draw.line([ox, oy - 60 * s, fx, fy], fill=(30, 30, 40), width=max(2, int(10 * s)))
    # A ring held out front: its inside is enclosed background that must become transparent.
    draw.ellipse([ox + 30 * s, oy - 120 * s, ox + 80 * s, oy - 70 * s], outline=(200, 60, 50), width=max(2, int(8 * s)))


def sheet(frames: int = 8, drop: int | None = None, transparent: bool = False, size: float = 1.0) -> Image.Image:
    cols, rows = planner.grid_for(frames)
    mode, fill = ("RGBA", (0, 0, 0, 0)) if transparent else ("RGB", GRAY)
    img = Image.new(mode, (cols * CELL, rows * CELL), fill)
    draw = ImageDraw.Draw(img)
    rng = np.random.default_rng(7)
    for i in range(frames):
        if i == drop:
            continue
        cx, cy = (i % cols) * CELL + CELL / 2, (i // cols) * CELL
        jitter_x, jitter_y = rng.integers(-14, 15), rng.integers(-12, 13)
        scale = (0.92 + 0.12 * (i % 3) / 2) * size
        figure(draw, cx + jitter_x, cy + 260 + jitter_y, scale, i * 2 * math.pi / frames)
    return img


def plan_run(tmp_path: Path, extra: list[str] | None = None) -> Path:
    run = tmp_path / "run"
    assert cli.main(["plan", "--out", str(run), "--subject", "a test figure", "--state", "walk:8",
                     "--cell", "128", *(extra or [])]) == 0
    return run


def test_plan_writes_prompt_guide_and_grid(tmp_path: Path) -> None:
    run = plan_run(tmp_path)
    data = json.loads((run / "run.json").read_text())
    state = data["states"][0]
    assert state["grid"] == [4, 2] and len(state["phases"]) == 8
    prompt = (run / "prompts" / "walk.txt").read_text()
    assert "4 columns x 2 rows" in prompt and "8. up" in prompt and "#808080" in prompt
    assert Image.open(run / "guides" / "walk.png").size == (4 * planner.GUIDE_CELL, 2 * planner.GUIDE_CELL)


def test_plan_writes_frame_prompts_and_mirrored_pose_guides(tmp_path: Path) -> None:
    run = tmp_path / "run"
    assert cli.main(["plan", "--out", str(run), "--subject", "a knight", "--view", "side view, facing left",
                     "--pose-guide", "openpose", "--state", "smash:6:attack-overhead"]) == 0
    assert len(list((run / "prompts" / "smash").glob("*.txt"))) == 6
    frame2 = (run / "prompts" / "smash" / "02.txt").read_text()
    assert "frame 1 of this same animation" in frame2 and "OpenPose skeleton" in frame2
    assert "pose_height" in json.loads((run / "run.json").read_text())["states"][0]["phases"][0]
    keypoints = json.loads((run / "poses" / "smash" / "04.openpose.json").read_text())["people"][0]["pose_keypoints_2d"]
    nose_x, neck_x = keypoints[0], keypoints[3]
    assert len(keypoints) == 18 * 3 and nose_x < neck_x  # facing left: the nose is left of the neck


def test_pose_guided_frames_get_the_size_their_pose_asks_for(tmp_path: Path) -> None:
    run = tmp_path / "run"
    assert cli.main(["plan", "--out", str(run), "--subject", "a test figure", "--cell", "128",
                     "--state", "idle:4"]) == 0
    full = sheet(frames=4, transparent=True)
    folder = tmp_path / "frames"
    folder.mkdir()
    for i in range(4):
        cell = full.crop((i * CELL, 0, (i + 1) * CELL, CELL))
        if i == 2:  # the model drew this frame 30% too small
            cell = cell.resize((round(CELL * 0.7), round(CELL * 0.7)), Image.Resampling.LANCZOS)
        cell.save(folder / f"{i + 1:02d}.png")
    assert cli.main(["build", str(run), "--source", f"idle={folder}"]) == 0
    built = json.loads((run / "run.json").read_text())["build"]["states"]["idle"]
    assert built["cutout"]["size_factors"][2] > 1.2
    heights = []
    for png in sorted((run / "frames" / "idle").glob("*.png")):
        rows = np.nonzero((np.asarray(Image.open(png).getchannel("A")) >= 16).any(axis=1))[0]
        heights.append(rows.max() - rows.min())
    assert max(heights) / min(heights) < 1.15


@pytest.mark.parametrize("frames,grid", [(4, (4, 1)), (5, (3, 2)), (6, (3, 2)), (8, (4, 2)), (12, (4, 3))])
def test_compact_grids(frames: int, grid: tuple[int, int]) -> None:
    assert planner.grid_for(frames) == grid


@pytest.mark.parametrize("transparent", [False, True])
def test_build_registers_frames_on_one_baseline_with_one_scale(tmp_path: Path, transparent: bool) -> None:
    run = plan_run(tmp_path)
    src = tmp_path / "walk.png"
    sheet(transparent=transparent).save(src)
    assert cli.main(["build", str(run), "--source", f"walk={src}", "--provider", "fixture"]) == 0

    data = json.loads((run / "run.json").read_text())
    built = data["build"]["states"]["walk"]
    assert built["cutout"]["method"] == ("native-alpha" if transparent else "matte")
    assert data["sources"]["walk"]["sha256"] and data["sources"]["walk"]["provider"] == "fixture"

    baseline = round(128 * 0.9)
    bottoms = []
    for i in range(1, 9):
        a = np.asarray(Image.open(run / "frames" / "walk" / f"{i:02d}.png").getchannel("A"))
        rows = np.nonzero((a >= 16).any(axis=1))[0]
        bottoms.append(rows.max() + 1)
    assert max(bottoms) - min(bottoms) <= 1 and abs(bottoms[0] - baseline) <= 1

    if not transparent:
        # Each of the 8 rings encloses gray that must become transparent, not stay as a gray disc.
        assert built["cutout"]["enclosed_holes_removed"] >= 8

    atlas = json.loads((run / "atlas.json").read_text())
    assert len(atlas["states"]["walk"]["frames"]) == 8 and atlas["pivot"] == [64, baseline]
    page = (run / "review.html").read_text(encoding="utf-8")
    assert "http://" not in page and "https://" not in page and '"name": "walk"' in page
    assert cli.main(["check", str(run)]) == 0


def test_states_drawn_at_different_sizes_get_one_character_size(tmp_path: Path) -> None:
    run = plan_run(tmp_path, ["--state", "idle:4"])
    walk, idle = tmp_path / "walk.png", tmp_path / "idle.png"
    sheet().save(walk)
    sheet(frames=4, size=0.6).save(idle)
    assert cli.main(["build", str(run), "--source", f"walk={walk}", "--source", f"idle={idle}"]) == 0

    def median_height(state: str) -> float:
        heights = []
        for png in sorted((run / "frames" / state).glob("*.png")):
            rows = np.nonzero((np.asarray(Image.open(png).getchannel("A")) >= 16).any(axis=1))[0]
            heights.append(rows.max() - rows.min())
        return float(np.median(heights))

    assert abs(median_height("walk") - median_height("idle")) <= 2


def test_folder_of_frames_is_laid_into_the_grid(tmp_path: Path) -> None:
    run = plan_run(tmp_path)
    full = sheet(transparent=True)
    folder = tmp_path / "frames"
    folder.mkdir()
    for i in range(8):
        x, y = (i % 4) * CELL, (i // 4) * CELL
        full.crop((x, y, x + CELL, y + CELL)).save(folder / f"{i + 1:02d}.png")
    assert cli.main(["build", str(run), "--source", f"walk={folder}"]) == 0
    data = json.loads((run / "run.json").read_text())
    assert len(data["sources"]["walk"]["frames"]) == 8
    assert data["build"]["states"]["walk"]["checks"][0]["status"] == "pass"


def test_repair_kit_and_patch_replace_one_frame_at_the_sheet_scale(tmp_path: Path) -> None:
    run = plan_run(tmp_path)
    src = tmp_path / "walk.png"
    sheet(drop=5).save(src)
    assert cli.main(["build", str(run), "--source", f"walk={src}"]) == 0
    assert cli.main(["repair", str(run), "--state", "walk", "--frame", "6"]) == 0
    kit = run / "repair" / "walk" / "06"
    assert {p.name for p in kit.iterdir()} >= {"frame-05.png", "frame-07.png", "prompt.txt"}

    # The repaired frame comes back from another generation at twice the size.
    full = sheet(transparent=True)
    fix = full.crop((1 * CELL, CELL, 2 * CELL, 2 * CELL))
    fix = fix.resize((CELL * 2, CELL * 2), Image.Resampling.LANCZOS)
    fix.save(tmp_path / "fix.png")
    assert cli.main(["build", str(run), "--patch", f"walk:6={tmp_path / 'fix.png'}"]) == 0
    built = json.loads((run / "run.json").read_text())["build"]["states"]["walk"]
    assert built["cutout"]["patched_frames"] == [6]
    assert next(c for c in built["checks"] if c["id"] == "frames")["status"] == "pass"
    heights = []
    for png in sorted((run / "frames" / "walk").glob("*.png")):
        rows = np.nonzero((np.asarray(Image.open(png).getchannel("A")) >= 16).any(axis=1))[0]
        heights.append(rows.max() - rows.min())
    assert max(heights) / min(heights) < 1.25


def test_one_sheet_with_all_states_is_split_by_row(tmp_path: Path) -> None:
    run = plan_run(tmp_path, ["--state", "idle:4"])
    assert (run / "prompts" / "_all.txt").exists() and (run / "guides" / "_all.png").exists()
    walk, idle = sheet(transparent=True), sheet(frames=4, transparent=True)
    combined = Image.new("RGBA", (8 * CELL, 2 * CELL), (0, 0, 0, 0))
    for i in range(8):
        combined.paste(walk.crop(((i % 4) * CELL, (i // 4) * CELL, (i % 4 + 1) * CELL, (i // 4 + 1) * CELL)), (i * CELL, 0))
    combined.paste(idle, (0, CELL))
    combined.save(tmp_path / "all.png")
    assert cli.main(["build", str(run), "--source", f"all={tmp_path / 'all.png'}"]) == 0
    data = json.loads((run / "run.json").read_text())
    assert data["sources"]["idle"]["grid"] == [4, 1] and data["sources"]["walk"]["from"]["row"] == 1
    for name in ("walk", "idle"):
        assert next(c for c in data["build"]["states"][name]["checks"] if c["id"] == "frames")["status"] == "pass"


def test_missing_frame_fails_and_strict_blocks(tmp_path: Path) -> None:
    run = plan_run(tmp_path)
    src = tmp_path / "walk.png"
    sheet(drop=5).save(src)
    assert cli.main(["build", str(run), "--source", f"walk={src}"]) == 0
    checks = json.loads((run / "run.json").read_text())["build"]["states"]["walk"]["checks"]
    frames_check = next(c for c in checks if c["id"] == "frames")
    assert frames_check["status"] == "fail" and frames_check["frames"] == [6]
    assert cli.main(["check", str(run)]) == 0
    assert cli.main(["check", str(run), "--strict"]) == 1


def test_changed_source_is_rejected(tmp_path: Path) -> None:
    run = plan_run(tmp_path)
    src = tmp_path / "walk.png"
    sheet().save(src)
    cli.main(["build", str(run), "--source", f"walk={src}"])
    sheet(drop=0).save(run / "sources" / "walk.png")
    with pytest.raises(SystemExit, match="changed after ingest"):
        cli.main(["build", str(run)])
    assert cli.main(["check", str(run), "--strict"]) == 1


def test_a_frame_drawn_larger_is_evened_and_a_pose_change_is_not() -> None:
    from spritekit import imaging
    disc = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    ImageDraw.Draw(disc).ellipse([20, 20, 180, 180], fill=(200, 80, 60, 255))
    wide = Image.new("RGBA", (300, 200), (0, 0, 0, 0))  # same disc plus a raised arm: more area, same thickest part
    wide.paste(disc, (0, 0))
    ImageDraw.Draw(wide).rectangle([170, 90, 290, 110], fill=(200, 80, 60, 255))
    big = disc.resize((220, 220), Image.Resampling.LANCZOS)
    frames = [imaging.Frame(i, c, (0, 0, *c.size), (0, 0, *c.size), False, 0) for i, c in enumerate([disc, disc, wide, big, disc])]
    factors = imaging.even_sizes(frames)
    assert factors[2] == 1.0 and abs(factors[3] - 1 / 1.1) < 0.02
    assert abs(imaging.size_signals(frames[3].crop)[0] / imaging.size_signals(disc)[0] - 1) < 0.02
