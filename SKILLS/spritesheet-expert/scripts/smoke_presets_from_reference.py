#!/usr/bin/env python3
"""Smoke every preset using one reference sprite sheet as synthetic row art."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps


CHROMA = "#00FF00"
CHROMA_RGB = (0, 255, 0, 255)


def run(script: str, *args: str) -> None:
    scripts = Path(__file__).resolve().parent
    subprocess.check_call([sys.executable, str(scripts / script), *args])


def parse_grid(value: str) -> tuple[int, int]:
    left, right = value.lower().split("x", 1)
    return int(left), int(right)


def nonwhite_bbox(image: Image.Image) -> tuple[int, int, int, int] | None:
    rgba = image.convert("RGBA")
    pixels = rgba.load()
    xs: list[int] = []
    ys: list[int] = []
    for y in range(rgba.height):
        for x in range(rgba.width):
            r, g, b, a = pixels[x, y]
            if a > 0 and not (r > 245 and g > 245 and b > 245):
                xs.append(x)
                ys.append(y)
    if not xs:
        return None
    return min(xs), min(ys), max(xs) + 1, max(ys) + 1


def crop_reference_frames(path: Path, grid: tuple[int, int]) -> list[Image.Image]:
    source = Image.open(path).convert("RGBA")
    cols, rows = grid
    cell_w = source.width / cols
    cell_h = source.height / rows
    frames: list[Image.Image] = []
    for row in range(rows):
        for col in range(cols):
            crop = source.crop((round(col * cell_w), round(row * cell_h), round((col + 1) * cell_w), round((row + 1) * cell_h)))
            bbox = nonwhite_bbox(crop)
            if not bbox:
                continue
            sprite = crop.crop(bbox).convert("RGBA")
            pixels = sprite.load()
            for y in range(sprite.height):
                for x in range(sprite.width):
                    r, g, b, a = pixels[x, y]
                    if r > 245 and g > 245 and b > 245:
                        pixels[x, y] = (r, g, b, 0)
            frames.append(sprite)
    if not frames:
        raise SystemExit(f"no sprite frames found in {path}")
    return frames


def paste_fit(canvas: Image.Image, sprite: Image.Image, slot: int, cell: dict[str, Any], flip: bool) -> None:
    cell_w = int(cell["width"])
    cell_h = int(cell["height"])
    margin_x = int(cell.get("safe_margin_x", cell.get("safe_margin", max(4, cell_w // 12))))
    margin_y = int(cell.get("safe_margin_y", cell.get("safe_margin", max(4, cell_h // 12))))
    src = ImageOps.mirror(sprite) if flip else sprite
    scale = min((cell_w - 2 * margin_x) / src.width, (cell_h - 2 * margin_y) / src.height, 1.0)
    size = (max(1, round(src.width * scale)), max(1, round(src.height * scale)))
    resized = src.resize(size, Image.Resampling.LANCZOS)
    x = slot * cell_w + (cell_w - resized.width) // 2
    y = cell_h - margin_y - resized.height
    canvas.alpha_composite(resized, (x, y))


def write_raw_rows(run_dir: Path, frames: list[Image.Image]) -> None:
    request = json.loads((run_dir / "sprite-request.json").read_text(encoding="utf-8"))
    cell = request["cell"]
    cell_w = int(cell["width"])
    cell_h = int(cell["height"])
    raw_dir = run_dir / "raw"
    raw_dir.mkdir(exist_ok=True)
    for state_index, (state, entry) in enumerate(request["states"].items()):
        count = int(entry["frames"])
        strip = Image.new("RGBA", (count * cell_w, cell_h), CHROMA_RGB)
        flip = "left" in state or state.endswith("-sw") or state.endswith("-nw")
        for index in range(count):
            paste_fit(strip, frames[(state_index + index) % len(frames)], index, cell, flip)
        strip.save(raw_dir / f"{state}.png")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--source-grid", default="4x2")
    parser.add_argument("--preset", action="append", help="repeat to limit presets")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    reference = args.reference.expanduser().resolve()
    out_dir = args.out_dir.expanduser().resolve()
    if out_dir.exists() and args.force:
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    presets_path = Path(__file__).parents[1] / "references" / "presets.json"
    presets = json.loads(presets_path.read_text(encoding="utf-8"))["presets"]
    selected = args.preset or list(presets)
    frames = crop_reference_frames(reference, parse_grid(args.source_grid))

    summary: dict[str, Any] = {"ok": True, "reference": str(reference), "out_dir": str(out_dir), "presets": {}}
    for preset in selected:
        run_dir = out_dir / preset
        run_dir.mkdir(parents=True, exist_ok=True)
        request_path = run_dir / "request.from-preset.json"
        preset_args = [preset, "--out", str(request_path)]
        if preset in {"custom-atlas", "custom-asset-atlas"}:
            preset_args += [
                "--states-json",
                json.dumps({
                    "idle": {"frames": 4, "fps": 4, "loop": True, "action": "reference creature idle"},
                    "sniff": {"frames": 4, "fps": 6, "loop": False, "action": "reference creature nose sniff"},
                    "belly-bounce": {"frames": 5, "fps": 6, "loop": True, "action": "reference creature belly bounce"},
                }),
            ]
        try:
            run("preset_to_request.py", *preset_args)
            run(
                "prepare_sprite_run.py",
                "--out-dir", str(run_dir),
                "--character-id", preset,
                "--base-image", str(reference),
                "--request", str(request_path),
                "--chroma-key", CHROMA,
                "--force",
            )
            write_raw_rows(run_dir, frames)
            run("extract_sprite_row_frames.py", "--run-dir", str(run_dir))
            run("compose_sprite_atlas.py", "--run-dir", str(run_dir), "--min-used-pixels", "80")
            run("preview_animation.py", "--run-dir", str(run_dir))
            manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
            summary["presets"][preset] = {
                "ok": True,
                "states": list(manifest["animation"]["rows"]),
                "atlas": str(run_dir / "sprite-sheet-alpha.png"),
                "manifest": str(run_dir / "manifest.json"),
                "qa": str(run_dir / "qa"),
                "sheet": {
                    "width": manifest["frame_layout"]["sheetWidth"],
                    "height": manifest["frame_layout"]["sheetHeight"],
                    "cell_width": manifest["frame_layout"]["cellWidth"],
                    "cell_height": manifest["frame_layout"]["cellHeight"],
                },
            }
        except Exception as exc:
            summary["ok"] = False
            summary["presets"][preset] = {"ok": False, "error": str(exc), "run_dir": str(run_dir)}

    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
