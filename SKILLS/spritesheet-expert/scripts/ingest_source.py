#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Validate and atomically ingest one selected provider bitmap as a raw row."""

from __future__ import annotations

import argparse
from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from PIL import Image

from runio import atomic_write_text
from spritecore.contracts import ContractError, normalize_contract
from spritecore.locks import RunLockError, acquire_run_lock
from spritecore.source_intake import (
    SourceIntakeError,
    SourceIntakePlan,
    document_fingerprint,
    load_source_intake,
    validate_source_intake,
)


def _atomic_write_bytes(target: Path, payload: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        dir=str(target.parent), prefix=f".{target.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
        os.replace(temporary, target)
    except BaseException:
        if os.path.exists(temporary):
            os.unlink(temporary)
        raise


def _normalized_png(plan: SourceIntakePlan) -> bytes:
    with Image.open(plan.candidate_path) as opened:
        opened.load()
        normalized = opened.convert("RGBA")
    buffer = BytesIO()
    normalized.save(buffer, format="PNG")
    return buffer.getvalue()


def _provenance_for(
    plan: SourceIntakePlan, *, output_sha256: str, output_size: int
) -> dict[str, Any]:
    prior = plan.existing_provenance or {}
    accepted = [
        dict(entry)
        for entry in prior.get("accepted_sources", [])
        if plan.state not in entry.get("states", [])
    ]
    accepted.append(
        {
            "path": f"raw/{plan.state}.png",
            "sha256": output_sha256,
            "size_bytes": output_size,
            "states": [plan.state],
        }
    )
    state_order = {state: index for index, state in enumerate(plan.request["states"])}
    accepted.sort(
        key=lambda entry: min(
            (state_order.get(state, len(state_order)) for state in entry["states"]),
            default=len(state_order),
        )
    )
    coverage = [
        state
        for state in plan.request["states"]
        if any(state in entry["states"] for entry in accepted)
    ]
    provenance = {
        "version": 2,
        "kind": "sprite-source-provenance",
        "source_type": plan.source_type,
        "art_engine": plan.source_type,
        "fixture": plan.source_type == "fixture",
        "verification_status": "verified",
        "accepted_sources": accepted,
        "state_coverage": coverage,
        "notes": "accepted through source-intake-v1",
        "license": plan.license_ref,
    }
    return normalize_contract(
        provenance, expected_kind="source-provenance"
    ).to_dict()


def _failure_report(
    *, issues: list[str] | tuple[str, ...], job_id: str | None, status: str = "fail"
) -> dict[str, Any]:
    return {
        "version": 1,
        "kind": "sprite-source-intake-report",
        "ok": False,
        "status": status,
        "job_id": job_id,
        "mutated": False,
        "errors": list(issues),
        "warnings": [],
    }


def _success_report(
    plan: SourceIntakePlan,
    *,
    output_sha256: str,
    output_size: int,
    coverage: list[str],
) -> dict[str, Any]:
    report = {
        "version": 1,
        "kind": "sprite-source-intake-report",
        "ok": True,
        "status": "pass",
        "job_id": plan.job_id,
        "state": plan.state,
        "mutated": True,
        "source_type": plan.source_type,
        "engine": plan.engine,
        "source_stage": plan.intake["source_stage"],
        "provider": dict(plan.intake["provider"]),
        "license_ref": plan.license_ref,
        "license_status": plan.license_status,
        "request_fingerprint": document_fingerprint(plan.request),
        "candidate": {
            "path": plan.intake["candidate"]["path"],
            "sha256": plan.candidate_sha256,
            "mime": plan.candidate_mime,
            "width": plan.width,
            "height": plan.height,
        },
        "processing_policy": dict(plan.intake["processing_policy"]),
        "output": {
            "path": f"raw/{plan.state}.png",
            "sha256": output_sha256,
            "size_bytes": output_size,
            "mime": "image/png",
            "width": plan.width,
            "height": plan.height,
        },
        "provenance": {
            "path": "source-provenance.json",
            "state_coverage": coverage,
        },
        "errors": [],
        "warnings": [],
    }
    for binding_name in ("style_reference", "identity_anchor"):
        binding = plan.intake.get(binding_name)
        if isinstance(binding, dict):
            report[binding_name] = dict(binding)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--intake", required=True, type=Path)
    parser.add_argument(
        "--force",
        action="store_true",
        help="replace only the declared raw/<state>.png and its provenance entry",
    )
    args = parser.parse_args()
    job_id: str | None = None
    try:
        intake = load_source_intake(args.intake)
        raw_job_id = intake.get("job_id")
        job_id = raw_job_id if isinstance(raw_job_id, str) else None
        validate_source_intake(intake, run_dir=args.run_dir, force=args.force)
    except SourceIntakeError as exc:
        print(json.dumps(_failure_report(issues=exc.issues, job_id=job_id), indent=2))
        return 1

    try:
        with acquire_run_lock(args.run_dir, "ingest_source"):
            plan = validate_source_intake(
                intake, run_dir=args.run_dir, force=args.force
            )
            png_bytes = _normalized_png(plan)
            from hashlib import sha256

            output_sha256 = sha256(png_bytes).hexdigest()
            provenance = _provenance_for(
                plan,
                output_sha256=output_sha256,
                output_size=len(png_bytes),
            )
            report = _success_report(
                plan,
                output_sha256=output_sha256,
                output_size=len(png_bytes),
                coverage=list(provenance["state_coverage"]),
            )
            plan.output_path.parent.mkdir(parents=True, exist_ok=True)
            (plan.run_dir / "qa").mkdir(parents=True, exist_ok=True)
            _atomic_write_bytes(plan.output_path, png_bytes)
            atomic_write_text(
                plan.provenance_path,
                json.dumps(provenance, ensure_ascii=False, indent=2) + "\n",
            )
            atomic_write_text(
                plan.report_path,
                json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            )
    except SourceIntakeError as exc:
        print(json.dumps(_failure_report(issues=exc.issues, job_id=job_id), indent=2))
        return 1
    except (RunLockError, ContractError, OSError, ValueError) as exc:
        report = _failure_report(
            issues=[str(exc)], job_id=job_id, status="operational-error"
        )
        print(json.dumps(report, indent=2))
        return 3

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
