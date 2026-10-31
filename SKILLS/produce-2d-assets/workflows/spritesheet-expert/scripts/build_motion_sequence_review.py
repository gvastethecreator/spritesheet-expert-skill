#!/usr/bin/env python3
"""Align detected baselines and build a motion review sheet.

Reject translations that clip detected foreground. Selected PNGs retain alpha;
contact-sheet resizing preserves aspect ratio. Inspect the result before acceptance.
"""

from __future__ import annotations

import argparse
import hashlib
from io import BytesIO
import json
import math
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageStat
from runio import atomic_save_image, atomic_write_text


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
    source = image.convert("RGBA")
    alpha = source.getchannel("A")
    transparent = alpha.getextrema()[0] < 255
    bbox = alpha.getbbox() if transparent else foreground_mask(source).getbbox()
    offset = target_y - source_y
    if bbox is None or bbox[1] + offset < 0 or bbox[3] + offset > source.height:
        raise ValueError("baseline translation would clip detected foreground")
    background = (0, 0, 0, 0) if transparent else (*border_color(source), 255)
    translated = Image.new("RGBA", source.size, background)
    translated.paste(source, (0, offset))
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
    selected_dir = args.selected_dir.expanduser().resolve()
    sheet_path, report_path = args.sheet.expanduser().resolve(), args.report.expanduser().resolve()
    selected_paths = [selected_dir / f"frame-{index:02d}.png" for index in range(1, len(sources) + 1)]
    outputs = [*selected_paths, sheet_path, report_path]
    if len(set(outputs)) != len(outputs) or set(outputs) & set(sources):
        raise SystemExit("motion review outputs must be distinct and cannot overwrite source frames")
    if any(path.exists() and not path.is_file() for path in outputs):
        raise SystemExit("motion review output destinations must be files")
    images, source_hashes = [], []
    for source in sources:
        content = source.read_bytes()
        source_hashes.append(hashlib.sha256(content).hexdigest())
        with Image.open(BytesIO(content)) as opened:
            images.append(opened.convert("RGBA"))
    dimensions = {image.size for image in images}
    if len(dimensions) != 1:
        raise SystemExit(f"all source frames must share dimensions, got {sorted(dimensions)}")

    baselines = [baseline_row(image) for image in images]
    target_baseline = baselines[0]
    selected = [translate_to_baseline(image, baseline, target_baseline) for image, baseline in zip(images, baselines, strict=True)]
    selected_dir.mkdir(parents=True, exist_ok=True)
    sheet_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, object]] = []
    for index, (source, detected, normalized) in enumerate(zip(sources, baselines, selected, strict=True), start=1):
        output = selected_paths[index - 1]
        atomic_save_image(normalized, output)
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
                "source_sha256": source_hashes[index - 1],
                "selected_sha256": sha256_file(output),
            }
        )

    rows = math.ceil(len(selected) / args.columns)
    sheet = Image.new(
        "RGB",
        (args.columns * args.cell_size, rows * args.cell_size),
        (17, 17, 17),
    )
    for index, image in enumerate(selected):
        scale = min(args.cell_size / image.width, args.cell_size / image.height)
        size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
        resized = image.resize(size, Image.Resampling.LANCZOS)
        x = (index % args.columns) * args.cell_size + (args.cell_size - size[0]) // 2
        y = (index // args.columns) * args.cell_size + (args.cell_size - size[1]) // 2
        sheet.paste(resized, (x, y), resized.getchannel("A"))
    atomic_save_image(sheet, sheet_path)

    report = {
        "ok": True,
        "kind": "imagegen-motion-sequence-review",
        "frame_count": len(selected),
        "columns": args.columns,
        "rows": rows,
        "cell_size": args.cell_size,
        "sheet": str(sheet_path),
        "sheet_sha256": sha256_file(sheet_path),
        "frames": records,
    }
    atomic_write_text(report_path, json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
