#!/usr/bin/env python3
"""Record one hash-bound visual review for artifacts inside a sprite run."""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any, Mapping

from runio import atomic_write_text
from spritecore.paths import PathSafetyError, resolve_run_path
from spritecore.visual_review import (
    VISUAL_REVIEW_KIND,
    VISUAL_REVIEW_RELATIVE_PATH,
    VISUAL_REVIEW_VERSION,
    VisualReviewError,
    VisualReviewLoadError,
    VisualReviewValidationError,
    compute_input_fingerprint,
    snapshot_review_artifacts,
    validate_visual_review,
)


DEFAULT_OUTPUT = VISUAL_REVIEW_RELATIVE_PATH
_COPIED_FIELDS = (
    "reviewer_kind",
    "scope",
    "stage",
    "status",
    "rubric",
    "failures",
    "waivers",
)


def record_visual_review(
    draft: Mapping[str, Any],
    *,
    run_dir: Path,
    output: str | Path = DEFAULT_OUTPUT,
) -> dict[str, Any]:
    """Hash draft artifact paths, validate the result, and atomically record it."""

    run_root = Path(run_dir).expanduser().resolve()
    artifact_paths = _artifact_paths(draft.get("reviewed_artifacts"))
    artifacts = snapshot_review_artifacts(run_root, artifact_paths)
    document: dict[str, Any] = {
        "version": VISUAL_REVIEW_VERSION,
        "kind": VISUAL_REVIEW_KIND,
        **{
            field: deepcopy(draft[field])
            for field in _COPIED_FIELDS
            if field in draft
        },
        "reviewed_artifacts": artifacts,
        "reviewed_at": _utc_now(),
        "input_fingerprint": compute_input_fingerprint(artifacts),
    }
    validated = validate_visual_review(document, run_dir=run_root)
    target = resolve_run_path(run_root, output)
    if target.relative_to(run_root).as_posix() in {
        artifact["path"] for artifact in artifacts
    }:
        raise VisualReviewValidationError(
            ["visual review output cannot overwrite a reviewed artifact"]
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        target, json.dumps(validated, ensure_ascii=False, indent=2) + "\n"
    )
    return validated


def _artifact_paths(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise VisualReviewValidationError(
            ["reviewed_artifacts must be a list of paths or path objects"]
        )
    paths: list[str] = []
    for index, entry in enumerate(value):
        candidate = entry.get("path") if isinstance(entry, Mapping) else entry
        if not isinstance(candidate, str) or not candidate:
            raise VisualReviewValidationError(
                [f"reviewed_artifacts.{index}.path must be a non-empty string"]
            )
        paths.append(candidate)
    return paths


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _load_draft(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.expanduser().resolve().read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise VisualReviewLoadError(f"could not load visual review draft: {exc}") from exc
    if not isinstance(payload, dict):
        raise VisualReviewLoadError("visual review draft root must be a JSON object")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True, help="draft review JSON")
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        help="safe run-relative output path",
    )
    args = parser.parse_args()

    try:
        draft = _load_draft(args.review)
        recorded = record_visual_review(
            draft, run_dir=args.run_dir, output=args.output
        )
    except (VisualReviewError, PathSafetyError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"could not record visual review: {exc}", file=sys.stderr)
        return 3

    print(json.dumps(recorded, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
