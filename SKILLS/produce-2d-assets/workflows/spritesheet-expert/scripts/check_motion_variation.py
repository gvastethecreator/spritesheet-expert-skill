#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Heuristic motion QA for generated sprite animation rows.

This catches the common failure where walk/run rows keep legs and lower-body
parts in nearly the same pose across every frame. It is intentionally simple:
no pose model, no new dependency, just alpha-shape movement in extracted cells.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from PIL import Image

from runio import atomic_write_text
from spritecore.paths import resolve_run_path
from check_animation_contracts import (
    LOCOMOTION_WORKFLOWS,
    LOCOMOTION_TOKENS,
    alpha_bbox,
    contact_phase_check,
    dedupe_ordered,
    frame_rows_by_state,
    load_frames,
    load_json,
    normalized_list,
    normalized_pair_diff,
    normalized_threshold,
    report_output_path,
    support_balance,
    support_side,
    workflows_for_state,
)


def is_locomotion_state(state: str, entry: dict[str, Any]) -> bool:
    action = str(entry.get("action", "")).lower()
    workflows = [value for value in normalized_list(entry.get("animation_workflows")) if value != "auto"]
    if workflows:
        return bool(set(workflows) & LOCOMOTION_WORKFLOWS)
    text = f"{state} {action}".lower()
    tokens = {token for token in re.split(r"[^a-z0-9]+", text) if token}
    return bool(tokens & LOCOMOTION_TOKENS)


def selected_states(request: dict[str, Any], mode: str, art_direction: dict[str, Any]) -> list[str]:
    states = request.get("states", {})
    if mode == "all":
        return list(states)
    if mode == "locomotion":
        selected = []
        for state, entry in states.items():
            workflows, _source = workflows_for_state(request, art_direction, state, entry)
            if is_locomotion_state(state, {**entry, "animation_workflows": workflows}):
                selected.append(state)
        return selected
    return dedupe_ordered([state.strip() for state in mode.split(",") if state.strip()])


def body_center(frame: Image.Image) -> tuple[float, float]:
    bbox = alpha_bbox(frame)
    if not bbox:
        return 0.0, 0.0
    x0, y0, x1, y1 = bbox
    return (x0 + x1) / (2 * frame.width), (y0 + y1) / (2 * frame.height)


