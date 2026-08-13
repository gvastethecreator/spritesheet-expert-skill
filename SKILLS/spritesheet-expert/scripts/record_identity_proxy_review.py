#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Record a hash-bound visual acceptance for exact identity-proxy false positives."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from runio import atomic_write_text
from spritecore.visual_review import compute_input_fingerprint, snapshot_review_artifacts


OUTPUT = "qa/identity-proxy-review.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--reviewer-kind", choices=("human", "vision-model"), default="vision-model")
    args = parser.parse_args()

    run_dir = args.run_dir.expanduser().resolve()
    report_path = run_dir / "qa" / "identity-consistency-report.json"
    try:
        report = json.loads(report_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        print(f"could not load failing identity report: {exc}", file=sys.stderr)
        return 1
    errors = report.get("errors") if isinstance(report.get("errors"), list) else []
    if report.get("ok") is not False or not errors:
        print("identity report must contain current proxy failures before review", file=sys.stderr)
        return 1
    if len(args.reason.strip()) < 20:
        print("reason must explain the proxy false positive", file=sys.stderr)
        return 1
    states = sorted({str(error).split(":", 1)[0] for error in errors})
    paths = [
        "sprite-request.json",
        "frames/frames-manifest.json",
        "sprite-sheet-alpha.png",
        "qa/background-matte-review.png",
        *[f"qa/{state}-contact.png" for state in states],
        *[f"qa/{state}-onion.png" for state in states],
    ]
    try:
        artifacts = snapshot_review_artifacts(run_dir, paths)
    except Exception as exc:
        print(f"could not snapshot identity review evidence: {exc}", file=sys.stderr)
        return 1
    document = {
        "version": 1,
        "kind": "identity-proxy-visual-review",
        "status": "approved",
        "reviewer_kind": args.reviewer_kind,
        "reason": args.reason.strip(),
        "covered_errors": errors,
        "reviewed_artifacts": artifacts,
        "reviewed_at": utc_now(),
        "input_fingerprint": compute_input_fingerprint(artifacts),
    }
    target = run_dir / OUTPUT
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(target, json.dumps(document, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(document, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
