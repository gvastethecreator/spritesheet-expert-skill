#!/usr/bin/env python3
"""Smoke every preset using one reference sprite sheet as synthetic row art."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

from spritecore.paths import PathSafetyError, create_run_marker, replace_owned_run


CHROMA = "#00FF00"
CHROMA_RGB = (0, 255, 0, 255)
FULL_CELL_MATTE = (72, 60, 96, 255)


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


def paste_fit(
    canvas: Image.Image,
    sprite: Image.Image,
    slot: int,
    columns: int,
    cell: dict[str, Any],
    flip: bool,
) -> None:
    cell_w = int(cell["width"])
    cell_h = int(cell["height"])
    margin_x = int(cell.get("safe_margin_x", cell.get("safe_margin", max(4, cell_w // 12))))
    margin_y = int(cell.get("safe_margin_y", cell.get("safe_margin", max(4, cell_h // 12))))
    src = ImageOps.mirror(sprite) if flip else sprite
    scale = min((cell_w - 2 * margin_x) / src.width, (cell_h - 2 * margin_y) / src.height, 1.0)
    size = (max(1, round(src.width * scale)), max(1, round(src.height * scale)))
    resized = src.resize(size, Image.Resampling.LANCZOS)
    column = slot % columns
    row = slot // columns
    x = column * cell_w + (cell_w - resized.width) // 2
    y = row * cell_h + cell_h - margin_y - resized.height
    canvas.alpha_composite(resized, (x, y))


def write_raw_rows(run_dir: Path, frames: list[Image.Image]) -> None:
    request = json.loads((run_dir / "sprite-request.json").read_text(encoding="utf-8"))
    cell = request["cell"]
    cell_w = int(cell["width"])
    cell_h = int(cell["height"])
    raw_dir = run_dir / "raw"
    raw_dir.mkdir(exist_ok=True)
    full_cell_assets = request.get("asset_kind") in {"tileset", "texture"}
    for state_index, (state, entry) in enumerate(request["states"].items()):
        count = int(entry["frames"])
        layout = entry.get("raw_layout", {})
        columns = int(layout.get("columns", count))
        rows = int(layout.get("rows", 1))
        if columns < 1 or rows < 1 or columns * rows < count:
            raise SystemExit(
                f"{state}: invalid raw_layout {columns}x{rows} for {count} frames"
            )
        strip = Image.new(
            "RGBA", (columns * cell_w, rows * cell_h), CHROMA_RGB
        )
        flip = "left" in state or state.endswith("-sw") or state.endswith("-nw")
        for index in range(count):
            if full_cell_assets:
                column = index % columns
                row = index // columns
                strip.paste(
                    FULL_CELL_MATTE,
                    (
                        column * cell_w,
                        row * cell_h,
                        (column + 1) * cell_w,
                        (row + 1) * cell_h,
                    ),
                )
            paste_fit(
                strip,
                frames[(state_index + index) % len(frames)],
                index,
                columns,
                cell,
                flip,
            )
        strip.save(raw_dir / f"{state}.png")


def execute_smoke(reference: Path, out_dir: Path, selected: list[str], frames: list[Image.Image]) -> int:
    summary: dict[str, Any] = {"ok": True, "reference": str(reference), "out_dir": str(out_dir), "presets": {}}
    for preset in selected:
        run_dir = out_dir / preset
        run_dir.mkdir(parents=True, exist_ok=True)
        try:
            create_run_marker(run_dir, run_id=preset)
        except PathSafetyError as exc:
            raise SystemExit(str(exc)) from exc
        request_path = run_dir / "request.from-preset.json"
        preset_args = [preset, "--out", str(request_path)]
        if preset == "custom-atlas":
            preset_args += [
                "--states-json",
                json.dumps({
                    "idle": {"frames": 4, "fps": 4, "loop": True, "action": "reference creature idle"},
                    "sniff": {"frames": 4, "fps": 6, "loop": False, "action": "reference creature nose sniff"},
                    "belly-bounce": {"frames": 5, "fps": 6, "loop": True, "action": "reference creature belly bounce"},
                }),
            ]
        elif preset == "custom-asset-atlas":
            preset_args += [
                "--states-json",
                json.dumps(
                    {
                        "props": {
                            "frames": 4,
                            "fps": 1,
                            "loop": False,
                            "action": "four isolated compact prop variants",
                            "asset_labels": [
                                "wood-crate",
                                "oak-barrel",
                                "iron-lantern",
                                "trail-sign",
                            ],
                            "catalog": {
                                "category": "props",
                                "pivot": [64, 120],
                                "strategy_class": "compact_prop",
                            },
                        },
                        "pickups": {
                            "frames": 4,
                            "fps": 1,
                            "loop": False,
                            "action": "four isolated compact pickup variants",
                            "asset_labels": [
                                "gold-coin",
                                "blue-gem",
                                "health-potion",
                                "brass-key",
                            ],
                            "catalog": {
                                "category": "pickups",
                                "pivot": [64, 120],
                                "strategy_class": "compact_prop",
                            },
                        },
                    }
                ),
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--source-grid", default="4x2")
    parser.add_argument("--preset", action="append", help="repeat to limit presets")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--clean", action="store_true", help="destructively reset an owned output directory")
    args = parser.parse_args()
    if args.force and args.clean:
        raise SystemExit("use only one of --force or --clean")

    reference = args.reference.expanduser().resolve()
    out_dir = args.out_dir.expanduser().resolve()
    frames = crop_reference_frames(reference, parse_grid(args.source_grid))

    presets_path = Path(__file__).parents[1] / "references" / "presets.json"
    presets = json.loads(presets_path.read_text(encoding="utf-8"))["presets"]
    selected = args.preset or list(presets)
    unknown_presets = sorted(set(selected) - set(presets))
    if unknown_presets:
        raise SystemExit(f"unknown presets: {', '.join(unknown_presets)}")

    try:
        if args.clean and out_dir.exists():
            with replace_owned_run(out_dir, run_id="preset-smoke"):
                result = execute_smoke(reference, out_dir, selected, frames)
                if result:
                    raise RuntimeError("preset smoke failed; restoring the previous owned output")
                return result
        if out_dir.exists() and any(out_dir.iterdir()) and not args.force:
            raise SystemExit(f"output dir exists and is not empty: {out_dir}; pass --force or --clean")
        create_run_marker(out_dir, run_id="preset-smoke")
    except PathSafetyError as exc:
        raise SystemExit(str(exc)) from exc
    return execute_smoke(reference, out_dir, selected, frames)


if __name__ == "__main__":
    raise SystemExit(main())
