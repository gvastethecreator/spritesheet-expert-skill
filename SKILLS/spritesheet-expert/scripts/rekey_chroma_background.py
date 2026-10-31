#!/usr/bin/env python3
"""Replace or normalize a border-connected chroma background."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image
from check_chroma_key_safety import flood_background, parse_color


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
