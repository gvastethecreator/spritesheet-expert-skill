#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Synchronize provenance after a quota-sealed ImageGen frame repair."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
from typing import Any, Mapping

from runio import acquire_run_dir_lock, atomic_write_text
from spritecore.contracts import ContractError, normalize_contract
from spritecore.models import is_state_slug
from spritecore.paths import resolve_run_path


DEFAULT_PLAN = "qa/quota-sealed-repair-plan.json"


class RepairProvenanceError(ValueError):
    """Raised when repair evidence cannot support a provenance update."""


def _load_json(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    if not path.is_file():
        raise RepairProvenanceError(f"{label} is missing: {path}")
    try:
        content = path.read_bytes()
        payload = json.loads(content.decode("utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RepairProvenanceError(f"{label} is unreadable: {exc}") from exc
    if not isinstance(payload, dict):
        raise RepairProvenanceError(f"{label} must be a JSON object")
    return payload, content


def _completed_repairs(plan: Mapping[str, Any]) -> dict[str, str]:
    if plan.get("status") != "completed":
        raise RepairProvenanceError("repair plan status must be completed")

    completed: dict[str, str] = {}
    repairs = plan.get("repairs")
    if repairs is None:
        repairs = [plan]
    if not isinstance(repairs, list):
        raise RepairProvenanceError("repair plan repairs must be an array")
    for index, repair in enumerate(repairs):
        if not isinstance(repair, Mapping):
            raise RepairProvenanceError(f"repairs[{index}] must be an object")
        if repair.get("status") != "completed":
            continue
        state, result = repair.get("state"), repair.get("result")
        if not is_state_slug(state):
            raise RepairProvenanceError(f"repairs[{index}].state must be a portable state slug")
        if not isinstance(result, str) or not result:
            raise RepairProvenanceError(f"repairs[{index}].result must name the repaired source")
        if state in completed:
            raise RepairProvenanceError(f"duplicate completed repair state: {state}")
        completed[state] = result
    if not completed:
        raise RepairProvenanceError("repair plan has no completed states")
    return completed


def _requested_states(raw: str | None, completed: list[str]) -> list[str]:
    if raw is None:
        return completed
    selected = list(dict.fromkeys(item.strip() for item in raw.split(",") if item.strip()))
    if not selected:
        raise RepairProvenanceError("--states must contain at least one state")
    unavailable = [state for state in selected if state not in completed]
    if unavailable:
        raise RepairProvenanceError(
            "states are not completed in the repair plan: " + ", ".join(unavailable)
        )
    return selected


def _state_order(request: Mapping[str, Any]) -> list[str]:
    states = request.get("states")
    if not isinstance(states, Mapping) or not states or any(not is_state_slug(state) for state in states):
        raise RepairProvenanceError("sprite-request.json states must be a non-empty object of portable state slugs")
    return [str(state) for state in states]


def _sync(
    *,
    run_dir: Path,
    plan_path: Path,
    plan_bytes: bytes,
    completed: Mapping[str, str],
    states: list[str],
) -> dict[str, Any]:
    request_path = resolve_run_path(run_dir, "sprite-request.json")
    request, request_bytes = _load_json(request_path, "sprite request")
    order = _state_order(request)
    unknown = [state for state in states if state not in order]
    if unknown:
        raise RepairProvenanceError(
            "repair states are not declared in sprite-request.json: " + ", ".join(unknown)
        )

    provenance_path = resolve_run_path(run_dir, "source-provenance.json")
    if plan_path == provenance_path:
        raise RepairProvenanceError("repair plan cannot be the provenance output")
    prior_payload, prior_bytes = _load_json(provenance_path, "source provenance")
    try:
        provenance = normalize_contract(
            prior_payload, expected_kind="source-provenance"
        ).to_dict()
    except ContractError as exc:
        raise RepairProvenanceError(f"source provenance is invalid: {exc}") from exc

    accepted = [dict(entry) for entry in provenance["accepted_sources"]]
    if provenance["fixture"] or any(entry.get("source_type") == "fixture" for entry in accepted):
        raise RepairProvenanceError("fixture sources require source intake, not promotion through repair sync")
    snapshots = {request_path: request_bytes, provenance_path: prior_bytes, plan_path: plan_bytes}
    plan_relative = plan_path.relative_to(run_dir).as_posix()
    updates: list[dict[str, Any]] = []

    for state in states:
        matches = [entry for entry in accepted if state in entry.get("states", [])]
        if len(matches) != 1:
            raise RepairProvenanceError(
                f"source provenance must contain exactly one accepted source for {state!r}"
            )
        entry = matches[0]
        if entry.get("states") != [state]:
            raise RepairProvenanceError(
                f"accepted source for {state!r} must cover only that state"
            )
        raw_path = resolve_run_path(run_dir, f"raw/{state}.png")
        if raw_path in snapshots:
            raise RepairProvenanceError(f"repaired source aliases metadata: {raw_path}")
        if resolve_run_path(run_dir, completed[state]) != raw_path:
            raise RepairProvenanceError(f"repair result for {state!r} does not match raw/{state}.png")
        if not raw_path.is_file():
            raise RepairProvenanceError(f"repaired source is missing: {raw_path}")
        content = raw_path.read_bytes()
        snapshots[raw_path] = content
        if not content:
            raise RepairProvenanceError(f"repaired source is empty: {raw_path}")
        digest = sha256(content).hexdigest()
        entry.update(
            {
                "path": f"raw/{state}.png",
                "sha256": digest,
                "size_bytes": len(content),
                "source_type": "imagegen",
                "art_engine": "imagegen",
                "upstream_report": plan_relative,
            }
        )
        updates.append(
            {
                "state": state,
                "path": entry["path"],
                "sha256": digest,
                "size_bytes": len(content),
            }
        )

    accepted.sort(
        key=lambda entry: min(
            (order.index(state) for state in entry["states"] if state in order),
            default=len(order),
        )
    )
    source_types = {str(entry.get("source_type")) for entry in accepted}
    art_engines = {str(entry.get("art_engine")) for entry in accepted}
    mixed = len(source_types) > 1 or len(art_engines) > 1
    provenance.update(
        {
            "source_type": "mixed" if mixed else next(iter(source_types)),
            "art_engine": "mixed" if mixed else next(iter(art_engines)),
            "accepted_sources": accepted,
            "state_coverage": [
                state
                for state in order
                if any(state in entry["states"] for entry in accepted)
            ],
        }
    )
    try:
        normalized = normalize_contract(
            provenance, expected_kind="source-provenance"
        ).to_dict()
    except ContractError as exc:
        raise RepairProvenanceError(f"updated source provenance is invalid: {exc}") from exc

    for path, expected_bytes in snapshots.items():
        if path.read_bytes() != expected_bytes:
            raise RepairProvenanceError(f"repair input changed during synchronization: {path}")
    atomic_write_text(
        provenance_path,
        json.dumps(normalized, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
    )
    return {
        "ok": True,
        "run_dir": str(run_dir),
        "repair_plan": plan_relative,
        "updated_states": updates,
        "source_type": normalized["source_type"],
        "art_engine": normalized["art_engine"],
        "provenance": "source-provenance.json",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Synchronize ImageGen repair bytes with source provenance."
    )
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--repair-plan", default=DEFAULT_PLAN)
    parser.add_argument(
        "--states",
        help="Optional comma-separated subset of completed repair states.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_dir = args.run_dir.resolve()
    try:
        requested = Path(args.repair_plan).expanduser()
        if requested.is_absolute():
            requested = requested.relative_to(run_dir)
        plan_path = resolve_run_path(run_dir, requested)
        acquire_run_dir_lock(run_dir, "sync-imagegen-repair-provenance")
        plan, plan_bytes = _load_json(plan_path, "repair plan")
        completed = _completed_repairs(plan)
        states = _requested_states(args.states, list(completed))
        result = _sync(
            run_dir=run_dir,
            plan_path=plan_path,
            plan_bytes=plan_bytes,
            completed=completed,
            states=states,
        )
    except (OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
