"""`plan`: write run.json, one generation prompt and one layout guide per state."""

from __future__ import annotations

import json
import math
import shutil
from pathlib import Path

from PIL import Image, ImageDraw

from . import SCHEMA, motions, poses, runfile

GUIDE_CELL = 256
RIGID = ("Rigid proportions: the head, torso, hands and feet keep exactly the same size and shape in every frame, and limbs "
         "keep the same length and thickness; only the joints rotate. Nothing stretches, melts or swells between frames.")


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


# How a slot set is placed in its cells: (ground mode, align_x, what every cell must show).
FITS = {
    "ground": ("ground", "feet", "the same character at the same scale, full body, feet on the cell's ground line"),
    "center": ("center", "center", "the same element at the same size and position; only its state changes"),
    "fill": ("fill", "center", "one separate object, centered and filling most of the cell, all in one style, light and palette"),
    "nine": ("nine", "center", "one panel with distinct corners and border and a plain, even middle, so it can stretch as a nine-slice"),
}


def parse_set(text: str) -> dict:
    """`icons:fill=sword,shield,potion` or `gestures:ground=wave,point`; the fit defaults to center."""
    head, sep, body = text.partition("=")
    name, _, fit = head.partition(":")
    fit = fit or "center"
    slots = [s.strip() for s in body.split(",") if s.strip()]
    if not sep or not name or not slots or fit not in FITS:
        raise SystemExit(f"set {text!r} must look like name[:{'|'.join(FITS)}]=slot,slot,...")
    if len(set(slots)) != len(slots):
        raise SystemExit(f"slot names in set {name!r} must be unique")
    cols, rows = grid_for(len(slots))
    return {
        "name": name, "frames": len(slots), "fps": 1, "motion": "slots", "loop": False,
        "ground": FITS[fit][0], "align_x": FITS[fit][1], "grid": [cols, rows],
        "phases": [{"label": s, "pose": s.replace("-", " "), "hold": 1.0} for s in slots],
    }


def slots_prompt(run: dict, st: dict) -> str:
    cols, rows = st["grid"]
    refs = []
    if run.get("anchor"):
        refs.append("Image 1 is the style and identity anchor: copy its design, materials, colors and rendering exactly.")
    refs.append(f"Image {len(refs) + 1} is a layout guide: the {cols}x{rows} cell grid with each cell's name. "
                "Do not draw the guide, the names or the grid.")
    lines = [
        f"Sprite sheet of {run['subject']}: a set of {st['frames']} {st['name']} in a {cols} columns x {rows} rows grid "
        "of equal cells, read left to right, top to bottom.",
        f"Style: {run['style']}." if run.get("style") else "",
        f"Camera: {run['view']}." if run.get("view") else "",
        run.get("notes", ""),
        f"Every cell shows {FITS[st['ground']][2]}, with empty margin, never touching the cell edges.",
        RIGID if st["ground"] == "ground" else "",
        "Consistency: one light source from the same direction and intensity in every cell; one palette and one rendering style.",
        "Cell by cell:",
        *[f"{i + 1}. {p['pose']}." for i, p in enumerate(st["phases"])],
        *refs,
        "Background: native transparent alpha. If transparency is impossible, use one flat uniform #808080 gray with no gradient, texture or shadow.",
        "No text, numbers, labels, grid lines, borders or ground shadows.",
    ]
    return "\n".join(line for line in lines if line)


def atlas_prompt(run: dict, st: dict) -> str:
    """Loose items with wide gaps: build separates them by shape, so no grid is asked for."""
    lines = [
        f"Sprite sheet of {run['subject']}: {st['frames']} separate {st['name']}, loosely arranged in a few rows on one canvas "
        "with wide empty space around every object, none touching or overlapping another. No grid, no cells.",
        f"Style: {run['style']}." if run.get("style") else "",
        f"Camera: {run['view']}." if run.get("view") else "",
        run.get("notes", ""),
        "Objects, in reading order:",
        *[f"{i + 1}. {p['pose']}." for i, p in enumerate(st["phases"])],
        "Every object complete and whole, at its natural size relative to the others, in one style, light and palette.",
        "Image 1 is the style anchor: copy its materials, colors and rendering." if run.get("anchor") else "",
        "Background: native transparent alpha. If transparency is impossible, use one flat uniform #808080 gray with no gradient, texture or shadow.",
        "No text, numbers, labels, borders or ground shadows.",
    ]
    return "\n".join(line for line in lines if line)


