#!/usr/bin/env python3
"""Baseline-register Image Gen frames and build a review sheet.

This script never draws or alters a pose. It translates each complete generated
raster so its detected registration baseline matches frame 1, then applies the
same resize to every frame for a compact contact sheet.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageStat


def border_color(image: Image.Image) -> tuple[int, int, int]:
    rgb = image.convert("RGB")
    width, height = rgb.size
    samples = [
        rgb.getpixel((0, 0)),
        rgb.getpixel((width - 1, 0)),
        rgb.getpixel((0, height - 1)),
        rgb.getpixel((width - 1, height - 1)),
    ]
    return tuple(round(sum(pixel[channel] for pixel in samples) / len(samples)) for channel in range(3))


def foreground_mask(image: Image.Image) -> Image.Image:
    if "A" in image.getbands():
        alpha = image.getchannel("A")
        if alpha.getextrema()[0] < 250:
            return alpha.point(lambda value: 255 if value >= 20 else 0)
    rgb = image.convert("RGB")
    background = Image.new("RGB", rgb.size, border_color(rgb))
    difference = ImageChops.difference(rgb, background).convert("L")
    return difference.point(lambda value: 255 if value >= 24 else 0)


def baseline_row(image: Image.Image) -> int:
    """Return the lowest foreground row instead of the darkest lower-body row."""
    bbox = foreground_mask(image).getbbox()
    if bbox is None:
        raise ValueError("no foreground subject found for baseline detection")
    return bbox[3] - 1


def translate_to_baseline(image: Image.Image, source_y: int, target_y: int) -> Image.Image:
    rgb = image.convert("RGB")
    translated = Image.new("RGB", rgb.size, border_color(rgb))
    translated.paste(rgb, (0, target_y - source_y))
    return translated


def subject_bbox(image: Image.Image, baseline_y: int) -> tuple[int, int, int, int] | None:
    mask = foreground_mask(image)
    start = max(0, baseline_y - 3)
    stop = min(image.height, baseline_y + 4)
    band = mask.crop((0, start, image.width, stop))
    foreground_ratio = ImageStat.Stat(band).sum[0] / (255 * max(1, image.width * band.height))
    if foreground_ratio > 0.65:
        draw = ImageDraw.Draw(mask)
        draw.rectangle((0, start, image.width, stop - 1), fill=0)
    return mask.getbbox()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frame", action="append", required=True, type=Path)
    parser.add_argument("--selected-dir", required=True, type=Path)
    parser.add_argument("--sheet", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--columns", type=int, default=3)
    parser.add_argument("--cell-size", type=int, default=512)
    args = parser.parse_args()

    if len(args.frame) < 2:
        raise SystemExit("at least two --frame inputs are required")
    if args.columns < 1 or args.cell_size < 64:
        raise SystemExit("columns must be positive and cell-size must be at least 64")

    sources = [path.expanduser().resolve() for path in args.frame]
    images = [Image.open(path).convert("RGB") for path in sources]
    dimensions = {image.size for image in images}
    if len(dimensions) != 1:
        raise SystemExit(f"all source frames must share dimensions, got {sorted(dimensions)}")

    target_baseline = baseline_row(images[0])
    args.selected_dir.mkdir(parents=True, exist_ok=True)
    args.sheet.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)

    selected: list[Image.Image] = []
    records: list[dict[str, object]] = []
    for index, (source, image) in enumerate(zip(sources, images, strict=True), start=1):
        detected = baseline_row(image)
        normalized = translate_to_baseline(image, detected, target_baseline)
        output = args.selected_dir / f"frame-{index:02d}.png"
        normalized.save(output)
        selected.append(normalized)
        bbox = subject_bbox(normalized, target_baseline)
        records.append(
            {
                "frame": index,
                "source": str(source),
                "selected": str(output.resolve()),
                "source_baseline_y": detected,
                "target_baseline_y": target_baseline,
                "translation_y": target_baseline - detected,
                "subject_bbox": list(bbox) if bbox else None,
                "subject_width": bbox[2] - bbox[0] if bbox else 0,
                "subject_height": bbox[3] - bbox[1] if bbox else 0,
                "source_sha256": sha256_file(source),
                "selected_sha256": sha256_file(output),
            }
        )

    rows = math.ceil(len(selected) / args.columns)
    sheet = Image.new(
        "RGB",
        (args.columns * args.cell_size, rows * args.cell_size),
        border_color(selected[0]),
    )
    for index, image in enumerate(selected):
        resized = image.resize((args.cell_size, args.cell_size), Image.Resampling.LANCZOS)
        x = (index % args.columns) * args.cell_size
        y = (index // args.columns) * args.cell_size
        sheet.paste(resized, (x, y))
    sheet.save(args.sheet)

    report = {
        "ok": True,
        "kind": "imagegen-motion-sequence-review",
        "frame_count": len(selected),
        "columns": args.columns,
        "rows": rows,
        "cell_size": args.cell_size,
        "sheet": str(args.sheet.resolve()),
        "sheet_sha256": sha256_file(args.sheet),
        "frames": records,
    }
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
