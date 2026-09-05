#!/usr/bin/env python3
"""Apply reviewed model proposals and rebuild an exact-pixel item atlas."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from spritecore.item_segmentation import ItemSegmentationError, apply_segmentation_results
from spritecore.item_sheet import ItemSheetError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--jobs", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--minimum-confidence", type=float, default=0.70)
    parser.add_argument("--force", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        manifest = apply_segmentation_results(
            args.manifest,
            args.jobs,
            args.results,
            args.output_dir,
            minimum_confidence=args.minimum_confidence,
            force=args.force,
        )
    except (ItemSegmentationError, ItemSheetError, OSError) as exc:
        print(json.dumps({"status": "contract-failure", "errors": [str(exc)]}, ensure_ascii=False))
        return 1
    application = manifest["segmentationApplication"]
    print(
        json.dumps(
            {
                "status": "pass",
                "run_id": manifest["runId"],
                "item_count": len(manifest["items"]),
                "split_parent_count": application["splitParentCount"],
                "mask_count": application["maskCount"],
                "manifest": str((args.output_dir / "manifest.json").resolve()),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
