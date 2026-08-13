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


DEFAULT_PLAN = "qa/quota-sealed-repair-plan.json"


class RepairProvenanceError(ValueError):
    """Raised when repair evidence cannot support a provenance update."""


def _load_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise RepairProvenanceError(f"{label} is missing: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RepairProvenanceError(f"{label} is unreadable: {exc}") from exc
    if not isinstance(payload, dict):
        raise RepairProvenanceError(f"{label} must be a JSON object")
    return payload


def _completed_states(plan: Mapping[str, Any]) -> list[str]:
    if plan.get("status") != "completed":
        raise RepairProvenanceError("repair plan status must be completed")

    states: list[str] = []
    repairs = plan.get("repairs")
    if isinstance(repairs, list):
        for index, repair in enumerate(repairs):
            if not isinstance(repair, Mapping):
                raise RepairProvenanceError(f"repairs[{index}] must be an object")
            if repair.get("status") != "completed":
                continue
            state = repair.get("state")
            if not isinstance(state, str) or not state:
                raise RepairProvenanceError(
                    f"repairs[{index}].state must name a completed state"
                )
            states.append(state)
    else:
        state = plan.get("state")
        if isinstance(state, str) and state:
            states.append(state)

    unique = list(dict.fromkeys(states))
    if not unique:
        raise RepairProvenanceError("repair plan has no completed states")
    return unique


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
    if not isinstance(states, Mapping):
        raise RepairProvenanceError("sprite-request.json states must be an object")
    return [str(state) for state in states]


def _sync(
    *,
    run_dir: Path,
    plan_path: Path,
    states: list[str],
) -> dict[str, Any]:
    request = _load_json(run_dir / "sprite-request.json", "sprite request")
    order = _state_order(request)
    unknown = [state for state in states if state not in order]
    if unknown:
        raise RepairProvenanceError(
            "repair states are not declared in sprite-request.json: " + ", ".join(unknown)
        )

    provenance_path = run_dir / "source-provenance.json"
    prior_payload = _load_json(provenance_path, "source provenance")
    try:
        provenance = normalize_contract(
            prior_payload, expected_kind="source-provenance"
        ).to_dict()
    except ContractError as exc:
        raise RepairProvenanceError(f"source provenance is invalid: {exc}") from exc

    accepted = [dict(entry) for entry in provenance["accepted_sources"]]
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
        raw_path = run_dir / "raw" / f"{state}.png"
        if not raw_path.is_file():
            raise RepairProvenanceError(f"repaired source is missing: {raw_path}")
        content = raw_path.read_bytes()
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
            "fixture": False,
            "verification_status": "verified",
            "accepted_sources": accepted,
            "state_coverage": [
                state
                for state in order
                if any(state in entry["states"] for entry in accepted)
            ],
            "notes": (
                "Quota-sealed video states with documented ImageGen frame repairs; "
                "accepted source hashes match the current raw sheets."
            ),
            "license": "mixed-provider-terms" if mixed else "OpenAI-provider-terms",
        }
    )
    try:
        normalized = normalize_contract(
            provenance, expected_kind="source-provenance"
        ).to_dict()
    except ContractError as exc:
        raise RepairProvenanceError(f"updated source provenance is invalid: {exc}") from exc

    atomic_write_text(
        provenance_path,
        json.dumps(normalized, indent=2, ensure_ascii=False) + "\n",
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
        plan_path = (run_dir / args.repair_plan).resolve()
        try:
            plan_path.relative_to(run_dir)
        except ValueError as exc:
            raise RepairProvenanceError("repair plan must stay inside the run directory") from exc
        plan = _load_json(plan_path, "repair plan")
        states = _requested_states(args.states, _completed_states(plan))
        acquire_run_dir_lock(run_dir, "sync-imagegen-repair-provenance")
        result = _sync(
            run_dir=run_dir,
            plan_path=plan_path,
            states=states,
        )
    except (OSError, RepairProvenanceError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
