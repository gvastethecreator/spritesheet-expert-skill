"""`build`: ingest sources, cut out, split frames, fit, pack the atlas, write the review."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
from PIL import Image

from . import checks, imaging, motions, review, runfile


IMAGE_SUFFIXES = {".png", ".webp", ".jpg", ".jpeg"}


def sheet_from_frames(paths: list[Path], cols: int, rows: int) -> Image.Image:
    """Lay separate frame images into the state's grid, each centered in an equal cell.

    Layout only: no pixel is changed. Cells take the largest frame's size.
    """
    images = [Image.open(p).convert("RGBA") for p in paths]
    cw, ch = max(i.width for i in images), max(i.height for i in images)
    sheet = Image.new("RGBA", (cols * cw, rows * ch), (0, 0, 0, 0))
    for k, img in enumerate(images):
        x, y = (k % cols) * cw + (cw - img.width) // 2, (k // cols) * ch + (ch - img.height)
        sheet.paste(img, (x, y))
    return sheet


def ingest(run_dir: Path, run: dict, pairs: list[str], provider: str) -> None:
    """`state=sheet.png` copies one sheet; `state=folder/` lays its frame images (sorted by name) into the grid."""
    for pair in pairs:
        if "=" not in pair:
            raise SystemExit(f"--source {pair!r} must look like state=sheet.png or state=frames-folder/")
        name, path = pair.split("=", 1)
        if name == "all":
            ingest_combined(run_dir, run, Path(path), provider)
            continue
        st = runfile.state(run, name)
        src = Path(path)
        (run_dir / "sources").mkdir(exist_ok=True)
        frames = []
        if src.is_dir():
            frames = sorted(p for p in src.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
            if len(frames) != st["frames"]:
                raise SystemExit(f"{src} has {len(frames)} images; state {name!r} needs {st['frames']}")
            dst = run_dir / "sources" / f"{name}.png"
            sheet_from_frames(frames, *st["grid"]).save(dst)
        elif src.is_file():
            dst = run_dir / "sources" / f"{name}{src.suffix.lower()}"
            if src.resolve() != dst.resolve():
                shutil.copyfile(src, dst)
        else:
            raise SystemExit(f"source not found: {src}")
        run["sources"][name] = {
            "file": dst.relative_to(run_dir).as_posix(), "sha256": runfile.sha256(dst),
            "origin": str(src), "provider": provider, "ingested": runfile.now(),
            **({"frames": [{"file": p.name, "sha256": runfile.sha256(p)} for p in frames]} if frames else {}),
        }


def ingest_combined(run_dir: Path, run: dict, src: Path, provider: str) -> None:
    """Split a one-sheet-for-all-states image into one row band per state (layout only)."""
    layout = run.get("combined")
    if not layout:
        raise SystemExit("this run has no combined layout; plan it with more than one state")
    if not src.is_file():
        raise SystemExit(f"source not found: {src}")
    (run_dir / "sources").mkdir(exist_ok=True)
    whole = run_dir / "sources" / f"_all{src.suffix.lower()}"
    if src.resolve() != whole.resolve():
        shutil.copyfile(src, whole)
    sheet = Image.open(whole)
    names = layout["rows"]
    cuts = imaging.row_bands(imaging.cutout(sheet, "auto")[0], len(names))
    for r, name in enumerate(names):
        frames = runfile.state(run, name)["frames"]
        dst = run_dir / "sources" / f"{name}.png"
        sheet.crop((0, cuts[r], sheet.width, cuts[r + 1])).save(dst)
        run["sources"][name] = {
            "file": dst.relative_to(run_dir).as_posix(), "sha256": runfile.sha256(dst), "grid": [frames, 1],
            "from": {"file": whole.relative_to(run_dir).as_posix(), "sha256": runfile.sha256(whole), "row": r + 1},
            "origin": str(src), "provider": provider, "ingested": runfile.now(),
        }


def ingest_patches(run_dir: Path, run: dict, pairs: list[str], provider: str) -> None:
    """`state:frame=image` stores a repaired frame; it replaces that frame of the sheet at build time."""
    for pair in pairs:
        target, _, path = pair.partition("=")
        name, _, frame = target.partition(":")
        st = runfile.state(run, name)
        if not frame.isdigit() or not 1 <= int(frame) <= st["frames"] or not Path(path).is_file():
            raise SystemExit(f"--patch {pair!r} must look like state:frame=image.png with a frame from 1 to {st['frames']}")
        dst = run_dir / "patches" / f"{name}-{int(frame):02d}{Path(path).suffix.lower()}"
        dst.parent.mkdir(exist_ok=True)
        shutil.copyfile(path, dst)
        run.setdefault("patches", {}).setdefault(name, {})[frame.lstrip("0")] = {
            "file": dst.relative_to(run_dir).as_posix(), "sha256": runfile.sha256(dst),
            "origin": str(path), "provider": provider, "ingested": runfile.now(),
        }


def apply_patches(run_dir: Path, run: dict, st: dict, frames: list, cutout_mode: str) -> list[int]:
    """Swap patched frames in, scaled to the body size of the frames around them."""
    patched = []
    for frame, entry in sorted(run.get("patches", {}).get(st["name"], {}).items(), key=lambda kv: int(kv[0])):
        path = run_dir / entry["file"]
        if runfile.sha256(path) != entry["sha256"]:
            raise SystemExit(f"{entry['file']} changed after ingest; patch it again")
        cut, _ = imaging.cutout(Image.open(path), cutout_mode)
        piece = imaging.split_frames(cut, 1, 1, 1)[0]
        if piece is None:
            raise SystemExit(f"{entry['file']} has no visible subject")
        k = int(frame) - 1
        piece.index, piece.cell_box = k, frames[k].cell_box if frames[k] else piece.cell_box
        if st["motion"] == "atlas":  # a lone redraw has its own scale: give it the replaced item's longest side
            sides = [max(f.crop.size) for f in frames if f is not None]
            want = max(frames[k].crop.size) if frames[k] else float(np.median(sides)) if sides else max(piece.crop.size)
            f = want / max(piece.crop.size)
            piece.crop = piece.crop.resize((max(1, round(piece.crop.width * f)), max(1, round(piece.crop.height * f))),
                                           Image.Resampling.LANCZOS)
        frames[k] = piece
        patched.append(k)
    others = [f for i, f in enumerate(frames) if f is not None and i not in patched]
    if others and st["motion"] != "atlas":
        # Match the row on both pose-tolerant size measures (area and thickest part), not on pose height.
        typical = np.median([imaging.size_signals(f.crop) for f in others], axis=0)
        for k in patched:
            area, radius = imaging.size_signals(frames[k].crop)
            factor = float(np.sqrt(typical[0] / max(area, 1) * typical[1] / max(radius, 1)))
            size = (max(1, round(frames[k].crop.width * factor)), max(1, round(frames[k].crop.height * factor)))
            frames[k].crop = frames[k].crop.resize(size, Image.Resampling.LANCZOS)
    return [k + 1 for k in patched]


def repair(args) -> int:
    """Write an in-between repair kit for each frame: its built neighbors, its pose guide and a prompt."""
    run_dir = Path(args.run)
    run = runfile.load(run_dir)
    st = runfile.state(run, args.state)
    if not run.get("build") or st["name"] not in run["build"]["states"]:
        raise SystemExit(f"build state {st['name']!r} first")
    n = st["frames"]
    for k in args.frame:
        if not 1 <= k <= n:
            raise SystemExit(f"frame {k} is out of range 1..{n}")
        kit = run_dir / "repair" / st["name"] / f"{k:02d}"
        kit.mkdir(parents=True, exist_ok=True)
        # Nearest usable frame on each side: skip frames being repaired too, and empty cells.
        def usable(j: int) -> bool:
            path = run_dir / "frames" / st["name"] / f"{j:02d}.png"
            return j not in args.frame and path.exists() and Image.open(path).getchannel("A").getbbox() is not None
        neighbors = []
        for step in (-1, 1):
            j = k
            for _ in range(n - 1):
                j += step
                if st["loop"]:
                    j = (j - 1) % n + 1
                elif not 1 <= j <= n:
                    break
                if usable(j):
                    if j != k and j not in neighbors:
                        neighbors.append(j)
                    break
        neighbors.sort()
        refs = []
        for j in neighbors:
            shutil.copyfile(run_dir / "frames" / st["name"] / f"{j:02d}.png", kit / f"frame-{j:02d}.png")
            refs.append(f"frame-{j:02d}.png")
        pose = run_dir / "poses" / st["name"] / f"{k:02d}.png"
        if pose.exists():
            shutil.copyfile(pose, kit / "pose.png")
        phase = st["phases"][k - 1]
        if st["motion"] == "slots":
            lines = [f"Redraw the '{phase['label']}' cell of the {st['name']} set of {run['subject']}: {phase['pose']}."]
            lines += [f"Image {i + 1} is the '{st['phases'][j - 1]['label']}' cell of the same set." for i, j in enumerate(neighbors)]
            lines.append("Match those cells exactly: same style, materials, palette, lighting direction and intensity, "
                         "rendering, camera and scale.")
        else:
            lines = [f"Redraw frame {k} of {n} ('{phase['label']}') of one {motions.motion_spec(st['motion'])['label']} by {run['subject']}."]
            lines += [f"Image {i + 1} is frame {j} of the same animation." for i, j in enumerate(neighbors)]
            lines.append("Keep the character exactly as in those frames: same shapes, proportions, size, colors, materials, "
                         "lighting direction and intensity, rendering and camera. Draw the natural in-between pose: "
                         f"{phase['pose']}.")
        if pose.exists():
            lines.append(f"Image {len(neighbors) + 1} is the pose guide for this frame: match its pose. Do not draw the guide.")
        grounded = st["ground"] in ("ground", "keep")
        lines.append(("Full body, centered, with empty margin, feet on the same ground line." if grounded
                      else "Centered, with empty margin.") + " Native transparent background. No text.")
        (kit / "prompt.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"{kit}: attach {' + '.join(refs + (['pose.png'] if pose.exists() else []))}, prompt prompt.txt")
    print(f"Then: sprite.py build {run_dir} --patch {st['name']}:<frame>=<image>")
    return 0


def reference_image(run_dir: Path, run: dict) -> Image.Image | None:
    if not run.get("anchor"):
        return None
    img, _ = imaging.cutout(Image.open(run_dir / run["anchor"]["file"]), "auto")
    box = img.getchannel("A").getbbox()
    return img.crop(box) if box else None


def write_packed_atlas(run_dir: Path, run: dict, placed: dict[str, list[Image.Image | None]]) -> dict:
    """Loose items: tight shelf packing, one rectangle per named item."""
    cw, ch = run["cell"]
    entries = [(name, k, img) for name in placed for k, img in enumerate(placed[name]) if img is not None]
    pos, size = imaging.shelf_pack([img.size for _, _, img in entries])
    atlas = Image.new("RGBA", size, (0, 0, 0, 0))
    meta = {"image": "atlas.png", "cell": [cw, ch], "pivot": [cw // 2, ch // 2], "states": {}}
    for (name, k, img), (x, y) in zip(entries, pos):
        atlas.paste(img, (x, y))
        st = runfile.state(run, name)
        meta["states"].setdefault(name, {"packed": True, "frames": []})["frames"].append(
            {"name": st["phases"][k]["label"], "x": x, "y": y, "w": img.width, "h": img.height})
    atlas.save(run_dir / "atlas.png", optimize=True)
    (run_dir / "atlas.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return meta


def write_atlas(run_dir: Path, run: dict, placed: dict[str, list[Image.Image]]) -> dict:
    if run["lane"] == "atlas":
        return write_packed_atlas(run_dir, run, placed)
    cw, ch = run["cell"]
    names = [s["name"] for s in run["states"] if s["name"] in placed]
    cols = max(len(placed[n]) for n in names)
    atlas = Image.new("RGBA", (cols * cw, len(names) * ch), (0, 0, 0, 0))
    meta = {"image": "atlas.png", "cell": [cw, ch], "pivot": [cw // 2, round(ch * run["baseline"])], "states": {}}
    for row, name in enumerate(names):
        st = runfile.state(run, name)
        frames = []
        for col, img in enumerate(placed[name]):
            atlas.paste(img, (col * cw, row * ch))
            cell = {"x": col * cw, "y": row * ch, "w": cw, "h": ch}
            if st["motion"] != "slots":
                cell["duration_ms"] = durations(st)[col]
            else:
                cell = {"name": st["phases"][col]["label"], **cell}
                if st["ground"] == "nine":
                    cell["nine_slice"] = imaging.nine_slice(img)
            frames.append(cell)
        meta["states"][name] = ({"fit": st["ground"], "frames": frames} if st["motion"] == "slots"
                                else {"fps": st["fps"], "loop": st["loop"], "frames": frames})
    atlas.save(run_dir / "atlas.png", optimize=True)
    (run_dir / "atlas.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return meta


def durations(st: dict) -> list[int]:
    """Milliseconds per frame: one frame at the state's fps, scaled by the phase's hold."""
    return [round(1000 / st["fps"] * p.get("hold", 1.0)) for p in st["phases"]]


def write_preview(run_dir: Path, st: dict, frames: list[Image.Image]) -> str:
    out = run_dir / "previews" / f"{st['name']}.webp"
    out.parent.mkdir(exist_ok=True)
    loop = st["loop"]
    frames[0].save(out, save_all=True, append_images=frames[1:], duration=durations(st),
                   loop=0 if loop else 1, lossless=False, quality=90, method=4)
    return out.relative_to(run_dir).as_posix()


def build(args) -> int:
    run_dir = Path(args.run)
    run = runfile.load(run_dir)
    ingest(run_dir, run, args.source or [], args.provider)
    ingest_patches(run_dir, run, args.patch or [], args.provider)
    pending = [s["name"] for s in run["states"] if s["name"] not in run["sources"]]
    ready = [s for s in run["states"] if s["name"] in run["sources"]]
    if not ready:
        raise SystemExit("no source images yet. Pass --source <state>=<image>.")
    reference = reference_image(run_dir, run)
    cw, ch = run["cell"]
    placed: dict[str, list[Image.Image]] = {}
    report = {"time": runfile.now(), "states": {}, "pending": pending}
    split = {}
    for st in ready:
        source = run["sources"][st["name"]]
        src_path = run_dir / source["file"]
        if runfile.sha256(src_path) != source["sha256"]:
            raise SystemExit(f"{source['file']} changed after ingest; ingest it again with --source")
        cut, info = imaging.cutout(Image.open(src_path), args.cutout)
        (run_dir / "cutout").mkdir(exist_ok=True)
        cut.save(run_dir / "cutout" / f"{st['name']}.png")
        if "from" in source:
            # A combined row rarely spaces its frames on the planned columns: split the drawn span instead.
            box = cut.getchannel("A").point(lambda a: 255 if a >= 128 else 0).getbbox()
            if box:
                cut = cut.crop((max(box[0] - 8, 0), 0, min(box[2] + 8, cut.width), cut.height))  # keep source-edge honest
        if st["motion"] == "atlas":
            items, specks = imaging.separate_items(cut)
            info = {**info, "found": len(items), "specks": specks}
            frames = items[:st["frames"]] + [None] * (st["frames"] - len(items))
        else:
            cols, rows = source.get("grid", st["grid"])
            frames = imaging.split_frames(cut, cols, rows, st["frames"])
        patched = apply_patches(run_dir, run, st, frames, args.cutout)
        if patched:
            info = {**info, "patched_frames": patched}
        heights = [p.get("pose_height") for p in st["phases"]]
        # Only frames drawn one by one get pose-guided sizes; a sheet drawn as one image already shares a scale.
        if st["ground"] == "ground" and "frames" in source and all(heights) and all(frames):
            info = {**info, "size_factors": imaging.match_pose_sizes(frames, heights)}
        elif st["ground"] == "ground" and sum(f is not None for f in frames) > 2:
            info = {**info, "evened": imaging.even_sizes([f for f in frames if f is not None])}
        split[st["name"]] = (frames, [f for f in frames if f is not None], info)
    # One character, one size: every grounded state maps its typical body height to the
    # same output height, so idle and attack sheets drawn at different sizes still match.
    grounded = {s["name"]: split[s["name"]][1] for s in ready if s["ground"] == "ground" and split[s["name"]][1]}
    body_px = None
    if grounded:
        body_px = min(imaging.fit_frames(found, (cw, ch), run["baseline"], runfile.state(run, n)["ground"],
                                         runfile.state(run, n)["align_x"])[1] * imaging.body_height(found)
                      for n, found in grounded.items())
    for st in ready:
        frames, found, info = split[st["name"]]
        target = body_px / imaging.body_height(found) if body_px and st["name"] in grounded else None
        if st["motion"] == "atlas":  # loose items keep their relative sizes; the largest fits one cell
            longest = max((max(f.crop.size) for f in found), default=1)
            scale = min(cw, ch) * 0.88 / longest
            fitted = [f.crop.resize((max(1, round(f.crop.width * scale)), max(1, round(f.crop.height * scale))),
                                    Image.Resampling.LANCZOS) for f in found]
        elif st["ground"] == "fill":  # icons and items: each one fills its cell
            fitted = [imaging.fit_frames([f], (cw, ch), run["baseline"], "center", "center")[0][0] for f in found]
            scale = 0.0
        else:
            ground = "center" if st["ground"] == "nine" else st["ground"]
            fitted, scale = imaging.fit_frames(found, (cw, ch), run["baseline"], ground, st["align_x"],
                                               scale=target) if found else ([], 0.0)
        by_index = {f.index: img for f, img in zip(found, fitted)}
        blank = None if st["motion"] == "atlas" else Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        images = [by_index.get(i, blank) for i in range(st["frames"])]
        frame_dir = run_dir / "frames" / st["name"]
        if frame_dir.exists():
            shutil.rmtree(frame_dir)
        frame_dir.mkdir(parents=True)
        for i, img in enumerate(images):
            if img is not None:
                img.save(frame_dir / f"{i + 1:02d}.png")
        placed[st["name"]] = images
        report["states"][st["name"]] = {
            "cutout": info, "scale": round(scale, 4),
            "preview": write_preview(run_dir, st, images) if st["motion"] not in ("slots", "atlas") else None,
            "checks": checks.run_checks(st, frames, fitted, reference, info),
        }
    rows = {s["name"]: placed[s["name"]] for s in ready if s["motion"] not in ("slots", "atlas")}
    if len(rows) > 1:
        for name, check in checks.state_match(rows).items():
            report["states"][name]["checks"].append(check)
    report["atlas"] = write_atlas(run_dir, run, placed)
    run["build"] = report
    runfile.save(run_dir, run)
    review.write(run_dir, run)
    print_summary(run)
    return 0


def print_summary(run: dict) -> None:
    build = run["build"]
    for name, st in build["states"].items():
        counts = {k: sum(1 for c in st["checks"] if c["status"] == k) for k in ("pass", "warn", "fail")}
        print(f"{name}: {st['cutout']['method']}, scale {st['scale']}, "
              f"{counts['pass']} pass / {counts['warn']} warn / {counts['fail']} fail")
        for c in st["checks"]:
            if c["status"] != "pass":
                print(f"  {c['status'].upper():4} {c['id']}: {c['detail']}")
    if build["pending"]:
        print(f"waiting for sources: {', '.join(build['pending'])}")
    print("outputs: atlas.png, atlas.json, frames/, previews/, review.html")
