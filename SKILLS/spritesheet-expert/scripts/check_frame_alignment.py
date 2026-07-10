#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check frame registration with onion-skin overlays.

This is a QA pass over extracted runtime frames, not over prompts or raw rows.
It catches the common "looks okay as a contact sheet, jitters in playback"
failure: baseline drift, jump takeoff/landing mismatch, and root/center drift.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from runio import atomic_save_image, atomic_write_text


ONION_COLORS = (
    (239, 68, 68),
    (245, 158, 11),
    (234, 179, 8),
    (34, 197, 94),
    (59, 130, 246),
    (168, 85, 247),
    (236, 72, 153),
    (20, 184, 166),
)


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    return data if isinstance(data, dict) else {}


def select_rows(rows: list[dict[str, Any]], states: str) -> list[dict[str, Any]]:
    if states in {"all", "*"}:
        return rows
    wanted = {state.strip() for state in states.split(",") if state.strip()}
    return [row for row in rows if str(row.get("state", "")) in wanted]


def frame_bbox(frame: Image.Image) -> tuple[int, int, int, int] | None:
    return frame.convert("RGBA").getbbox()


def alpha_center(frame: Image.Image) -> tuple[float, float] | None:
    alpha = frame.convert("RGBA").getchannel("A")
    pixels = alpha.load()
    total = 0
    sum_x = 0
    sum_y = 0
    for y in range(alpha.height):
        for x in range(alpha.width):
            value = pixels[x, y]
            if value <= 16:
                continue
            total += value
            sum_x += x * value
            sum_y += y * value
    if not total:
        return None
    return sum_x / total, sum_y / total


def tinted_mask(frame: Image.Image, color: tuple[int, int, int], opacity: float) -> Image.Image:
    rgba = frame.convert("RGBA")
    alpha = rgba.getchannel("A").point(lambda value: round(value * opacity))
    tint = Image.new("RGBA", rgba.size, (*color, 0))
    tint.putalpha(alpha)
    return tint


def make_onion(
    state: str,
    frames: list[Image.Image],
    bboxes: list[tuple[int, int, int, int] | None],
    centers: list[tuple[float, float] | None],
    baseline_y: int | None,
) -> Image.Image:
    cell_w = max(frame.width for frame in frames)
    cell_h = max(frame.height for frame in frames)
    label_h = 44
    margin = 16
    canvas = Image.new("RGBA", (cell_w + margin * 2, cell_h + label_h + margin * 2), (18, 18, 18, 255))
    draw = ImageDraw.Draw(canvas)
    origin = (margin, label_h + margin)
    draw.text((margin, 10), f"{state} onion skin", fill=(255, 255, 255, 255))
    draw.text((margin, 26), "orange=baseline  cyan=center  colored boxes=frame bboxes", fill=(188, 196, 208, 255))

    for index, frame in enumerate(frames):
        color = ONION_COLORS[index % len(ONION_COLORS)]
        canvas.alpha_composite(tinted_mask(frame, color, 0.30), origin)

    if baseline_y is not None:
        y = origin[1] + baseline_y
        draw.line((origin[0], y, origin[0] + cell_w - 1, y), fill=(245, 158, 11, 255), width=2)
    center_x = origin[0] + cell_w // 2
    draw.line((center_x, origin[1], center_x, origin[1] + cell_h - 1), fill=(34, 211, 238, 160), width=1)

    previous_center: tuple[float, float] | None = None
    for index, bbox in enumerate(bboxes):
        color = ONION_COLORS[index % len(ONION_COLORS)]
        outline = (*color, 210)
        if bbox:
            left, top, right, bottom = bbox
            draw.rectangle(
                (origin[0] + left, origin[1] + top, origin[0] + right - 1, origin[1] + bottom - 1),
                outline=outline,
                width=1,
            )
        center = centers[index]
        if center:
            cx, cy = origin[0] + center[0], origin[1] + center[1]
            draw.ellipse((cx - 2, cy - 2, cx + 2, cy + 2), fill=(*color, 255))
            if previous_center:
                px, py = origin[0] + previous_center[0], origin[1] + previous_center[1]
                draw.line((px, py, cx, cy), fill=(*color, 180), width=1)
            previous_center = center
    return canvas.convert("RGB")


