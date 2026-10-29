#!/usr/bin/env python3
"""Ingest an existing animation video and build its candidate-frame editor."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from build_video_frame_selector import build_selector
from runio import atomic_write_bytes, atomic_write_text
from spritecore.contracts import ContractError
from spritecore.locks import RunLockError, acquire_run_lock
from spritecore.video_animation import (
    VideoAnimationError,
    ingest_imported_video,
    revalidate_imported_video_sources,
)


def parse_sample_indices(raw: str | None) -> list[int] | None:
    if raw is None:
        return None
    try:
        return [int(value.strip()) for value in raw.split(",") if value.strip()]
    except ValueError as exc:
        raise ValueError("--sample-indices must be comma-separated integers") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--state", required=True)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--first-frame", type=Path)
    parser.add_argument(
        "--sample-indices",
        help="reviewed chronological decoder indices; frame 0 must stay first",
    )
    parser.add_argument(
        "--sampling-strategy",
        choices=("adaptive", "uniform"),
        default="adaptive",
    )
    parser.add_argument("--license", default="caller-provided-source-terms")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    try:
        result = ingest_imported_video(
            run_dir=args.run_dir,
            state=args.state,
            video_path=args.video,
            first_frame_path=args.first_frame,
            force=args.force,
            sample_indices=parse_sample_indices(args.sample_indices),
            sampling_strategy=args.sampling_strategy,
            license_name=args.license,
        )
        with acquire_run_lock(result.run_dir, "ingest-video-animation"):
            revalidate_imported_video_sources(result)
            for output_path, content in result.additional_outputs:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                atomic_write_bytes(output_path, content)
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
            selector = build_selector(
                run_dir=result.run_dir,
                state=args.state,
                source_report=result.report_path,
                force=True,
            )
    except (
        ContractError,
        OSError,
        RunLockError,
        VideoAnimationError,
        ValueError,
    ) as exc:
        print(json.dumps({"status": "operational-error", "errors": [str(exc)]}, ensure_ascii=False))
        return 3

    print(
        json.dumps(
            {
                "status": "pass",
                "raw_path": result.raw_path.relative_to(result.run_dir).as_posix(),
                "report_path": result.report_path.relative_to(result.run_dir).as_posix(),
                "selector": selector["output"],
                "selector_evidence": selector["evidence"],
                "next": "review candidates, re-ingest reviewed indices, then run background removal and extraction",
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
