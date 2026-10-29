#!/usr/bin/env python3
"""Check whether a chroma key is too close to visible artwork colors."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from PIL import Image


KEYS = {
    "green": (0, 255, 0),
    "cyan": (0, 255, 255),
    "blue": (0, 77, 255),
    "magenta": (255, 0, 255),
}


def parse_color(value: str) -> tuple[int, int, int]:
    raw = value.strip()
    if raw in KEYS:
        return KEYS[raw]
    if raw.startswith("#") and len(raw) == 7:
        return tuple(int(raw[index : index + 2], 16) for index in (1, 3, 5))
    raise SystemExit(f"invalid color {value!r}; use key name or #RRGGBB")


def color_distance(left: tuple[int, int, int], right: tuple[int, int, int]) -> float:
    return math.sqrt(sum((left[index] - right[index]) ** 2 for index in range(3)))


def flood_background(image: Image.Image, key: tuple[int, int, int], threshold: float) -> bytearray:
    rgba = image.convert("RGBA")
    pixels = rgba.load()
    width, height = rgba.size
    mask = bytearray(width * height)
    stack: list[int] = []

    def maybe_add(x: int, y: int) -> None:
        index = y * width + x
        if mask[index]:
            return
        red, green, blue, alpha = pixels[x, y]
        if alpha <= 16 or color_distance((red, green, blue), key) <= threshold:
            mask[index] = 1
            stack.append(index)

    for x in range(width):
        maybe_add(x, 0)
        maybe_add(x, height - 1)
    for y in range(1, max(1, height - 1)):
        maybe_add(0, y)
        maybe_add(width - 1, y)

    while stack:
        current = stack.pop()
        x = current % width
        y = current // width
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if nx < 0 or ny < 0 or nx >= width or ny >= height:
                continue
            maybe_add(nx, ny)
    return mask


def percentile(values: list[float], ratio: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round((len(ordered) - 1) * ratio)))
    return ordered[index]


def analyze(path: Path, key: tuple[int, int, int], args: argparse.Namespace) -> dict[str, Any]:
    with Image.open(path) as opened:
        image = opened.convert("RGBA")
        if max(image.size) > args.sample_size:
            image.thumbnail((args.sample_size, args.sample_size), Image.Resampling.NEAREST)
        pixels = image.load()
        background = flood_background(image, key, args.background_threshold)
        subject_distances: list[float] = []
        subject_pixels = 0
        near_subject = 0
        exact_subject = 0
        for y in range(image.height):
            for x in range(image.width):
                red, green, blue, alpha = pixels[x, y]
                if alpha <= 16 or background[y * image.width + x]:
                    continue
                subject_pixels += 1
                distance = color_distance((red, green, blue), key)
                subject_distances.append(distance)
                if distance <= args.warn_distance:
                    near_subject += 1
                if distance <= args.exact_distance:
                    exact_subject += 1
    candidate_scores = {}
    if subject_distances:
        with Image.open(path) as opened:
            probe = opened.convert("RGBA")
            if max(probe.size) > args.sample_size:
                probe.thumbnail((args.sample_size, args.sample_size), Image.Resampling.NEAREST)
            background_current = flood_background(probe, key, args.background_threshold)
            subject_colors = [
                probe.getpixel((x, y))[:3]
                for y in range(probe.height)
                for x in range(probe.width)
                if probe.getpixel((x, y))[3] > 16 and not background_current[y * probe.width + x]
            ]
            for name, candidate in KEYS.items():
                distances = [color_distance(color, candidate) for color in subject_colors]
                candidate_scores[name] = {
                    "hex": f"#{candidate[0]:02X}{candidate[1]:02X}{candidate[2]:02X}",
                    "p01_distance": round(percentile(distances, 0.01) or 0, 2),
                    "near_ratio": round(sum(1 for value in distances if value <= args.warn_distance) / max(1, len(distances)), 5),
                    "exact_pixels": sum(1 for value in distances if value <= args.exact_distance),
                }
    recommended = None
    if candidate_scores:
        recommended = max(
            candidate_scores,
            key=lambda name: (
                -candidate_scores[name]["exact_pixels"],
                candidate_scores[name]["p01_distance"],
                -candidate_scores[name]["near_ratio"],
            ),
        )
    near_ratio = near_subject / max(1, subject_pixels)
    ok = subject_pixels > 0 and exact_subject == 0 and near_ratio <= args.max_near_ratio
    if ok:
        severity = "pass"
    elif near_ratio > args.max_near_ratio or exact_subject > args.fail_exact_pixels:
        severity = "fail"
    else:
        severity = "warn"
    return {
        "path": str(path),
        "key": f"#{key[0]:02X}{key[1]:02X}{key[2]:02X}",
        "ok": ok,
        "severity": severity,
        "subject_pixels": subject_pixels,
        "near_subject_pixels": near_subject,
        "near_subject_ratio": round(near_ratio, 5),
        "exact_subject_pixels": exact_subject,
        "min_subject_distance": round(min(subject_distances), 2) if subject_distances else None,
        "p01_subject_distance": round(percentile(subject_distances, 0.01) or 0, 2) if subject_distances else None,
        "recommended_key": recommended,
        "candidate_scores": candidate_scores,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("images", nargs="+", type=Path)
    parser.add_argument("--key", default="magenta")
    parser.add_argument("--background-threshold", type=float, default=24.0)
    parser.add_argument("--warn-distance", type=float, default=120.0)
    parser.add_argument("--exact-distance", type=float, default=12.0)
    parser.add_argument("--max-near-ratio", type=float, default=0.01)
    parser.add_argument("--fail-exact-pixels", type=int, default=128)
    parser.add_argument("--sample-size", type=int, default=512)
    args = parser.parse_args()

    key = parse_color(args.key)
    results = [analyze(path, key, args) for path in args.images]
    output = {"ok": all(result["ok"] for result in results), "results": results}
    print(json.dumps(output, indent=2))
    return 0 if output["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
