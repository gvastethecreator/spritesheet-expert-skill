#!/usr/bin/env python3
"""Segment an irregular RGBA item sheet and repack it without rescaling."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from spritecore.item_sheet import (
    ItemSheetError,
    PackingConfig,
    SegmentationConfig,
    build_item_atlas,
    validate_manifest_geometry,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="RGBA source sheet")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--alpha-high", type=int, default=64)
    parser.add_argument("--alpha-low", type=int, default=2)
    parser.add_argument("--halo-radius", type=int, default=6)
    parser.add_argument("--min-strong-pixels", type=int, default=12)
    parser.add_argument("--connectivity", type=int, choices=(4, 8), default=8)
    parser.add_argument("--grid-quantum", type=int, default=32)
    parser.add_argument("--padding", type=int, default=16)
    parser.add_argument("--outer-padding", type=int, default=0)
    parser.add_argument("--max-width", type=int, default=4096)
    parser.add_argument("--extrude", type=int, default=0)
    parser.add_argument("--force", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        manifest = build_item_atlas(
            args.source,
            args.output_dir,
            segmentation=SegmentationConfig(
                alpha_high=args.alpha_high,
                alpha_low=args.alpha_low,
                halo_radius=args.halo_radius,
                min_strong_pixels=args.min_strong_pixels,
                connectivity=args.connectivity,
            ),
            packing=PackingConfig(
                quantum=args.grid_quantum,
                padding=args.padding,
                outer_padding=args.outer_padding,
                max_width=args.max_width,
                extrude=args.extrude,
            ),
            force=args.force,
        )
        errors = validate_manifest_geometry(manifest)
        if errors:
            print(
                json.dumps(
                    {"status": "contract-failure", "errors": errors},
                    ensure_ascii=False,
                )
            )
            return 1
    except ItemSheetError as exc:
        print(
            json.dumps(
                {"status": "operational-error", "errors": [str(exc)]},
                ensure_ascii=False,
            )
        )
        return 3

    print(
        json.dumps(
            {
                "status": "pass",
                "run_id": manifest["runId"],
                "item_count": len(manifest["items"]),
                "atlas": manifest["atlas"],
                "manifest": str((args.output_dir / "manifest.json").resolve()),
                "source_overlay": str(
                    (args.output_dir / manifest["evidence"]["sourceComponents"]).resolve()
                ),
                "atlas_grid": str(
                    (args.output_dir / manifest["evidence"]["atlasGrid"]).resolve()
                ),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
