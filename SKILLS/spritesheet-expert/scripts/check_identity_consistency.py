#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check recorded silhouette ratios against configured identity-proxy limits.

These extraction records do not prove current pixel identity or anatomy.
Use current contact, onion, and runtime evidence for visual acceptance.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from statistics import median
import sys
from typing import Any

from check_animation_contracts import frame_rows_by_state, report_output_path
from runio import atomic_write_text
from spritecore.paths import resolve_run_path
from spritecore.visual_review import compute_input_fingerprint, snapshot_review_artifact


IDENTITY_KEYS = (
    "head_width_vs_reference",
    "upper_width_vs_reference",
    "body_mass_width_80_vs_reference",
    "opaque_area_vs_reference",
)
IDENTITY_PROXY_REVIEW = "qa/identity-proxy-review.json"
IDENTITY_PROXY_REVIEW_KIND = "identity-proxy-visual-review"


def identity_review_paths(request: dict[str, Any], states: list[str]) -> list[str]:
    background = request.get("background_removal") or {}
    if not isinstance(background, dict):
        raise ValueError("background_removal must be an object")
    removal = background.get("method")
    return [
        "sprite-request.json",
        "frames/frames-manifest.json",
        "sprite-sheet-alpha.png",
        *([] if removal == "none" else ["qa/background-matte-review.png"]),
        *[f"qa/{state}-contact.png" for state in states],
        *[f"qa/{state}-onion.png" for state in states],
    ]


def apply_identity_proxy_review(
    run_dir: Path,
    results: list[dict[str, Any]],
    quality_errors: list[str],
    request: dict[str, Any],
) -> tuple[list[str], list[str], dict[str, Any] | None]:
    review_path = run_dir / IDENTITY_PROXY_REVIEW
    if not review_path.is_file() or not quality_errors:
        return quality_errors, [], None
    review = load_json(review_path)
    issues: list[str] = []
    if review.get("version") != 1:
        issues.append("version must be 1")
    if review.get("kind") != IDENTITY_PROXY_REVIEW_KIND:
        issues.append(f"kind must be {IDENTITY_PROXY_REVIEW_KIND!r}")
    if review.get("status") != "approved":
        issues.append("status must be 'approved'")
    if review.get("reviewer_kind") not in {"human", "vision-model"}:
        issues.append("reviewer_kind must be 'human' or 'vision-model'")
    if not isinstance(review.get("reason"), str) or len(review["reason"].strip()) < 20:
        issues.append("reason must explain the proxy false positive")
    covered = review.get("covered_errors")
    if covered != quality_errors:
        issues.append("covered_errors no longer match the current identity proxy failures")
    declared_artifacts = review.get("reviewed_artifacts")
    if not isinstance(declared_artifacts, list) or not declared_artifacts:
        issues.append("reviewed_artifacts must be a non-empty list")
        declared_artifacts = []
    actual_artifacts: list[dict[str, Any]] = []
    for index, declared in enumerate(declared_artifacts):
        if not isinstance(declared, dict) or not isinstance(declared.get("path"), str):
            issues.append(f"reviewed_artifacts.{index} is invalid")
            continue
        try:
            actual = snapshot_review_artifact(run_dir, declared["path"])
        except Exception as exc:  # safe path and missing-file errors become review failures
            issues.append(f"reviewed_artifacts.{index}: {exc}")
            continue
        actual_artifacts.append(actual)
        if declared != actual:
            issues.append(f"reviewed_artifacts.{index}: artifact changed")
    affected_states = sorted({error.split(":", 1)[0] for error in quality_errors})
    required_paths = set(identity_review_paths(request, affected_states))
    actual_paths = {artifact["path"] for artifact in actual_artifacts}
    missing = sorted(required_paths - actual_paths)
    if missing:
        issues.append(f"reviewed_artifacts missing required evidence: {', '.join(missing)}")
    if actual_artifacts:
        fingerprint = compute_input_fingerprint(actual_artifacts)
        if review.get("input_fingerprint") != fingerprint:
            issues.append("input_fingerprint no longer matches reviewed artifacts")
    if issues:
        return [
            *quality_errors,
            *[f"identity proxy review invalid: {issue}" for issue in issues],
        ], [], None

    covered_set = set(quality_errors)
    for row in results:
        state = str(row.get("state", ""))
        row_errors = [f"{state}: {error}" for error in row.get("errors", [])]
        if not row["input_errors"] and row_errors and set(row_errors) <= covered_set:
            row["warnings"].extend(
                f"visually reviewed proxy false positive: {error}" for error in row["errors"]
            )
            row["errors"] = []
            row["ok"] = True
            row["proxy_review"] = IDENTITY_PROXY_REVIEW
    warnings = [
        f"identity proxy visual review accepted {len(quality_errors)} exact metric failure(s)"
    ]
    return [], warnings, {
        "path": IDENTITY_PROXY_REVIEW,
        "input_fingerprint": review["input_fingerprint"],
        "covered_errors": quality_errors,
    }


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    return data if isinstance(data, dict) else {}


