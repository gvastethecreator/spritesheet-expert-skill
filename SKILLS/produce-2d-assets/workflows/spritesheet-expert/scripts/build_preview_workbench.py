#!/usr/bin/env python3
"""Build a self-contained interactive sprite review workbench."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from runio import atomic_write_bytes, atomic_write_text
from spritecore.locks import acquire_run_lock
from spritecore.preview_workbench import PreviewWorkbenchError, prepare_workbench


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--manifest", default="manifest.json")
    parser.add_argument("--out", default="qa/preview-workbench/index.html")
    parser.add_argument("--report", default="qa/preview-workbench/workbench.evidence.json")
    parser.add_argument("--force", action="store_true")
    return parser


def _error(message: str) -> int:
    print(json.dumps({"status": "operational-error", "errors": [message]}, ensure_ascii=False))
    return 3


def main() -> int:
    args = _parser().parse_args()
    try:
        output_path, report_path, html_bytes, report = prepare_workbench(
            run_dir=args.run_dir,
            manifest_name=args.manifest,
            output_name=args.out,
            report_name=args.report,
            force=args.force,
        )
    except (OSError, PreviewWorkbenchError, ValueError) as exc:
        return _error(str(exc))

    run_dir = args.run_dir.expanduser().resolve()
    try:
        with acquire_run_lock(run_dir, "build-preview-workbench"):
            output_path.parent.mkdir(parents=True, exist_ok=True)
            if not args.force and (output_path.exists() or report_path.exists()):
                raise PreviewWorkbenchError(
                    "output appeared during build; pass --force to replace known outputs"
                )
            atomic_write_bytes(output_path, html_bytes)
            atomic_write_text(
                report_path,
                json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            )
    except (OSError, PreviewWorkbenchError, ValueError) as exc:
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
