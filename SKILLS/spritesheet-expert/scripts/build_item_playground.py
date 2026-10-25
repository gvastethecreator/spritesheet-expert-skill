#!/usr/bin/env python3
"""Build a self-contained interactive item-atlas playground."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from runio import atomic_write_bytes, atomic_write_text
from spritecore.item_playground import ItemPlaygroundError, prepare_playground
from spritecore.locks import acquire_run_lock


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--manifest", default="manifest.json")
    parser.add_argument("--out", default="qa/item-playground/index.html")
    parser.add_argument("--report", default="qa/item-playground/playground.evidence.json")
    parser.add_argument("--preview-max-width", type=int, default=900)
    parser.add_argument("--assume-run-lock", action="store_true",
                        help="Caller already owns the run lock (workflow stage use)")
    parser.add_argument("--force", action="store_true")
    return parser


def _error(message: str) -> int:
    print(json.dumps({"status": "operational-error", "errors": [message]}, ensure_ascii=False))
    return 3


def main() -> int:
    args = _parser().parse_args()
    try:
        output_path, report_path, html_bytes, report = prepare_playground(
            run_dir=args.run_dir,
            manifest_name=args.manifest,
            output_name=args.out,
            report_name=args.report,
            force=args.force,
            preview_max_width=args.preview_max_width,
        )
    except (OSError, ItemPlaygroundError, ValueError) as exc:
        return _error(str(exc))

    run_dir = args.run_dir.expanduser().resolve()

    def write_outputs() -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if not args.force and (output_path.exists() or report_path.exists()):
            raise ItemPlaygroundError(
                "output appeared during build; pass --force to replace known outputs"
            )
        atomic_write_bytes(output_path, html_bytes)
        atomic_write_text(
            report_path,
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        )

    try:
        if args.assume_run_lock:
            write_outputs()
        else:
            with acquire_run_lock(run_dir, "build-item-playground"):
                write_outputs()
    except (OSError, ItemPlaygroundError, ValueError) as exc:
        return _error(str(exc))

    print(
        json.dumps(
            {
                "status": "pass",
                "artifact": report["artifact"],
                "report_path": report_path.relative_to(run_dir).as_posix(),
                "input_fingerprint": report["input_fingerprint"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