def row_kind(row: dict[str, Any]) -> str:
    geometry = row.get("pose_geometry")
    if isinstance(geometry, dict):
        return str(geometry.get("kind", ""))
    return ""


def metric_values(records: list[dict[str, Any]], key: str) -> list[float]:
    values: list[float] = []
    for record in records:
        value = record.get(key)
        if value is None:
            continue
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError(f"{key} must be a finite non-negative number")
        values.append(float(value))
    return values


def non_negative_ratio(raw: str) -> float:
    value = float(raw)
    if not math.isfinite(value) or value < 0:
        raise argparse.ArgumentTypeError("ratio must be finite and non-negative")
    return value


def allowed_floor(key: str, kind: str, args: argparse.Namespace) -> float:
    if key == "head_width_vs_reference":
        if kind in {"knockdown", "fall"}:
            return args.min_knockdown_head
        if kind == "airborne":
            return args.min_airborne_head
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
    registration_policy = (request or {}).get("registration")
    if isinstance(motion, dict) and isinstance(registration_policy, dict):
        anatomy = str(motion.get("anatomy", "")).lower()
        locomotion = str(motion.get("locomotion", "")).lower()
        if (
            registration_policy.get("scale_policy") == "source-reference"
            and (anatomy in {"winged", "flying"} or locomotion in {"fly", "flight"})
        ):
            # A true flap deliberately moves the wings through the upper and
            # central silhouette bands. With source-reference scaling the body
            # scale is already fixed, so these width bands measure wing pose,
            # not identity drift. Keep area/head checks and require visual QA.
            unreliable.update(
                {
                    "upper_width_vs_reference",
                    "body_mass_width_80_vs_reference",
                }
            )
    if isinstance(motion, dict) and str(motion.get("anatomy", "")).lower() in {
        "multi-legged",
        "quadruped",
    }:
        declaration = " ".join(
            str(motion.get(key, "")).lower()
            for key in ("movement_source", "attack_source")
        )
        if "maw" in declaration or "mouth" in declaration:
            # Front-facing spiders, quadrupeds, and similar crawlers do not
            # always have a stable top-band head silhouette: lifted forelegs
            # and head foreshortening cross that band while the actual identity
            # anchor is the central maw and body mass.
            unreliable.add("head_width_vs_reference")
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
    if isinstance(motion, dict) and str(motion.get("anatomy", "")).lower() == "amorphous":
        attack_source = str(motion.get("attack_source", "")).lower()
        if "maw" in attack_source or "mouth" in attack_source:
            # A headless amorphous creature can attack by opening its declared
            # central mouth. The top-band proxy then measures the attack pose,
            # not a head-size change. Body mass, area, registration, and visual
            # review continue to guard identity and scale.
            unreliable.add("head_width_vs_reference")
    if isinstance(motion, dict) and str(motion.get("anatomy", "")).lower() == "biped":
        movement_source = str(motion.get("movement_source", "")).lower()
        attack_source = str(motion.get("attack_source", "")).lower()
        long_asymmetric_arm = any(
            token in movement_source
            for token in (
                "long-arm counter-swing",
                "long arm counter-swing",
                "extra-long",
                "extra long",
                "asymmetric arm",
                "asymmetrical arm",
            )
        )
        long_arm_attack = any(
            token in attack_source
            for token in (
                "extra-long",
                "extra long",
                "long claw",
                "long arm",
                "elongated",
                "asymmetric arm",
                "asymmetrical arm",
            )
        )
        if long_asymmetric_arm:
            # Counter-swing crosses the upper silhouette band. Keep the head
            # proxy active unless the attack contract also drives a declared
            # long arm through that narrow top band.
            unreliable.add("upper_width_vs_reference")
            if long_arm_attack:
                unreliable.add("head_width_vs_reference")
        bilateral_long_arm_attack = (
            "both" in attack_source
            and any(token in attack_source for token in ("elongated", "long arm"))
            and any(
                token in attack_source
                for token in ("bilateral", "inward", "cross", "x-shaped", "x shaped")
            )
        )
        if bilateral_long_arm_attack:
            # A declared two-arm inward/crossing strike moves both elbows and
            # hands through the upper band. Head, body mass, area, baseline,
            # and visual review remain reliable identity/scale guards.
            unreliable.add("upper_width_vs_reference")
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
            "limb",
            "pincer",
            "scythe",
            "hook",
            "gauntlet",
            "fist",
        )
    )


