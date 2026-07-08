#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Gate sprite rows on identity/volume consistency.

Frame extraction already records head/upper-body proxies. This script turns
those records into an explicit production gate so head size, upper-body mass,
and overall volume drift cannot hide behind otherwise passing animation QA.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import median
from typing import Any

from runio import atomic_write_text


IDENTITY_KEYS = (
    "head_width_vs_reference",
    "upper_width_vs_reference",
    "body_mass_width_80_vs_reference",
    "opaque_area_vs_reference",
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


def row_kind(row: dict[str, Any]) -> str:
    geometry = row.get("pose_geometry")
    if isinstance(geometry, dict):
        return str(geometry.get("kind", ""))
    return ""


def metric_values(records: list[dict[str, Any]], key: str) -> list[float]:
    values: list[float] = []
    for record in records:
        value = record.get(key)
        if isinstance(value, (int, float)):
            values.append(float(value))
    return values


def allowed_floor(key: str, kind: str, args: argparse.Namespace) -> float:
    if key == "head_width_vs_reference":
        if kind in {"knockdown", "fall"}:
            return args.min_knockdown_head
        return args.min_head
    if key == "upper_width_vs_reference":
        if kind == "jump":
            return args.min_jump_upper
        if kind in {"knockdown", "fall"}:
            return args.min_knockdown_upper
        return args.min_upper
    if key == "body_mass_width_80_vs_reference":
        if kind in {"knockdown", "fall"}:
            return args.min_knockdown_body_mass_width
        return args.min_body_mass_width
    if key == "opaque_area_vs_reference":
        if kind in {"crouch", "jump", "knockdown", "fall"}:
            return args.min_pose_area
        return args.min_area
    return 0.0


def allowed_ceiling(key: str, kind: str, args: argparse.Namespace) -> float:
    if key == "opaque_area_vs_reference":
        return args.max_area
    if key == "head_width_vs_reference":
        return args.max_head
    if key == "upper_width_vs_reference":
        return args.max_upper
    if key == "body_mass_width_80_vs_reference":
        return args.max_body_mass_width
    return 999.0


def inspect_row(row: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    state = str(row.get("state", ""))
    records = row.get("frame_records") if isinstance(row.get("frame_records"), list) else []
    kind = row_kind(row)
    errors: list[str] = []
    warnings: list[str] = []
    metrics: dict[str, Any] = {}

    for key in IDENTITY_KEYS:
        values = metric_values(records, key)
        if not values:
            message = f"{key} missing; identity proxy unavailable"
            if args.allow_missing_proxies:
                warnings.append(message)
            else:
                errors.append(message)
            continue
        minimum = min(values)
        maximum = max(values)
        med = median(values)
        spread = maximum - minimum
        floor = allowed_floor(key, kind, args)
        ceiling = allowed_ceiling(key, kind, args)
        metrics[key] = {
            "min": round(minimum, 4),
            "median": round(med, 4),
            "max": round(maximum, 4),
            "spread": round(spread, 4),
            "floor": floor,
            "ceiling": ceiling,
        }
        if minimum < floor:
            errors.append(f"{key} shrinks to {minimum:.2f}x reference; expected >= {floor:.2f}x")
        if maximum > ceiling:
            warnings.append(f"{key} grows to {maximum:.2f}x reference; review possible head/body inflation")
        if key != "opaque_area_vs_reference" and spread > args.max_proxy_spread:
            warnings.append(f"{key} varies by {spread:.2f}x across row; review identity wobble")

    return {
        "state": state,
        "kind": kind or "default",
        "ok": not errors,
        "metrics": metrics,
        "errors": errors,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--states", default="all", help="'all' or comma-separated states")
    parser.add_argument("--report", default="qa/identity-consistency-report.json")
    parser.add_argument("--min-head", type=float, default=0.82)
    parser.add_argument("--max-head", type=float, default=1.28)
    parser.add_argument("--min-upper", type=float, default=0.62)
    parser.add_argument("--max-upper", type=float, default=1.55)
    parser.add_argument("--min-body-mass-width", type=float, default=0.68)
    parser.add_argument("--max-body-mass-width", type=float, default=1.65)
    parser.add_argument("--min-area", type=float, default=0.58)
    parser.add_argument("--max-area", type=float, default=1.55)
    parser.add_argument("--min-jump-upper", type=float, default=0.72)
    parser.add_argument("--min-pose-area", type=float, default=0.45)
    parser.add_argument("--min-knockdown-head", type=float, default=0.55)
    parser.add_argument("--min-knockdown-upper", type=float, default=0.58)
    parser.add_argument("--min-knockdown-body-mass-width", type=float, default=0.50)
    parser.add_argument("--max-proxy-spread", type=float, default=0.42)
    parser.add_argument("--allow-missing-proxies", action="store_true")
    parser.add_argument("--warn-only", action="store_true")
    args = parser.parse_args()

    run_dir = args.run_dir.expanduser().resolve()
    manifest = load_json(run_dir / "frames" / "frames-manifest.json")
    rows = manifest.get("rows") if isinstance(manifest.get("rows"), list) else []
    selected = select_rows(rows, args.states)
    results = [inspect_row(row, args) for row in selected]
    errors = [f"{row['state']}: {error}" for row in results for error in row["errors"]]
    warnings = [f"{row['state']}: {warning}" for row in results for warning in row["warnings"]]
    payload = {
        "ok": not errors or args.warn_only,
        "engine": "identity-consistency-proxy",
        "run_dir": str(run_dir),
        "states_mode": args.states,
        "quality_gate_note": "Head/upper/body proxy metrics are guardrails. Visual contact/onion/runtime review still wins when metrics miss a visible drift.",
        "errors": errors,
        "warnings": warnings,
        "results": results,
    }
    report_path = run_dir / args.report
    report_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(report_path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({key: value for key, value in payload.items() if key != "results"}, indent=2, ensure_ascii=False))
    if errors and not args.warn_only:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
