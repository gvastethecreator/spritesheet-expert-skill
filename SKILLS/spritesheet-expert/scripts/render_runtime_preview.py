#!/usr/bin/env python3
"""Render deterministic runtime still/playback evidence from a final manifest."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tempfile

from runio import atomic_write_text
from spritecore.locks import acquire_run_lock
from spritecore.runtime_preview import (
    RuntimePreviewError,
    build_evidence,
    encode_preview,
    prepare_preview,
)


def _atomic_write_bytes(target: Path, content: bytes) -> None:
    descriptor, temporary = tempfile.mkstemp(
        dir=str(target.parent), prefix=f".{target.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
        os.replace(temporary, target)
    except BaseException:
        if os.path.exists(temporary):
            os.unlink(temporary)
        raise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--manifest", default="manifest.json")
    parser.add_argument("--state", required=True)
    parser.add_argument(
        "--kind",
        choices=("runtime-still", "runtime-playback"),
        default="runtime-playback",
    )
    parser.add_argument("--frame", type=int, default=0)
    parser.add_argument("--out")
    parser.add_argument("--report")
    parser.add_argument("--viewport", default="256x256")
    parser.add_argument("--dpr", type=float, default=1.0)
    parser.add_argument("--scale", type=int, default=1)
    parser.add_argument("--background", default="#101018")
    parser.add_argument("--force", action="store_true")
    return parser


def _error(message: str) -> int:
    print(
        json.dumps(
            {"status": "operational-error", "errors": [message]},
            ensure_ascii=False,
        )
    )
    return 3


def main() -> int:
    args = _parser().parse_args()
    try:
        plan = prepare_preview(
            run_dir=args.run_dir,
            manifest_name=args.manifest,
            state=args.state,
            kind=args.kind,
            frame=args.frame,
            output_name=args.out,
            report_name=args.report,
            viewport=args.viewport,
            dpr=args.dpr,
            scale=args.scale,
            background=args.background,
            force=args.force,
        )
        artifact_bytes, placements = encode_preview(plan)
        evidence = build_evidence(plan, artifact_bytes, placements)
    except (OSError, RuntimePreviewError, ValueError) as exc:
        return _error(str(exc))

    try:
        with acquire_run_lock(plan.run_dir, "render-runtime-preview"):
            plan.output_path.parent.mkdir(parents=True, exist_ok=True)
            if not plan.force and (plan.output_path.exists() or plan.report_path.exists()):
                raise RuntimePreviewError(
                    "output appeared during render; pass --force to replace known outputs"
                )
            _atomic_write_bytes(plan.output_path, artifact_bytes)
            atomic_write_text(
                plan.report_path,
                json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
            )
    except (OSError, RuntimePreviewError, ValueError) as exc:
        return _error(str(exc))

    print(
        json.dumps(
            {
                "status": "pass",
                "artifact": evidence["artifact"],
                "report_path": plan.report_path.relative_to(plan.run_dir).as_posix(),
                "input_fingerprint": evidence["input_fingerprint"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
