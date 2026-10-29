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
from pathlib import Path
from typing import Any

from PIL import Image

from runio import atomic_write_text


LOCOMOTION_RE = re.compile(r"(^|-)(walk|walking|run|running|move)(-|$)")


def is_locomotion_state(state: str, entry: dict[str, Any]) -> bool:
    action = str(entry.get("action", "")).lower()
    workflows = entry.get("animation_workflows", [])
    workflow_text = " ".join(str(item) for item in workflows) if isinstance(workflows, list) else str(workflows)
    if workflow_text.strip():
        return "locomotion" in workflow_text.lower()
    text = f"{state} {action} {workflow_text}".lower()
    tokens = {token for token in re.split(r"[^a-z0-9]+", text) if token}
    return bool(
        LOCOMOTION_RE.search(state.lower())
        or tokens & {"walk", "walking", "run", "running", "move", "moving", "advance", "retreat", "dash", "dashing"}
    )


def selected_states(request: dict[str, Any], mode: str) -> list[str]:
    states = request.get("states", {})
    if mode == "all":
        return list(states)
    if mode == "locomotion":
        return [state for state, entry in states.items() if is_locomotion_state(state, entry)]
    return [state.strip() for state in mode.split(",") if state.strip()]


def load_frames(run_dir: Path, row: dict[str, Any]) -> list[Image.Image]:
    frames = []
    for rel in row.get("files", []):
        with Image.open(run_dir / rel) as opened:
            frames.append(opened.convert("RGBA"))
    return frames


def alpha_bbox(frame: Image.Image, threshold: int = 16) -> tuple[int, int, int, int] | None:
    return frame.getchannel("A").point(lambda value: 255 if value > threshold else 0).getbbox()


def lower_mask_diff(left: Image.Image, right: Image.Image, y_ratio: float) -> float:
    width, height = left.size
    if right.size != left.size:
        return 1.0
    y_start = max(0, min(height - 1, round(height * y_ratio)))
    xor = 0
    union = 0
    left_alpha = left.getchannel("A")
    right_alpha = right.getchannel("A")
    for y in range(y_start, height):
        for x in range(width):
            a = left_alpha.getpixel((x, y)) > 16
            b = right_alpha.getpixel((x, y)) > 16
            if a or b:
                union += 1
                if a != b:
                    xor += 1
    return xor / union if union else 0.0


def support_balance(frame: Image.Image) -> float:
    bbox = alpha_bbox(frame)
    if not bbox:
        return 0.0
    x0, y0, x1, y1 = bbox
    width = max(1, x1 - x0)
    center_x = (x0 + x1) / 2
    y_start = y0 + round((y1 - y0) * 0.68)
    total = 0
    weighted = 0.0
    alpha = frame.getchannel("A")
    for y in range(y_start, y1):
        for x in range(x0, x1):
            if alpha.getpixel((x, y)) > 16:
                total += 1
                weighted += (x - center_x) / width
    return weighted / total if total else 0.0


def body_center(frame: Image.Image) -> tuple[float, float]:
    bbox = alpha_bbox(frame)
    if not bbox:
        return 0.0, 0.0
    x0, y0, x1, y1 = bbox
    return (x0 + x1) / (2 * frame.width), (y0 + y1) / (2 * frame.height)


def support_side(value: float, threshold: float) -> str:
    if value <= -threshold:
        return "left"
    if value >= threshold:
        return "right"
    return "center/ambiguous"


