#!/usr/bin/env python3
"""Validate current item-atlas bytes: 0 pass, 2 review required, 3 invalid."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

from spritecore.item_delivery import validate_delivery


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--draft", action="store_true", help="Allow unresolved review, never corrupted artifacts")
    parser.add_argument("--max-texture-size", type=int, default=16384,
                        help="Target device limit; this default is not an engine capability probe")
    args = parser.parse_args()
    report = validate_delivery(args.manifest, draft=args.draft, max_texture_size=args.max_texture_size)
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    return {"pass": 0, "review-required": 2}.get(report["status"], 3)


if __name__ == "__main__":
    sys.exit(main())