def row_kind(state: str, row: dict[str, Any], request: dict[str, Any]) -> str:
    geometry = row.get("pose_geometry")
    if not isinstance(geometry, dict):
        states = request.get("states") if isinstance(request.get("states"), dict) else {}
        entry = states.get(state) if isinstance(states.get(state), dict) else {}
        geometry = entry.get("pose_geometry") if isinstance(entry.get("pose_geometry"), dict) else {}
    kind = str(geometry.get("kind", "")).strip()
    if kind:
        return kind
    text = f"{state} {row.get('action', '')}".lower()
    if any(token in text for token in ("advance", "retreat", "walk", "run")):
        return "grounded-locomotion"
    if any(token in text for token in ("idle", "block", "crouch")):
        return "grounded"
    return "action"


def inspect_row(
    run_dir: Path,
    qa_dir: Path,
    row: dict[str, Any],
    request: dict[str, Any],
    baseline_y: int | None,
    args: argparse.Namespace,
) -> dict[str, Any]:
    state = str(row.get("state", ""))
    files = [str(item) for item in row.get("files", [])]
    frames = [Image.open(run_dir / rel).convert("RGBA") for rel in files]
    bboxes = [frame_bbox(frame) for frame in frames]
    centers = [alpha_center(frame) for frame in frames]
    kind = row_kind(state, row, request)

    bottom_y = [bbox[3] if bbox else None for bbox in bboxes]
    center_x = [center[0] if center else None for center in centers]
    center_y = [center[1] if center else None for center in centers]
    valid_bottoms = [value for value in bottom_y if isinstance(value, int)]
    valid_center_x = [value for value in center_x if isinstance(value, float)]

    errors: list[str] = []
    warnings: list[str] = []
    if not frames:
        errors.append("no frames to inspect")
    elif baseline_y is None:
        warnings.append("missing shared baseline_y; baseline checks skipped")

    if baseline_y is not None and valid_bottoms:
        grounded_kind = kind in {"grounded", "grounded-locomotion", "crouch", "land"} or state in {"idle", "block"}
        if grounded_kind:
            drift = max(abs(value - baseline_y) for value in valid_bottoms)
            if drift > args.baseline_tolerance_px:
                errors.append(f"grounded baseline drifts by {drift}px")
        elif kind == "jump" and len(valid_bottoms) >= 2:
            takeoff = valid_bottoms[0]
            landing = valid_bottoms[-1]
            takeoff_delta = abs(takeoff - baseline_y)
            landing_delta = abs(landing - baseline_y)
            closure_delta = abs(takeoff - landing)
            arc_range = max(valid_bottoms) - min(valid_bottoms)
            if takeoff_delta > args.baseline_tolerance_px:
                errors.append(f"jump takeoff misses baseline by {takeoff_delta}px")
            if landing_delta > args.baseline_tolerance_px:
                errors.append(f"jump landing misses baseline by {landing_delta}px")
            if closure_delta > args.baseline_tolerance_px:
                errors.append(f"jump takeoff/landing baseline mismatch is {closure_delta}px")
            if arc_range < args.min_jump_arc_px:
                errors.append(f"jump vertical arc is too small ({arc_range}px; target >= {args.min_jump_arc_px}px)")
        elif kind in {"knockdown", "fall"} and valid_bottoms:
            final_delta = abs(valid_bottoms[-1] - baseline_y)
            if final_delta > args.baseline_tolerance_px:
                errors.append(f"{kind} final frame misses ground baseline by {final_delta}px")

    if kind == "jump" and len(valid_center_x) >= 2:
        takeoff_landing_drift = abs(valid_center_x[0] - valid_center_x[-1])
        total_x_range = max(valid_center_x) - min(valid_center_x)
        if takeoff_landing_drift > args.jump_root_tolerance_px:
            errors.append(f"jump takeoff/landing root x mismatch is {takeoff_landing_drift:.1f}px")
        if total_x_range > args.max_jump_x_range_px:
            warnings.append(f"jump root x range is wide ({total_x_range:.1f}px); verify intentional forward/back jump")

    if kind in {"grounded", "crouch"} and len(valid_center_x) >= 2:
        total_x_range = max(valid_center_x) - min(valid_center_x)
        if total_x_range > args.max_stationary_x_range_px:
            warnings.append(f"stationary root x range is wide ({total_x_range:.1f}px)")

    onion = make_onion(state, frames, bboxes, centers, baseline_y)
    onion_path = qa_dir / f"{state}-onion.png"
    atomic_save_image(onion, onion_path)

    return {
        "state": state,
        "kind": kind,
        "ok": not errors,
        "onion": str(onion_path.relative_to(run_dir)),
        "bottom_y": bottom_y,
        "center_x": [round(value, 2) if isinstance(value, float) else None for value in center_x],
        "center_y": [round(value, 2) if isinstance(value, float) else None for value in center_y],
        "baseline_y": baseline_y,
        "errors": errors,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--states", default="all", help="'all' or comma-separated states")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--baseline-tolerance-px", type=int, default=4)
    parser.add_argument("--min-jump-arc-px", type=int, default=18)
    parser.add_argument("--jump-root-tolerance-px", type=int, default=8)
    parser.add_argument("--max-jump-x-range-px", type=int, default=20)
    parser.add_argument("--max-stationary-x-range-px", type=int, default=10)
    parser.add_argument("--warn-only", action="store_true")
    args = parser.parse_args()

    run_dir = args.run_dir.expanduser().resolve()
    manifest_path = run_dir / "frames" / "frames-manifest.json"
    request_path = run_dir / "sprite-request.json"
    manifest = load_json(manifest_path)
    request = load_json(request_path)
    precondition_errors: list[str] = []
    if not request_path.is_file() or not request:
        precondition_errors.append("sprite-request.json is missing or invalid")
    if not manifest_path.is_file() or not manifest:
        precondition_errors.append("frames/frames-manifest.json is missing or invalid")
    elif manifest.get("ok") is not True:
        precondition_errors.append("frames/frames-manifest.json is not ok")
    rows = manifest.get("rows") if isinstance(manifest.get("rows"), list) else []
    request_states = request.get("states") if isinstance(request.get("states"), dict) else {}
    available_states = {
        str(row.get("state")) for row in rows if isinstance(row, dict) and row.get("state")
    }
    if args.states in {"all", "*"}:
        expected_states = set(request_states)
    else:
        expected_states = {state.strip() for state in args.states.split(",") if state.strip()}
        unknown_states = sorted(expected_states - set(request_states))
        if unknown_states:
            precondition_errors.append(
                f"unknown requested states: {', '.join(unknown_states)}"
            )
    missing_states = sorted(expected_states - available_states)
    if missing_states:
        precondition_errors.append(
            f"missing extracted rows for states: {', '.join(missing_states)}"
        )
    selected = [
        row for row in rows if isinstance(row, dict) and row.get("state") in expected_states
    ]
    if not selected:
        precondition_errors.append("zero expected rows were checked")
    registration = manifest.get("sprite_registration") if isinstance(manifest.get("sprite_registration"), dict) else {}
    baseline_raw = registration.get("baseline_y")
    baseline_y = int(baseline_raw) if isinstance(baseline_raw, (int, float)) else None
    qa_dir = run_dir / "qa"
    qa_dir.mkdir(parents=True, exist_ok=True)

    reports = [inspect_row(run_dir, qa_dir, row, request, baseline_y, args) for row in selected]
    quality_errors = [f"{row['state']}: {error}" for row in reports for error in row["errors"]]
    errors = precondition_errors + quality_errors
    warnings = [f"{row['state']}: {warning}" for row in reports for warning in row["warnings"]]
    payload = {
        "ok": not precondition_errors and (not quality_errors or args.warn_only),
        "engine": "frame-alignment-onion-skin",
        "run_dir": str(run_dir),
        "states_mode": args.states,
        "baseline_y": baseline_y,
        "visual_review_required": True,
        "quality_gate_note": "Review each qa/*-onion.png overlay before final approval; automated checks cover baseline/root drift only.",
        "rows": reports,
        "errors": errors,
        "warnings": warnings,
    }
    report_path = args.report or (qa_dir / "frame-alignment-report.json")
    atomic_write_text(report_path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    if precondition_errors or (quality_errors and not args.warn_only):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