def inspect_state(
    state: str,
    entry: dict[str, Any],
    frames: list[Image.Image],
    args: argparse.Namespace,
    shared_idle: bool = False,
    creature_motion: dict[str, Any] | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    diffs: list[float] = []
    balances = [support_balance(frame) for frame in frames]
    anatomy = str((creature_motion or {}).get("anatomy", "")).strip().lower()
    locomotion = str((creature_motion or {}).get("locomotion", "")).strip().lower()
    is_amorphous_pulse = anatomy == "amorphous" and locomotion == "pulse"
    min_average_lower_diff = 0.05 if is_amorphous_pulse else args.min_average_lower_diff
    min_pair_lower_diff = 0.03 if is_amorphous_pulse else args.min_pair_lower_diff
    min_opposite_contact_pose_diff = (
        0.05 if is_amorphous_pulse else args.min_opposite_contact_pose_diff
    )
    threshold_policy = "amorphous-pulse" if is_amorphous_pulse else "default"
    phase_check = contact_phase_check(
        frames,
        args,
        shared_idle=shared_idle,
        min_pose_diff=min_opposite_contact_pose_diff,
    )
    centers = [body_center(frame) for frame in frames]
    complete = bool(frames) and any(alpha_bbox(frame) is not None for frame in frames)
    if not complete:
        errors.append("motion analysis requires foreground above alpha threshold 16")
    pairs = len(frames) if entry.get("loop", True) and len(frames) > 2 else max(0, len(frames) - 1)

    for index in range(pairs):
        left = frames[index]
        right = frames[(index + 1) % len(frames)]
        diffs.append(normalized_pair_diff(left, right, args.lower_body_start))

    average_diff = sum(diffs) / len(diffs) if diffs else 0.0
    min_diff = min(diffs) if diffs else 0.0
    support_range = max(balances) - min(balances) if balances else 0.0
    center_x_range = max((c[0] for c in centers), default=0.0) - min((c[0] for c in centers), default=0.0)
    center_y_range = max((c[1] for c in centers), default=0.0) - min((c[1] for c in centers), default=0.0)

    if len(frames) < 2:
        warnings.append("state has fewer than two frames; motion variation not meaningful")
    elif average_diff < min_average_lower_diff:
        errors.append(
            f"lower-body silhouette barely changes across frames (avg {average_diff:.3f}; expected >= {min_average_lower_diff:.3f})"
        )
    elif min_diff < min_pair_lower_diff:
        errors.append(
            f"one or more adjacent frames are too similar in the lower body (min {min_diff:.3f}; expected >= {min_pair_lower_diff:.3f})"
        )

    if len(frames) >= 3 and support_range < args.min_support_range:
        warnings.append(
            f"lower-body screen-space balance barely varies (range {support_range:.3f}; "
            f"diagnostic target >= {args.min_support_range:.3f})"
        )
    if is_locomotion_state(state, entry) and phase_check and not phase_check["ok"]:
        message = (
            "opposite-contact candidate duplicates the first lower-body pose "
            f"(frame {phase_check['first_contact_frame']} vs frame "
            f"{phase_check['opposite_contact_frame']} lower-body diff "
            f"{phase_check['opposite_contact_pose_diff']:.3f}; expected >= "
            f"{phase_check['min_opposite_contact_pose_diff']:.3f}; {phase_check['reason']})"
        )
        if args.support_warn_only:
            warnings.append(message)
        else:
            errors.append(message)
    if len(frames) >= 3 and center_x_range < args.min_center_range and center_y_range < args.min_center_range:
        warnings.append("body center is nearly static; verify body bob/weight shift visually")

    return {
        "state": state,
        "frames": len(frames),
        "loop": bool(entry.get("loop", True)),
        "ok": not errors,
        "complete": complete,
        "errors": errors,
        "warnings": warnings,
        "semantic_review_required": is_locomotion_state(state, entry),
        "semantic_review": [
            "inspect playback/contact sheet; metric pass is not final approval",
            "frame 1 and the opposite contact frame must show opposite anatomical support/contact legs",
            "pass/down frames must not keep both legs drifting to the same side",
        ]
        if is_locomotion_state(state, entry)
        else [],
        "metrics": {
            "average_lower_body_diff": round(average_diff, 4) if diffs else None,
            "min_lower_body_diff": round(min_diff, 4) if diffs else None,
            "support_balance_range": round(support_range, 4),
            "contact_phase_check": phase_check,
            "threshold_policy": threshold_policy,
            "creature_anatomy": anatomy or None,
            "creature_locomotion": locomotion or None,
            "min_average_lower_diff": min_average_lower_diff,
            "min_pair_lower_diff": min_pair_lower_diff,
            "body_center_x_range": round(center_x_range, 4),
            "body_center_y_range": round(center_y_range, 4),
            "support_balances": [round(value, 4) for value in balances],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--states", default="locomotion", help="'locomotion', 'all', or comma-separated state names")
    parser.add_argument("--report", default="qa/motion-variation-report.json")
    parser.add_argument("--lower-body-start", type=normalized_threshold, default=0.45)
    parser.add_argument("--min-average-lower-diff", type=normalized_threshold, default=0.10)
    parser.add_argument("--min-pair-lower-diff", type=normalized_threshold, default=0.04)
    parser.add_argument("--min-support-range", type=normalized_threshold, default=0.045)
    parser.add_argument("--min-contact-balance-abs", type=normalized_threshold, default=0.012)
    parser.add_argument("--min-contact-opposition", type=normalized_threshold, default=0.035)
    parser.add_argument("--min-opposite-contact-pose-diff", type=normalized_threshold, default=0.08)
    parser.add_argument("--min-center-range", type=normalized_threshold, default=0.015)
    parser.add_argument(
        "--support-warn-only",
        action="store_true",
        help="report the selected contact-silhouette failure as a warning; other motion failures still apply",
    )
    parser.add_argument("--warn-only", action="store_true")
    args = parser.parse_args()

    run_dir = args.run_dir.expanduser().resolve()
    request = load_json(resolve_run_path(run_dir, "sprite-request.json"), {})
    if not isinstance(request, dict) or not request:
        raise ValueError("sprite request must be a non-empty JSON object")
    request_states = request.get("states")
    if not isinstance(request_states, dict) or any(not isinstance(value, dict) for value in request_states.values()):
        raise ValueError("request states must be an object of state entries")
    creature_motion = request.get("creature_motion")
    shared_idle = bool(
        isinstance(creature_motion, dict) and creature_motion.get("shared_idle")
    )
    frames_manifest = load_json(resolve_run_path(run_dir, "frames/frames-manifest.json"), {})
    art_direction = load_json(resolve_run_path(run_dir, "references/art-direction.json"), {})
    if not isinstance(frames_manifest, dict) or not isinstance(art_direction, dict):
        raise ValueError("frames manifest and art direction must be JSON objects")
    if frames_manifest.get("ok") is not True:
        raise SystemExit("frames-manifest.json is not ok; fix extraction before motion QA")
    rows_by_state = frame_rows_by_state(frames_manifest)
    report_path = report_output_path(run_dir, args.report, rows_by_state)

    results = []
    contract_errors = []
    heuristic_errors = []
    warnings = []
    try:
        states = selected_states(request, args.states, art_direction)
    except ValueError as exc:
        states = []
        contract_errors.append(str(exc))
    for state in states:
        if state not in request_states:
            contract_errors.append(f"unknown state: {state}")
            continue
        if state not in rows_by_state:
            contract_errors.append(f"missing extracted frames for state: {state}")
            continue
        entry = request_states[state]
        row = rows_by_state[state]
        try:
            frames = load_frames(run_dir, row, entry.get("frames"))
            workflows, _source = workflows_for_state(request, art_direction, state, entry)
        except (OSError, ValueError) as exc:
            contract_errors.append(f"{state}: {exc}")
            continue
        entry = {**entry, "animation_workflows": workflows}
        result = inspect_state(
            state,
            entry,
            frames,
            args,
            shared_idle=shared_idle,
            creature_motion=creature_motion if isinstance(creature_motion, dict) else None,
        )
        results.append(result)
        if not result["complete"]:
            contract_errors.append(f"{state}: required motion analysis is incomplete")
        heuristic_errors.extend(f"{state}: {error}" for error in result["errors"])
        warnings.extend(f"{state}: {warning}" for warning in result["warnings"])

    if args.states == "locomotion" and not results:
        contract_errors.append("no locomotion states matched; nothing checked")
    elif not results and not contract_errors:
        contract_errors.append("no states were checked; nothing checked")

    errors = [*contract_errors, *heuristic_errors]
    ok = not contract_errors and (not heuristic_errors or args.warn_only)
    report = {
        "ok": ok,
        "complete": not contract_errors,
        "engine": "motion-variation-heuristic",
        "run_dir": str(run_dir),
        "states_mode": args.states,
        "checked_states": [result["state"] for result in results],
        "semantic_review_required": any(result.get("semantic_review_required") for result in results),
        "quality_gate_note": (
            "Motion variation is a heuristic. Locomotion still needs visual leg-phase review before final approval."
        ),
        "errors": errors,
        "warnings": warnings,
        "results": results,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(report_path, json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "results"}, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        print(json.dumps({"ok": False, "status": "operational-error", "errors": [str(exc)]}))
        raise SystemExit(3)
