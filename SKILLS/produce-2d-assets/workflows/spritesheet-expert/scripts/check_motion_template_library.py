#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Validate coverage, prompts, hashes, and approvals for motion templates."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

REQUIRED_SIGNATURES = {
    ("side", "right"),
    ("front", "center"),
    ("back", "center"),
    ("three-quarter-front", "right"),
    ("three-quarter-back", "right"),
}
REQUIRED_APPROVALS = {
    "exact_eight_poses",
    "correct_phase_order",
    "opposite_contact_legs",
    "cross_lateral_arm_swing",
    "stable_anatomy_and_camera",
    "anatomical_colors_persist",
    "clean_loop_seam",
    "no_forbidden_artifacts",
}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template-root", required=True, type=Path)
    parser.add_argument(
        "--allow-pending",
        action="store_true",
        help="accept internally consistent needs-imagegen slots while still rejecting stale or partial assets",
    )
    args = parser.parse_args()
    root = args.template_root.expanduser().resolve()
    manifest_path = root / "manifest.json"
    manifest: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
    templates = manifest.get("templates")
    if not isinstance(templates, dict):
        raise SystemExit("template manifest must contain a templates object")

    errors: list[str] = []
    results: list[dict[str, Any]] = []
    pending_templates: list[str] = []
    signatures = {
        (str(item.get("view")), str(item.get("facing")))
        for item in templates.values()
        if isinstance(item, dict)
    }
    for signature in sorted(REQUIRED_SIGNATURES - signatures):
        errors.append(f"missing required template view: {signature[0]}/{signature[1]}")

    for template_id, template in templates.items():
        item_errors: list[str] = []
        if not isinstance(template, dict):
            errors.append(f"template must be an object: {template_id}")
            continue
        prompt_path = root / str(template.get("prompt", ""))
        if not prompt_path.is_file():
            item_errors.append("missing canonical prompt")
        else:
            prompt = prompt_path.read_text(encoding="utf-8")
            for token in (
                "Frame 1: contact",
                "Frame 5: opposite_contact",
                "LEFT/ORANGE leg reaches forward",
                "RIGHT/GREEN leg reaches forward",
                "anatomical_left_arm: flat coral red",
                "anatomical_right_leg: flat leaf green",
            ):
                if token not in prompt:
                    item_errors.append(f"canonical prompt missing {token!r}")

        asset_path = root / str(template.get("asset", ""))
        approval_path = asset_path.with_suffix(".approval.json")
        status = template.get("status")
        pending_allowed = status == "needs-imagegen" and args.allow_pending
        if pending_allowed:
            pending_templates.append(template_id)
            if template.get("sha256") is not None:
                item_errors.append("pending template sha256 must be null")
            if asset_path.exists():
                item_errors.append("pending template must not bundle an unapproved master PNG")
            if approval_path.exists():
                item_errors.append("pending template must not bundle an approval sidecar")
        else:
            if status != "approved":
                item_errors.append(f"template status is {status!r}, not 'approved'")
            if not asset_path.is_file():
                item_errors.append("missing Image Gen master PNG")

        if not pending_allowed and asset_path.is_file():
            expected_hash = template.get("sha256")
            actual_hash = sha256_file(asset_path)
            if expected_hash != actual_hash:
                item_errors.append("master PNG sha256 mismatch")
            try:
                from PIL import Image

                with Image.open(asset_path) as image:
                    width, height = image.size
                    image.verify()
                if width < 1024 or height < 512 or width % 4 or height % 2:
                    item_errors.append(f"master PNG must be at least 1024x512 and divisible by 4x2, got {width}x{height}")
            except ModuleNotFoundError:
                item_errors.append("Pillow is required to inspect an approved master PNG")
            except OSError as exc:
                item_errors.append(f"invalid master PNG: {exc}")

            if not approval_path.is_file():
                item_errors.append("missing visual approval sidecar")
            else:
                approval = json.loads(approval_path.read_text(encoding="utf-8"))
                if approval.get("asset_sha256") != actual_hash:
                    item_errors.append("visual approval is stale for current PNG hash")
                checks = approval.get("checks")
                if not isinstance(checks, dict):
                    item_errors.append("visual approval checks must be an object")
                else:
                    failed = sorted(name for name in REQUIRED_APPROVALS if checks.get(name) is not True)
                    if failed:
                        item_errors.append(f"visual approval checks incomplete: {', '.join(failed)}")

        results.append(
            {
                "template_id": template_id,
                "status": status,
                "ok": not item_errors,
                "errors": item_errors,
            }
        )
        errors.extend(f"{template_id}: {message}" for message in item_errors)

    report = {
        "ok": not errors,
        "ready": not errors and not pending_templates,
        "pending_templates": pending_templates,
        "templates": results,
        "errors": errors,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
