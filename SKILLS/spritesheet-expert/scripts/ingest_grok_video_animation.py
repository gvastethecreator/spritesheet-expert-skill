#!/usr/bin/env python3
"""Ingest a completed $grok-imagine video into a deterministic raw sprite grid."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from runio import atomic_write_bytes, atomic_write_text
from spritecore.contracts import ContractError
from spritecore.locks import RunLockError, acquire_run_lock
from spritecore.video_animation import (
    VideoAnimationError,
    ingest_video,
    revalidate_video_sources,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--state", required=True)
    parser.add_argument("--invocation", type=Path, required=True)
    parser.add_argument("--job")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    try:
        result = ingest_video(
            run_dir=args.run_dir,
            state=args.state,
            invocation_path=args.invocation,
            job_name=args.job,
            force=args.force,
        )
        with acquire_run_lock(result.run_dir, "ingest-grok-video-animation"):
            revalidate_video_sources(result)
            result.raw_path.parent.mkdir(parents=True, exist_ok=True)
            result.report_path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_bytes(result.raw_path, result.raw_bytes)
            atomic_write_text(
                result.provenance_path,
                json.dumps(result.provenance, ensure_ascii=False, indent=2) + "\n",
            )
            atomic_write_text(
                result.report_path,
                json.dumps(result.report, ensure_ascii=False, indent=2) + "\n",
            )
    except (ContractError, OSError, RunLockError, VideoAnimationError, ValueError) as exc:
        print(json.dumps({"status": "operational-error", "errors": [str(exc)]}, ensure_ascii=False))
        return 3

    print(
        json.dumps(
            {
                "status": "pass",
                "raw_path": result.raw_path.relative_to(result.run_dir).as_posix(),
                "report_path": result.report_path.relative_to(result.run_dir).as_posix(),
                "provenance_path": result.provenance_path.relative_to(result.run_dir).as_posix(),
                "next": "run the normal extraction, registration, atlas, alignment, identity, animation, runtime-preview, and aggregate gates",
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
