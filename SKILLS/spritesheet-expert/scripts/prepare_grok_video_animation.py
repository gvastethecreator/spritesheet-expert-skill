#!/usr/bin/env python3
"""Prepare a dry-run-first $grok-imagine job from one accepted first frame."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from runio import atomic_write_bytes, atomic_write_text
from spritecore.contracts import ContractError
from spritecore.locks import RunLockError, acquire_run_lock
from spritecore.video_animation import (
    VideoAnimationError,
    prepare_video_job,
    revalidate_prepared_sources,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--state", required=True)
    parser.add_argument("--first-frame", required=True)
    parser.add_argument("--duration-seconds", type=int, choices=(6, 10), default=6)
    parser.add_argument(
        "--provider-action",
        help="state-local generation instruction; does not mutate sprite-request.json",
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    try:
        prepared = prepare_video_job(
            repo_root=args.repo_root,
            run_dir=args.run_dir,
            state=args.state,
            first_frame_name=args.first_frame,
            duration_seconds=args.duration_seconds,
            provider_action_override=args.provider_action,
            force=args.force,
        )
        with acquire_run_lock(prepared.run_dir, "prepare-grok-video-animation"):
            revalidate_prepared_sources(prepared)
            if not prepared.force and (
                prepared.prompt_path.exists() or prepared.job_path.exists()
            ):
                raise VideoAnimationError("Grok video job appeared before commit")
            prepared.prompt_path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_bytes(
                prepared.prompt_path,
                prepared.prompt_text.encode("utf-8"),
            )
            atomic_write_text(
                prepared.job_path,
                json.dumps(prepared.job, ensure_ascii=False, indent=2) + "\n",
            )
    except (ContractError, OSError, RunLockError, VideoAnimationError, ValueError) as exc:
        print(json.dumps({"status": "operational-error", "errors": [str(exc)]}, ensure_ascii=False))
        return 3

    print(
        json.dumps(
            {
                "status": "prepared",
                "job_path": prepared.job_path.relative_to(prepared.run_dir).as_posix(),
                "prompt_path": prepared.prompt_path.relative_to(prepared.run_dir).as_posix(),
                "dry_run": prepared.job["dry_run"],
                "next": "review the prompt, then run $grok-imagine dry-run; add --ack-run only with current-task consent",
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
