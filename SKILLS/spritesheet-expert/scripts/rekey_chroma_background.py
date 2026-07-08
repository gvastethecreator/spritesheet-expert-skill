#!/usr/bin/env python3
"""Replace or normalize a border-connected chroma background."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from PIL import Image


KEYS = {
    "green": (0, 255, 0),
    "cyan": (0, 255, 255),
    "blue": (0, 77, 255),
    "magenta": (255, 0, 255),
}


def parse_color(value: str) -> tuple[int, int, int]:
    raw = value.strip().lower()
    if raw in KEYS:
        return KEYS[raw]
    if raw.startswith("#") and len(raw) == 7:
        return tuple(int(raw[index : index + 2], 16) for index in (1, 3, 5))
    raise SystemExit(f"invalid color {value!r}; use key name or #RRGGBB")


def color_distance(left: tuple[int, int, int], right: tuple[int, int, int]) -> float:
    return math.sqrt(sum((left[index] - right[index]) ** 2 for index in range(3)))


def flood_background(image: Image.Image, key: tuple[int, int, int], threshold: float) -> bytearray:
    pixels = image.load()
    width, height = image.size
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--from-key", default="magenta")
    parser.add_argument("--to-key", required=True)
    parser.add_argument("--threshold", type=float, default=24.0)
    args = parser.parse_args()

    from_key = parse_color(args.from_key)
    to_key = parse_color(args.to_key)
    image = Image.open(args.input).convert("RGBA")
    mask = flood_background(image, from_key, args.threshold)
    pixels = image.load()
    replaced = 0
    for y in range(image.height):
        for x in range(image.width):
            if mask[y * image.width + x]:
                pixels[x, y] = (to_key[0], to_key[1], to_key[2], 255)
                replaced += 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    image.save(args.out)
    print(json.dumps({"ok": True, "input": str(args.input), "out": str(args.out), "replaced": replaced}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