def is_head_driven_attack(request: dict[str, Any], state: str) -> bool:
    if state != "attack":
        return False
    creature_motion = request.get("creature_motion")
    if not isinstance(creature_motion, dict):
        return False
    attack_source = str(creature_motion.get("attack_source", "")).lower()
    return any(token in attack_source for token in ("head", "mouth", "maw", "jaw", "tusk"))


def is_airborne_motion(request: dict[str, Any], state: str) -> bool:
    if state != "idle-step":
        return False
    creature_motion = request.get("creature_motion")
    if not isinstance(creature_motion, dict):
        return False
    anatomy = str(creature_motion.get("anatomy", "")).lower()
    locomotion = str(creature_motion.get("locomotion", "")).lower()
    return anatomy in {"hovering", "flying"} or locomotion in {"hover", "fly", "flight"}


def inspect_row(
    row: dict[str, Any],
    args: argparse.Namespace,
    unreliable_proxies: set[str] | None = None,
    *,
    appendage_driven_attack: bool = False,
    head_driven_attack: bool = False,
    airborne_motion: bool = False,
) -> dict[str, Any]:
    state = str(row.get("state", ""))
    records = row.get("frame_records") if isinstance(row.get("frame_records"), list) else []
    kind = row_kind(row)
    errors: list[str] = []
    input_errors: list[str] = []
    warnings: list[str] = []
    metrics: dict[str, Any] = {}
    missing_proxies = False
    unreliable_proxies = unreliable_proxies or set()

    for key in IDENTITY_KEYS:
        values = metric_values(records, key)
        if len(values) != len(records) or not records:
            missing_proxies = True
            message = f"{key} missing for {len(records) - len(values)} frame record(s); identity proxy unavailable"
            if args.allow_missing_proxies:
                warnings.append(message + "; diagnostic output is incomplete")
            else:
                input_errors.append(message)
        if not values:
            continue
        minimum = min(values)
        maximum = max(values)
        med = median(values)
        spread = maximum - minimum
        floor = allowed_floor(key, kind, args)
        ceiling = allowed_ceiling(key, kind, args)
        if key == "head_width_vs_reference" and airborne_motion:
            floor = args.min_airborne_head
        if key == "head_width_vs_reference" and head_driven_attack:
            floor = args.min_head_attack
            ceiling = args.max_head_attack
        if (
            key == "head_width_vs_reference"
            and appendage_driven_attack
            and not head_driven_attack
        ):
            floor = args.min_appendage_attack_head
            ceiling = args.max_appendage_attack_head
        if key == "upper_width_vs_reference" and appendage_driven_attack:
            ceiling = args.max_appendage_attack_upper_width
        if key == "body_mass_width_80_vs_reference" and appendage_driven_attack:
            floor = args.min_appendage_attack_body_mass_width
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
                f"{key} is excluded by the reference or declared-pose policy; visual review required"
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
        if key == "head_width_vs_reference" and head_driven_attack:
            spread_limit = args.max_head_attack_spread
            metrics[key]["spread_policy"] = "declared-head-attack"
        if (
            key == "head_width_vs_reference"
            and appendage_driven_attack
            and not head_driven_attack
        ):
            spread_limit = args.max_appendage_attack_head_spread
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
        "ok": not errors and not input_errors,
        "complete": not input_errors and not missing_proxies,
        "metrics": metrics,
        "input_errors": input_errors,
        "errors": [*input_errors, *errors],
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--states", default="all", help="'all' or comma-separated states")
    parser.add_argument("--report", default="qa/identity-consistency-report.json")
    parser.add_argument("--min-head", type=non_negative_ratio, default=0.82)
    parser.add_argument(
        "--min-airborne-head",
        type=non_negative_ratio,
        default=0.80,
        help="Head-width floor for airborne rows where independently moving shrouds or wings can perturb the top-band proxy; visual identity review remains required.",
    )
    parser.add_argument(
        "--min-head-attack",
        type=non_negative_ratio,
        default=0.75,
        help="Head-width floor for an attack explicitly driven by the head, mouth, maw, jaw, or tusks; visual identity review remains required.",
    )
    parser.add_argument("--max-head", type=non_negative_ratio, default=1.28)
    parser.add_argument(
        "--max-head-attack",
        type=non_negative_ratio,
        default=1.40,
        help="Head-width ceiling for an attack explicitly driven by the head, mouth, maw, jaw, or tusks; visual identity review remains required.",
    )
    parser.add_argument("--min-upper", type=non_negative_ratio, default=0.62)
    parser.add_argument("--max-upper", type=non_negative_ratio, default=1.55)
    parser.add_argument("--min-body-mass-width", type=non_negative_ratio, default=0.68)
    parser.add_argument("--max-body-mass-width", type=non_negative_ratio, default=1.65)
    parser.add_argument("--min-area", type=non_negative_ratio, default=0.58)
    parser.add_argument("--max-area", type=non_negative_ratio, default=1.55)
    parser.add_argument("--min-jump-upper", type=non_negative_ratio, default=0.72)
    parser.add_argument("--min-pose-area", type=non_negative_ratio, default=0.45)
    parser.add_argument("--min-knockdown-head", type=non_negative_ratio, default=0.55)
    parser.add_argument("--min-knockdown-upper", type=non_negative_ratio, default=0.58)
    parser.add_argument("--min-knockdown-body-mass-width", type=non_negative_ratio, default=0.50)
    parser.add_argument("--max-proxy-spread", type=non_negative_ratio, default=0.42)
    parser.add_argument(
        "--max-head-attack-spread",
        type=non_negative_ratio,
        default=0.60,
        help="Head-width spread allowed only for a declared head-driven attack; other rows keep --max-proxy-spread.",
    )
    parser.add_argument(
        "--max-arm-attack-upper-spread",
        type=non_negative_ratio,
        default=0.95,
        help="Upper-width spread allowed only for an attack whose request explicitly declares a moving appendage as its attack source.",
    )
    parser.add_argument(
        "--max-appendage-attack-upper-width",
        type=non_negative_ratio,
        default=1.85,
        help="Upper-width ceiling for a declared appendage-driven attack; head and area proxies remain independently gated.",
    )
    parser.add_argument(
        "--min-appendage-attack-head",
        type=non_negative_ratio,
        default=0.40,
        help="Head-band floor for an appendage attack where raised hands, claws, or wings can become the topmost silhouette; visual head review remains required.",
    )
    parser.add_argument(
        "--max-appendage-attack-head",
        type=non_negative_ratio,
        default=2.20,
        help="Head-band ceiling for an appendage attack where raised or crossed limbs can become the topmost silhouette; visual head review remains required.",
    )
    parser.add_argument(
        "--max-appendage-attack-head-spread",
        type=non_negative_ratio,
        default=1.30,
        help="Head-band spread for an appendage attack where the moving appendage crosses the topmost silhouette; visual head review remains required.",
    )
    parser.add_argument(
        "--min-appendage-attack-body-mass-width",
        type=non_negative_ratio,
        default=0.50,
        help="Body-mass width floor for a declared appendage-driven attack where forward foreshortening can narrow the silhouette; visual review remains required.",
    )
    parser.add_argument(
        "--max-appendage-attack-body-mass-width",
        type=non_negative_ratio,
        default=1.85,
        help="Body-mass width ceiling for a declared appendage-driven attack; visual identity review remains required.",
    )
    parser.add_argument(
        "--max-appendage-attack-body-mass-spread",
        type=non_negative_ratio,
        default=0.85,
        help="Body-mass width spread for a declared appendage-driven attack; other rows keep --max-body-mass-spread.",
    )
    parser.add_argument(
        "--max-body-mass-spread",
        type=non_negative_ratio,
        default=0.60,
        help="Wider pose-aware spread for the 80%% body-mass proxy; head/upper-body keep --max-proxy-spread.",
    )
    parser.add_argument("--allow-missing-proxies", action="store_true", help="Keep available metrics as diagnostics; missing proxies still mark the report incomplete.")
    parser.add_argument("--warn-only", action="store_true")
    args = parser.parse_args()

    run_dir = args.run_dir.expanduser().resolve()
    manifest_path = resolve_run_path(run_dir, "frames/frames-manifest.json")
    request_path = resolve_run_path(run_dir, "sprite-request.json")
    manifest = load_json(manifest_path)
    request = load_json(request_path)
    precondition_errors: list[str] = []
    if not request_path.is_file() or not request:
        precondition_errors.append("sprite-request.json is missing or invalid")
    if not manifest_path.is_file() or not manifest:
        precondition_errors.append("frames/frames-manifest.json is missing or invalid")
    elif manifest.get("ok") is not True:
        precondition_errors.append("frames/frames-manifest.json is not ok")
    rows_by_state = frame_rows_by_state(manifest)
    rows = list(rows_by_state.values())
    request_states = request.get("states") if isinstance(request.get("states"), dict) else {}
    available_states = set(rows_by_state)
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
        row for row in rows if row["state"] in expected_states
    ]
    if not selected:
        precondition_errors.append("zero expected rows were checked")
    report_path = report_output_path(run_dir, args.report, rows_by_state)
    protected = {
        resolve_run_path(run_dir, relative) for relative in [
            IDENTITY_PROXY_REVIEW, *identity_review_paths(request, sorted(expected_states))
        ]
    }
    if report_path in protected:
        raise ValueError("report output cannot overwrite identity review evidence")
    for row in selected:
        state = row["state"]
        entry = request_states.get(state)
        expected = entry.get("frames") if isinstance(entry, dict) else None
        records = row.get("frame_records")
        if type(expected) is not int or expected <= 0:
            precondition_errors.append(f"{state}: requested frames must be a positive integer")
        if not isinstance(records, list) or any(not isinstance(record, dict) for record in records):
            raise ValueError(f"{state}: frame_records must be an array of objects")
        if len(records) != expected:
            precondition_errors.append(f"{state}: expected {expected} frame records; found {len(records)}")
        if "frames" in row and (type(row["frames"]) is not int or row["frames"] != expected):
            precondition_errors.append(f"{state}: extracted frame count differs from request")
        if "files" in row and len(row["files"]) != expected:
            precondition_errors.append(f"{state}: extracted file count differs from request")
    registration = manifest.get("sprite_registration")
    if isinstance(registration, dict):
        for key in ("reference_head_width", "reference_upper_width", "reference_body_mass_width_80"):
            value = registration.get(key)
            if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value < 0):
                raise ValueError(f"sprite_registration.{key} must be a finite non-negative number")
    unreliable_proxies = unreliable_identity_proxies(manifest, request)
    results = [
        inspect_row(
            row,
            args,
            unreliable_proxies,
            appendage_driven_attack=is_appendage_driven_attack(
                request, str(row.get("state", ""))
            ),
            head_driven_attack=is_head_driven_attack(
                request, str(row.get("state", ""))
            ),
            airborne_motion=is_airborne_motion(
                request, str(row.get("state", ""))
            ),
        )
        for row in selected
    ]
    precondition_errors.extend(f"{row['state']}: {error}" for row in results for error in row["input_errors"])
    quality_errors = [f"{row['state']}: {error}" for row in results for error in row["errors"] if error not in row["input_errors"]]
    review_warnings: list[str] = []
    proxy_review = None
    if not precondition_errors:
        quality_errors, review_warnings, proxy_review = apply_identity_proxy_review(
            run_dir, results, quality_errors, request
        )
    errors = precondition_errors + quality_errors
    warnings = [f"{row['state']}: {warning}" for row in results for warning in row["warnings"]]
    warnings.extend(review_warnings)
    payload = {
        "ok": not precondition_errors and (not quality_errors or args.warn_only),
        "complete": not precondition_errors and all(row["complete"] for row in results),
        "engine": "identity-consistency-proxy",
        "run_dir": str(run_dir),
        "states_mode": args.states,
        "quality_gate_note": "These recorded silhouette ratios are proxies, not current-pixel or anatomical proof. Require complete evidence and visual contact/onion/runtime review for identity acceptance.",
        "unreliable_proxies": sorted(unreliable_proxies),
        "errors": errors,
        "warnings": warnings,
        "results": results,
    }
    if proxy_review is not None:
        payload["identity_proxy_review"] = proxy_review
    report_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(report_path, json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    print(json.dumps({key: value for key, value in payload.items() if key != "results"}, indent=2, ensure_ascii=False, allow_nan=False))
    if precondition_errors or (quality_errors and not args.warn_only):
        return 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, TypeError) as exc:
        print(str(exc), file=sys.stderr)
        print(json.dumps({"ok": False, "complete": False, "status": "operational-error", "errors": [str(exc)]}))
        raise SystemExit(3)
