"""`plan`: write run.json, one generation prompt and one layout guide per state."""

from __future__ import annotations

import json
import math
import shutil
from pathlib import Path

from PIL import Image, ImageDraw

from . import SCHEMA, motions, poses, runfile

GUIDE_CELL = 256


def grid_for(frames: int) -> tuple[int, int]:
    """Compact grid: long strips drift and crop more often than grids."""
    if frames <= 4:
        return frames, 1
    cols = math.ceil(math.sqrt(frames * 2))
    cols = min(cols, frames)
    while frames % cols and cols > 2 and math.ceil(frames / (cols - 1)) <= cols - 1:
        cols -= 1
    return cols, math.ceil(frames / cols)


def parse_state(text: str) -> dict:
    """`walk:8` or `walk:8:walk-quadruped` or `slash:6:attack:12`."""
    parts = text.split(":")
    if len(parts) < 2 or not parts[1].isdigit():
        raise SystemExit(f"state {text!r} must look like name:frames[:motion[:fps]]")
    name, frames = parts[0], int(parts[1])
    motion = parts[2] if len(parts) > 2 and parts[2] else name
    spec = motions.motion_spec(motion)
    fps = int(parts[3]) if len(parts) > 3 else (6 if motion in ("idle",) else 10)
    cols, rows = grid_for(frames)
    return {
        "name": name, "frames": frames, "fps": fps, "motion": motion,
        "loop": spec["loop"], "ground": spec["ground"], "align_x": spec["align_x"],
        "grid": [cols, rows],
        "phases": [{"label": l, "pose": d, "hold": motions.hold(motion, l)} for l, d in motions.phases(motion, frames, name)],
    }


def prompt_text(run: dict, st: dict) -> str:
    cols, rows = st["grid"]
    spec = motions.motion_spec(st["motion"])
    refs = []
    if run.get("anchor"):
        refs.append("Image 1 is the identity anchor: copy the character design exactly (face, proportions, outfit, colors, line weight).")
    refs.append(f"Image {len(refs) + 1} is a layout guide: it shows the {cols}x{rows} cell grid, the ground line and the frame order. Do not draw the guide itself.")
    lines = [
        f"Sprite sheet of {run['subject']}.",
        f"Style: {run['style']}." if run.get("style") else "",
        f"Camera: {run['view']}." if run.get("view") else "",
        f"Exactly {st['frames']} frames of one {spec['label']} ({st['name']}), in a {cols} columns x {rows} rows grid of equal cells, read left to right, top to bottom.",
        "Every frame shows the same character at the same scale, from the same camera, with the same palette, centered in its own cell with empty margin, never touching the cell edges.",
        "Feet rest on the same ground line in every cell." if st["ground"] == "ground" else "Keep one fixed ground line; only airborne frames leave it.",
        "Frame by frame:",
        *[f"{i + 1}. {p['label']}: {p['pose']}." for i, p in enumerate(st["phases"])],
        *refs,
        "Background: native transparent alpha. If transparency is impossible, use one flat uniform #808080 gray with no gradient, texture or shadow.",
        "No text, numbers, labels, grid lines, borders or ground shadows.",
    ]
    if run.get("notes"):
        lines.insert(3, run["notes"])
    return "\n".join(line for line in lines if line)


def frame_prompt(run: dict, st: dict, k: int, has_pose: bool) -> str:
    """Prompt for frame k (1-based) of the chained route: anchor, previous frame, pose guide."""
    phase = st["phases"][k - 1]
    refs = ["Image 1 is the identity anchor: copy the character's face, proportions, outfit, colors and rendering exactly."]
    if k > 1:
        refs.append("Image 2 is the previous animation frame: keep every detail identical to it (textures, equipment, "
                    "lighting, scale, feet position) and change ONLY the body pose. Keep the character exactly the same "
                    "size as in Image 2: same head size, same feet size, same framing.")
    if has_pose:
        kind = ("an OpenPose skeleton (colored limbs on black)" if run.get("pose_guide") == "openpose"
                else "a gray mannequin (dark limbs are the far side, light limbs the near side)")
        refs.append(f"Image {len(refs) + 1} is {kind} showing the exact target pose and the ground line: match its head, "
                    "torso, arm and leg positions. Do not draw the guide itself.")
    lines = [
        f"One animation frame ({k} of {st['frames']}, '{phase['label']}') of one {motions.motion_spec(st['motion'])['label']} "
        f"({st['name']}) by {run['subject']}.",
        f"Style: {run['style']}." if run.get("style") else "",
        f"Camera: {run['view']}." if run.get("view") else "",
        run.get("notes", ""),
        f"Pose: {phase['pose']}.",
        "Full body, centered, with empty margin; feet on the ground line.",
        *refs,
        "Background: native transparent alpha. No text, effects, ground shadow or guide marks.",
    ]
    return "\n".join(line for line in lines if line)