def contact_phase_check(
    frames: list[Image.Image],
    args: argparse.Namespace,
    *,
    shared_idle: bool = False,
    min_pose_diff: float | None = None,
) -> dict[str, Any] | None:
    if len(frames) < 4:
        return None
    balances = [support_balance(frame) for frame in frames]
    first_index = 1 if shared_idle and len(frames) == 4 else 0
    opposite_index = 3 if shared_idle and len(frames) == 4 else (
        len(frames) // 2 if len(frames) >= 6 else 2
    )
    first = balances[first_index]
    opposite = balances[opposite_index]
    first_side = support_side(first, args.min_contact_balance_abs)
    opposite_side = support_side(opposite, args.min_contact_balance_abs)
    contact_delta = abs(opposite - first)
    contact_pose_diff = lower_mask_diff(
        frames[first_index], frames[opposite_index], args.lower_body_start
    )
    effective_min_pose_diff = (
        args.min_opposite_contact_pose_diff if min_pose_diff is None else min_pose_diff
    )
    ok = contact_pose_diff >= effective_min_pose_diff
    reason = "distinct opposite-contact lower-body poses"
    if not ok:
        reason = "opposite contact lower-body pose is duplicated or too similar"
    return {
        "ok": ok,
        "phase_layout": "idle-phase-a-idle-phase-b" if first_index == 1 else "standard-contact-cycle",
        "first_contact_index": first_index,
        "first_contact_frame": first_index + 1,
        "opposite_contact_index": opposite_index,
        "opposite_contact_frame": opposite_index + 1,
        "frame_1_support_balance": round(first, 4),
        "frame_1_support_side": first_side,
        "opposite_contact_support_balance": round(opposite, 4),
        "opposite_contact_support_side": opposite_side,
        "contact_delta": round(contact_delta, 4),
        "opposite_contact_pose_diff": round(contact_pose_diff, 4),
        "min_opposite_contact_pose_diff": effective_min_pose_diff,
        "min_contact_balance_abs": args.min_contact_balance_abs,
        "min_contact_opposition": args.min_contact_opposition,
        "screen_side_is_diagnostic_only": True,
        "anatomical_leg_alternation_requires_visual_review": True,
        "reason": reason,
    }


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
    pairs = len(frames) if entry.get("loop", True) and len(frames) > 2 else max(0, len(frames) - 1)

    for index in range(pairs):
        left = frames[index]
        right = frames[(index + 1) % len(frames)]
        diffs.append(lower_mask_diff(left, right, args.lower_body_start))

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
            "average_lower_body_diff": round(average_diff, 4),
            "min_lower_body_diff": round(min_diff, 4),
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
    parser.add_argument("--lower-body-start", type=float, default=0.45)
    parser.add_argument("--min-average-lower-diff", type=float, default=0.10)
    parser.add_argument("--min-pair-lower-diff", type=float, default=0.04)
    parser.add_argument("--min-support-range", type=float, default=0.045)
    parser.add_argument("--min-contact-balance-abs", type=float, default=0.012)
    parser.add_argument("--min-contact-opposition", type=float, default=0.035)
    parser.add_argument("--min-opposite-contact-pose-diff", type=float, default=0.08)
    parser.add_argument("--min-center-range", type=float, default=0.015)
    parser.add_argument(
        "--support-warn-only",
        action="store_true",
        help="deprecated compatibility flag; screen-space balance is always diagnostic-only",
    )
    parser.add_argument("--warn-only", action="store_true")
    args = parser.parse_args()

    run_dir = args.run_dir.expanduser().resolve()
    request = json.loads((run_dir / "sprite-request.json").read_text(encoding="utf-8"))
    creature_motion = request.get("creature_motion")
    shared_idle = bool(
        isinstance(creature_motion, dict) and creature_motion.get("shared_idle")
    )
    frames_manifest = json.loads((run_dir / "frames" / "frames-manifest.json").read_text(encoding="utf-8"))
    if not frames_manifest.get("ok"):
        raise SystemExit("frames-manifest.json is not ok; fix extraction before motion QA")
    rows_by_state = {row["state"]: row for row in frames_manifest.get("rows", [])}
    states = selected_states(request, args.states)

    results = []
    contract_errors = []
    heuristic_errors = []
    warnings = []
    for state in states:
        if state not in request.get("states", {}):
            contract_errors.append(f"unknown state: {state}")
            continue
        if state not in rows_by_state:
            contract_errors.append(f"missing extracted frames for state: {state}")
            continue
        entry = request["states"][state]
        row = rows_by_state[state]
        files = row.get("files", [])
        expected_frames = entry.get("frames")
        if not isinstance(files, list):
            contract_errors.append(f"{state}: frames-manifest files must be a list")
            continue
        if (
            isinstance(expected_frames, bool)
            or not isinstance(expected_frames, int)
            or expected_frames < 1
        ):
            contract_errors.append(f"{state}: request frames must be a positive integer")
            continue
        if len(files) != expected_frames:
            contract_errors.append(
                f"{state}: expected {expected_frames} frames, found {len(files)}"
            )
            continue
        result = inspect_state(
            state,
            entry,
            load_frames(run_dir, row),
            args,
            shared_idle=shared_idle,
            creature_motion=creature_motion if isinstance(creature_motion, dict) else None,
        )
        results.append(result)
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
    report_path = run_dir / args.report
    report_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(report_path, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "results"}, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
