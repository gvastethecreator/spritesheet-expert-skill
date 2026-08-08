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


def unreliable_identity_proxies(
    manifest: dict[str, Any],
    request: dict[str, Any] | None = None,
) -> set[str]:
    registration = manifest.get("sprite_registration")
    if not isinstance(registration, dict):
        return set()
    body_width = registration.get("reference_body_mass_width_80")
    if not isinstance(body_width, (int, float)) or body_width <= 0:
        return set()
    proxies = {
        "head_width_vs_reference": registration.get("reference_head_width"),
        "upper_width_vs_reference": registration.get("reference_upper_width"),
    }
    unreliable = {
        key
        for key, width in proxies.items()
        if isinstance(width, (int, float)) and width / body_width < 0.12
    }
    motion = (request or {}).get("creature_motion")
    if isinstance(motion, dict) and str(motion.get("anatomy", "")).lower() == "hovering":
        declaration = " ".join(
            str(motion.get(key, "")).lower()
            for key in ("movement_source", "attack_source")
        )
        if "jaw pod" in declaration or "colony" in declaration:
            # The top band contains one orbiting pod, not a stable anatomical
            # head. Its width changes as the pod hovers even when the six-part
            # colony identity and overall body mass remain exact.
            unreliable.add("head_width_vs_reference")
    return unreliable


def is_appendage_driven_attack(request: dict[str, Any], state: str) -> bool:
    if state != "attack":
        return False
    creature_motion = request.get("creature_motion")
    if not isinstance(creature_motion, dict):
        return False
    attack_source = str(creature_motion.get("attack_source", "")).lower()
    return any(
        token in attack_source
        for token in (
            "arm",
            "hand",
            "wing",
            "tentacle",
            "mandible",
            "claw",
            "foreleg",
            "front leg",
            "pincer",
            "scythe",
            "hook",
        )
    )


def inspect_row(
    row: dict[str, Any],
    args: argparse.Namespace,
    unreliable_proxies: set[str] | None = None,
    *,
    appendage_driven_attack: bool = False,
) -> dict[str, Any]:
    state = str(row.get("state", ""))
    records = row.get("frame_records") if isinstance(row.get("frame_records"), list) else []
    kind = row_kind(row)
    errors: list[str] = []
    warnings: list[str] = []
    metrics: dict[str, Any] = {}
    unreliable_proxies = unreliable_proxies or set()

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
        if key == "upper_width_vs_reference" and appendage_driven_attack:
            ceiling = args.max_appendage_attack_upper_width
        if key == "body_mass_width_80_vs_reference" and appendage_driven_attack:
            ceiling = args.max_appendage_attack_body_mass_width
        metrics[key] = {
            "min": round(minimum, 4),
            "median": round(med, 4),
            "max": round(maximum, 4),
            "spread": round(spread, 4),
            "floor": floor,
            "ceiling": ceiling,
        }
        if key in unreliable_proxies:
            metrics[key]["reliable"] = False
            warnings.append(
                f"{key} is too narrow in the reference to gate reliably; visual review required"
            )
            continue
        if minimum < floor:
            errors.append(f"{key} shrinks to {minimum:.2f}x reference; expected >= {floor:.2f}x")
        if maximum > ceiling:
            errors.append(f"{key} grows to {maximum:.2f}x reference; expected <= {ceiling:.2f}x")
        spread_limit = (
            args.max_body_mass_spread
            if key == "body_mass_width_80_vs_reference"
            else args.max_proxy_spread
        )
        if key == "upper_width_vs_reference" and appendage_driven_attack:
            spread_limit = args.max_arm_attack_upper_spread
            metrics[key]["spread_policy"] = "declared-appendage-attack"
        if key == "body_mass_width_80_vs_reference" and appendage_driven_attack:
            spread_limit = args.max_appendage_attack_body_mass_spread
            metrics[key]["spread_policy"] = "declared-appendage-attack"
        if key != "opaque_area_vs_reference" and spread > spread_limit:
            errors.append(
                f"{key} varies by {spread:.2f}x across row; "
                f"expected <= {spread_limit:.2f}x"
            )

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
    parser.add_argument(
        "--max-arm-attack-upper-spread",
        type=float,
        default=0.85,
        help="Upper-width spread allowed only for an attack whose request explicitly declares a moving appendage as its attack source.",
    )
    parser.add_argument(
        "--max-appendage-attack-upper-width",
        type=float,
        default=1.85,
        help="Upper-width ceiling for a declared appendage-driven attack; head and area proxies remain independently gated.",
    )
    parser.add_argument(
        "--max-appendage-attack-body-mass-width",
        type=float,
        default=1.85,
        help="Body-mass width ceiling for a declared appendage-driven attack; visual identity review remains required.",
    )
    parser.add_argument(
        "--max-appendage-attack-body-mass-spread",
        type=float,
        default=0.85,
        help="Body-mass width spread for a declared appendage-driven attack; other rows keep --max-body-mass-spread.",
    )
    parser.add_argument(
        "--max-body-mass-spread",
        type=float,
        default=0.60,
        help="Wider pose-aware spread for the 80%% body-mass proxy; head/upper-body keep --max-proxy-spread.",
    )
    parser.add_argument("--allow-missing-proxies", action="store_true")
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
    unreliable_proxies = unreliable_identity_proxies(manifest, request)
    results = [
        inspect_row(
            row,
            args,
            unreliable_proxies,
            appendage_driven_attack=is_appendage_driven_attack(
                request, str(row.get("state", ""))
            ),
        )
        for row in selected
    ]
    quality_errors = [f"{row['state']}: {error}" for row in results for error in row["errors"]]
    errors = precondition_errors + quality_errors
    warnings = [f"{row['state']}: {warning}" for row in results for warning in row["warnings"]]
    payload = {
        "ok": not precondition_errors and (not quality_errors or args.warn_only),
        "engine": "identity-consistency-proxy",
        "run_dir": str(run_dir),
        "states_mode": args.states,
        "quality_gate_note": "Head/upper/body proxy metrics are guardrails. Visual contact/onion/runtime review still wins when metrics miss a visible drift.",
        "unreliable_proxies": sorted(unreliable_proxies),
        "errors": errors,
        "warnings": warnings,
        "results": results,
    }
    report_path = run_dir / args.report
    report_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(report_path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({key: value for key, value in payload.items() if key != "results"}, indent=2, ensure_ascii=False))
    if precondition_errors or (quality_errors and not args.warn_only):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