def write_pose_guides(run_dir: Path, run: dict, st: dict) -> bool:
    keyed = poses.frame_poses(st["motion"], st["frames"])
    if keyed is None:
        return False
    mirror = poses.faces_left(run.get("view", ""))
    folder = run_dir / "poses" / st["name"]
    folder.mkdir(parents=True, exist_ok=True)
    for k, pose in enumerate(keyed, 1):
        image = poses.draw_openpose(pose, mirror) if run.get("pose_guide") == "openpose" else poses.draw(pose, mirror)
        image.save(folder / f"{k:02d}.png")
        (folder / f"{k:02d}.openpose.json").write_text(json.dumps(poses.openpose_json(pose, mirror)) + "\n", encoding="utf-8")
    return True


def draw_guide(st: dict, baseline: float) -> Image.Image:
    cols, rows = st["grid"]
    c = GUIDE_CELL
    img = Image.new("RGB", (cols * c, rows * c), (236, 236, 232))
    draw = ImageDraw.Draw(img)
    for i in range(cols * rows):
        x, y = (i % cols) * c, (i // cols) * c
        draw.rectangle([x, y, x + c - 1, y + c - 1], outline=(150, 150, 146), width=2)
        if i >= st["frames"]:
            draw.line([x, y, x + c, y + c], fill=(200, 200, 196), width=2)
            continue
        gy = y + round(c * baseline)
        draw.line([x + 8, gy, x + c - 8, gy], fill=(220, 90, 60), width=3)
        draw.line([x + c // 2, y + 8, x + c // 2, gy], fill=(170, 170, 230), width=1)
        draw.text((x + 8, y + 6), f"{i + 1} {st['phases'][i]['label']}", fill=(60, 60, 60))
    return img


def plan(args) -> int:
    run_dir = Path(args.out)
    if (run_dir / runfile.RUN_FILE).exists() and not args.force:
        raise SystemExit(f"{run_dir / runfile.RUN_FILE} exists; pass --force to replace the plan.")
    states = [parse_state(s) for s in args.state]
    if len({s["name"] for s in states}) != len(states):
        raise SystemExit("state names must be unique")
    run = {
        "schema": SCHEMA, "lane": args.lane, "subject": args.subject, "style": args.style or "",
        "view": args.view or "", "notes": args.notes or "", "pose_guide": args.pose_guide,
        "cell": [args.cell[0], args.cell[1]], "baseline": args.baseline,
        "anchor": None, "states": states, "sources": {}, "build": None,
        "created": runfile.now(),
    }
    run_dir.mkdir(parents=True, exist_ok=True)
    if args.anchor:
        src = Path(args.anchor)
        dst = run_dir / "anchor" / f"anchor{src.suffix.lower()}"
        dst.parent.mkdir(exist_ok=True)
        shutil.copyfile(src, dst)
        run["anchor"] = {"file": dst.relative_to(run_dir).as_posix(), "sha256": runfile.sha256(dst), "origin": str(src)}
    for st in states:
        for sub in ("prompts", "guides"):
            (run_dir / sub).mkdir(exist_ok=True)
        (run_dir / "prompts" / f"{st['name']}.txt").write_text(prompt_text(run, st) + "\n", encoding="utf-8")
        draw_guide(st, run["baseline"]).save(run_dir / "guides" / f"{st['name']}.png")
        st["pose_guides"] = write_pose_guides(run_dir, run, st)
        frames_dir = run_dir / "prompts" / st["name"]
        frames_dir.mkdir(exist_ok=True)
        for k in range(1, st["frames"] + 1):
            (frames_dir / f"{k:02d}.txt").write_text(frame_prompt(run, st, k, st["pose_guides"]) + "\n", encoding="utf-8")
    runfile.save(run_dir, run)
    anchor = [run["anchor"]["file"]] if run["anchor"] else []
    print(f"Planned {len(states)} state(s) in {run_dir}")
    for st in states:
        name = st["name"]
        chained = anchor + ["frame NN-1"] + ([f"poses/{name}/NN.png"] if st["pose_guides"] else [])
        print(f"  {name}: {st['frames']} frames ({st['motion']})")
        print(f"    frame by frame (best): prompts/{name}/NN.txt with {' + '.join(chained)}")
        if not st["pose_guides"]:
            print(f"    no pose guides for motion {st['motion']!r} yet; the prompt describes the pose in words")
        print(f"    one sheet (fast draft): prompts/{name}.txt with {' + '.join(anchor + [f'guides/{name}.png'])}")
    print(f"Then: sprite.py build {run_dir} --source <state>=<frames-folder or sheet>")
    return 0
