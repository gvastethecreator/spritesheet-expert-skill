#!/usr/bin/env python3
"""Prepare contextual alpha-region segmentation jobs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from spritecore.item_segmentation import (
    ItemSegmentationError,
    prepare_segmentation_jobs,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--force", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        jobs = prepare_segmentation_jobs(
            args.manifest,
            args.out,
            force=args.force,
        )
    except (ItemSegmentationError, OSError) as exc:
        print(json.dumps({"status": "operational-error", "errors": [str(exc)]}, ensure_ascii=False))
        return 3
    print(
        json.dumps(
            {
                "status": "pass",
                "job_count": len(jobs),
                "output": str(args.out.expanduser().resolve()),
                "selection": "source-regions",
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