def prompt_text(run: dict, st: dict) -> str:
    if st["motion"] == "slots":
        return slots_prompt(run, st)
    if st["motion"] == "atlas":
        return atlas_prompt(run, st)
    cols, rows = st["grid"]
    spec = motions.motion_spec(st["motion"])
    refs = []
    if run.get("anchor"):
        refs.append("Image 1 is the identity anchor: copy the character design exactly (face, proportions, outfit, colors, line weight).")
    if st.get("pose_guides"):
        refs.append(f"Image {len(refs) + 1} is the layout and pose guide: a {cols}x{rows} grid with one mannequin per cell "
                    "showing the exact pose, size and ground line for that frame (dark limbs are the far side). Match each "
                    "cell's pose. Do not draw the mannequins, the grid or the numbers.")
    else:
        refs.append(f"Image {len(refs) + 1} is a layout guide: it shows the {cols}x{rows} cell grid, the ground line and "
                    "the frame order. Do not draw the guide itself.")
    lines = [
        f"Sprite sheet of {run['subject']}.",
        f"Style: {run['style']}." if run.get("style") else "",
        f"Camera: {run['view']}." if run.get("view") else "",
        f"Exactly {st['frames']} frames of one {spec['label']} ({st['name']}), in a {cols} columns x {rows} rows grid of equal cells, read left to right, top to bottom.",
        "Every frame shows the same character at the same scale, from the same camera, centered in its own cell with empty margin, never touching the cell edges.",
        "Consistency: one light source from the same direction and the same intensity in every frame; identical colors, "
        "materials and proportions in every frame. Motion: smooth and continuous, each frame a small natural step from "
        "the previous one, with weight shifting through the hips and follow-through in the arms.",
        RIGID,
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


def combined_prompt(run: dict) -> str:
    """One sheet with every state or set of the run, one row each: one light, one palette for all."""
    cols = run["combined"]["cols"]
    states = run["states"]
    slots = run["lane"] == "slots"
    rows = []
    for i, st in enumerate(states):
        if st["motion"] == "slots":
            rows.append(f"Row {i + 1}: {st['name']}, each cell {FITS[st['ground']][2]}: "
                        + "; ".join(f"{k + 1}. {p['pose']}" for k, p in enumerate(st["phases"])) + ".")
        else:
            rows.append(f"Row {i + 1}: {st['name']} ({motions.motion_spec(st['motion'])['label']}, {st['frames']} frames): "
                        + "; ".join(f"{k + 1}. {p['label']}: {p['pose']}" for k, p in enumerate(st["phases"])) + ".")
    refs = []
    if run.get("anchor"):
        refs.append("Image 1 is the identity anchor: copy the design exactly (shapes, proportions, colors, materials, rendering).")
    if slots:
        refs.append(f"Image {len(refs) + 1} is the layout guide: {cols} columns x {len(states)} rows with each cell's name; "
                    "crossed cells stay empty. Do not draw the grid, the crosses or the names.")
    else:
        refs.append(f"Image {len(refs) + 1} is the layout and pose guide: {cols} columns x {len(states)} rows, one row per "
                    "animation, one mannequin per cell showing the exact pose, size and ground line (dark limbs are the far "
                    "side); crossed cells stay empty. Do not draw the mannequins, the grid, the crosses or the labels.")
    lines = [
        f"Sprite sheet of {run['subject']} with {len(states)} {'sets' if slots else 'animations'}, one per row, read left to right.",
        f"Style: {run['style']}." if run.get("style") else "",
        f"Camera: {run['view']}." if run.get("view") else "",
        run.get("notes", ""),
        *rows,
        "Every cell is centered in its cell with empty margin, never touching the cell edges." if slots else
        "Every cell shows the same character at the same scale, centered in its cell with empty margin, feet on the cell's ground line.",
        "" if slots else RIGID,
        "Consistency: one light source from the same direction and the same intensity in every cell of every row; one "
        "palette, one material and one rendering style everywhere." + ("" if slots else " Motion: smooth and continuous "
        "within each row, each frame a small natural step from the previous one."),
        *refs,
        "Background: native transparent alpha. If transparency is impossible, use one flat uniform #808080 gray.",
        "No text, numbers, labels, grid lines, borders or ground shadows.",
    ]
    return "\n".join(line for line in lines if line)


def draw_combined_guide(run_dir: Path, run: dict) -> Image.Image:
    cols, c = run["combined"]["cols"], GUIDE_CELL
    states = run["states"]
    img = Image.new("RGB", (cols * c, len(states) * c), (236, 236, 232))
    draw = ImageDraw.Draw(img)
    for r, st in enumerate(states):
        for k in range(cols):
            x, y = k * c, r * c
            if k < st["frames"] and st.get("pose_guides"):
                pose = Image.open(run_dir / "poses" / st["name"] / f"{k + 1:02d}.png").convert("RGB")
                img.paste(pose.resize((c, c), Image.Resampling.LANCZOS), (x, y))
            draw.rectangle([x, y, x + c - 1, y + c - 1], outline=(150, 150, 146), width=2)
            if k >= st["frames"]:
                draw.line([x, y, x + c, y + c], fill=(200, 200, 196), width=2)
                continue
            mark_cell(draw, x, y, c, st, run["baseline"], f"{st['name']} {k + 1} {st['phases'][k]['label']}")
    return img


def mark_cell(draw: ImageDraw.ImageDraw, x: int, y: int, c: int, st: dict, baseline: float, label: str) -> None:
    """Ground line for grounded cells, a margin box for centered ones, and the cell's label."""
    if st["ground"] in ("ground", "keep"):
        gy = y + round(c * baseline)
        draw.line([x + 8, gy, x + c - 8, gy], fill=(220, 90, 60), width=3)
        draw.line([x + c // 2, y + 8, x + c // 2, gy], fill=(170, 170, 230), width=1)
    else:
        m = round(c * 0.08)
        draw.rectangle([x + m, y + m, x + c - m, y + c - m], outline=(170, 170, 230), width=1)
    draw.text((x + 8, y + 6), label, fill=(60, 60, 60))


def frame_prompt(run: dict, st: dict, k: int, has_pose: bool) -> str:
    """Prompt for frame k (1-based) of the chained route.

    Frame 1 comes from the anchor. Every later frame comes from frame 1 itself, not
    from the previous frame, so shapes and colors never drift step by step.
    """
    phase = st["phases"][k - 1]
    if k == 1:
        refs = ["Image 1 is the identity anchor: copy the character's face, proportions, outfit, colors and rendering exactly."]
    else:
        refs = ["Image 1 is frame 1 of this same animation: it is the master reference. Keep every body part exactly "
                "the same shape, size, color, material and rendering as in Image 1 (same head size, same limb length "
                "and thickness, same hand and foot size, same framing) and change ONLY the pose."]
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
        st["phases"][k - 1]["pose_height"] = poses.pose_height(pose)
        image = poses.draw_openpose(pose, mirror) if run.get("pose_guide") == "openpose" else poses.draw(pose, mirror)
        image.save(folder / f"{k:02d}.png")
        (folder / f"{k:02d}.openpose.json").write_text(json.dumps(poses.openpose_json(pose, mirror)) + "\n", encoding="utf-8")
    return True


def draw_guide(st: dict, baseline: float, pose_dir: Path | None = None) -> Image.Image:
    """Grid, ground line and frame order; with pose guides, each cell also shows its mannequin."""
    cols, rows = st["grid"]
    c = GUIDE_CELL
    img = Image.new("RGB", (cols * c, rows * c), (236, 236, 232))
    if pose_dir is not None:
        for i in range(st["frames"]):
            pose = Image.open(pose_dir / f"{i + 1:02d}.png").convert("RGB").resize((c, c), Image.Resampling.LANCZOS)
            img.paste(pose, ((i % cols) * c, (i // cols) * c))
    draw = ImageDraw.Draw(img)
    for i in range(cols * rows):
        x, y = (i % cols) * c, (i // cols) * c
        draw.rectangle([x, y, x + c - 1, y + c - 1], outline=(150, 150, 146), width=2)
        if i >= st["frames"]:
            draw.line([x, y, x + c, y + c], fill=(200, 200, 196), width=2)
            continue
        mark_cell(draw, x, y, c, st, baseline, f"{i + 1} {st['phases'][i]['label']}")
    return img


def plan(args) -> int:
    run_dir = Path(args.out)
    if (run_dir / runfile.RUN_FILE).exists() and not args.force:
        raise SystemExit(f"{run_dir / runfile.RUN_FILE} exists; pass --force to replace the plan.")
    if args.lane in ("slots", "atlas"):
        if not args.set or args.state:
            raise SystemExit(f"the {args.lane} lane takes --set name[:fit]=slot,slot,... (not --state)")
        states = [parse_set(s) for s in args.set]
        if args.lane == "atlas":  # loose items: separated by shape, packed at their own size
            for st in states:
                st.update(motion="atlas", ground="native", align_x="center", grid=[st["frames"], 1])
    else:
        if not args.state or args.set:
            raise SystemExit("the animation lane takes --state name:frames[:motion[:fps]] (not --set)")
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
        st["pose_guides"] = write_pose_guides(run_dir, run, st)
        (run_dir / "prompts" / f"{st['name']}.txt").write_text(prompt_text(run, st) + "\n", encoding="utf-8")
        pose_dir = run_dir / "poses" / st["name"] if st["pose_guides"] else None
        if st["motion"] != "atlas":
            draw_guide(st, run["baseline"], pose_dir).save(run_dir / "guides" / f"{st['name']}.png")
        if st["motion"] in ("slots", "atlas"):
            continue
        frames_dir = run_dir / "prompts" / st["name"]
        frames_dir.mkdir(exist_ok=True)
        for k in range(1, st["frames"] + 1):
            (frames_dir / f"{k:02d}.txt").write_text(frame_prompt(run, st, k, st["pose_guides"]) + "\n", encoding="utf-8")
    if len(states) > 1 and args.lane != "atlas":
        run["combined"] = {"cols": max(s["frames"] for s in states), "rows": [s["name"] for s in states]}
        (run_dir / "prompts" / "_all.txt").write_text(combined_prompt(run) + "\n", encoding="utf-8")
        draw_combined_guide(run_dir, run).save(run_dir / "guides" / "_all.png")
    runfile.save(run_dir, run)
    anchor = [run["anchor"]["file"]] if run["anchor"] else []
    print(f"Planned {len(states)} {'state' if args.lane == 'animation' else 'set'}(s) in {run_dir}")
    if run.get("combined"):
        print(f"  everything in one sheet (best color and light match): prompts/_all.txt with "
              f"{' + '.join(anchor + ['guides/_all.png'])}")
    for st in states:
        name = st["name"]
        kind = {"slots": f"{st['frames']} slots, fit {st['ground']}", "atlas": f"{st['frames']} loose items"}.get(
            st["motion"], f"{st['frames']} frames, {st['motion']}")
        guide = [] if st["motion"] == "atlas" else [f"guides/{name}.png"]
        alone = "  or alone (more pixels per frame)" if run.get("combined") else ""
        print(f"{alone or ' '} {name} ({kind}): prompts/{name}.txt" + (f" with {' + '.join(anchor + guide)}" if anchor or guide else ""))
    print(f"Then: sprite.py build {run_dir} --source {'all' if run.get('combined') else '<name>'}=<sheet>; "
          "redraw single bad cells with sprite.py repair")
    return 0
