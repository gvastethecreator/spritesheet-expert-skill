"""`build`: ingest sources, cut out, split frames, fit, pack the atlas, write the review."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from PIL import Image

from . import checks, imaging, review, runfile


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


def reference_image(run_dir: Path, run: dict) -> Image.Image | None:
    if not run.get("anchor"):
        return None
    img, _ = imaging.cutout(Image.open(run_dir / run["anchor"]["file"]), "auto")
    box = img.getchannel("A").getbbox()
    return img.crop(box) if box else None


def write_atlas(run_dir: Path, run: dict, placed: dict[str, list[Image.Image]]) -> dict:
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
            frames.append({"x": col * cw, "y": row * ch, "w": cw, "h": ch, "duration_ms": durations(st)[col]})
        meta["states"][name] = {"fps": st["fps"], "loop": st["loop"], "frames": frames}
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
        cols, rows = st["grid"]
        frames = imaging.split_frames(cut, cols, rows, st["frames"])
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
        fitted, scale = imaging.fit_frames(found, (cw, ch), run["baseline"], st["ground"], st["align_x"],
                                           scale=target) if found else ([], 0.0)
        by_index = {f.index: img for f, img in zip(found, fitted)}
        images = [by_index.get(i, Image.new("RGBA", (cw, ch), (0, 0, 0, 0))) for i in range(st["frames"])]
        frame_dir = run_dir / "frames" / st["name"]
        if frame_dir.exists():
            shutil.rmtree(frame_dir)
        frame_dir.mkdir(parents=True)
        for i, img in enumerate(images):
            img.save(frame_dir / f"{i + 1:02d}.png")
        placed[st["name"]] = images
        report["states"][st["name"]] = {
            "cutout": info, "scale": round(scale, 4),
            "preview": write_preview(run_dir, st, images),
            "checks": checks.run_checks(st, frames, fitted, reference, info),
        }
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
