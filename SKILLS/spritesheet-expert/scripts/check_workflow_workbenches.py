#!/usr/bin/env python3
"""Fail-closed validation for isolated workflow workbench contracts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DEFAULT_ROOT = Path(__file__).resolve().parents[1] / "assets" / "workflow-workbenches"
ALLOWED_STATUS = {"active", "blocked"}
ALLOWED_ASSET_KINDS = {"sprite", "asset", "vfx", "tileset", "texture"}
REQUIRED_CONTRACT_KEYS = {
    "version",
    "workflow",
    "asset_kind",
    "output_kind",
    "views",
    "frame_count",
    "generation_order",
    "required_templates",
    "candidate_policy",
    "review_artifacts",
    "hard_gates",
    "promotion",
}


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"missing JSON: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def find_dependency_cycle(entries: dict[str, Any]) -> list[str]:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(name: str, stack: list[str]) -> list[str]:
        if name in visiting:
            start = stack.index(name)
            return stack[start:] + [name]
        if name in visited:
            return []
        visiting.add(name)
        dependency = entries[name].get("blocked_by")
        if dependency in entries:
            cycle = visit(dependency, stack + [dependency])
            if cycle:
                return cycle
        visiting.remove(name)
        visited.add(name)
        return []

    for key in entries:
        cycle = visit(key, [key])
        if cycle:
            return cycle
    return []


def validate(root: Path) -> dict[str, Any]:
    errors: list[str] = []
    contracts: list[dict[str, Any]] = []
    catalog_path = root / "catalog.json"
    try:
        catalog = read_json(catalog_path)
    except ValueError as exc:
        return {"ok": False, "kind": "workflow-workbench-check", "root": str(root), "errors": [str(exc)], "contracts": []}

    entries = catalog.get("workbenches")
    if catalog.get("kind") != "spritesheet-workflow-workbench-catalog":
        errors.append("catalog.kind must be spritesheet-workflow-workbench-catalog")
    if not isinstance(entries, dict) or not entries:
        errors.append("catalog.workbenches must be a non-empty object")
        entries = {}

    active = [name for name, entry in entries.items() if isinstance(entry, dict) and entry.get("status") == "active"]
    if len(active) != 1:
        errors.append(f"exactly one workbench must be active; found {len(active)}")

    for name, entry in entries.items():
        if not isinstance(entry, dict):
            errors.append(f"{name}: catalog entry must be an object")
            continue
        status = entry.get("status")
        if status not in ALLOWED_STATUS:
            errors.append(f"{name}: unsupported status {status!r}")
        if status == "blocked":
            dependency = entry.get("blocked_by")
            if dependency not in entries:
                errors.append(f"{name}: blocked_by must reference another workbench")
            if dependency == name:
                errors.append(f"{name}: cannot block itself")

        contract_rel = entry.get("contract")
        if not isinstance(contract_rel, str) or not contract_rel:
            errors.append(f"{name}: contract path is required")
            continue
        contract_path = root / contract_rel
        if not inside(contract_path, root):
            errors.append(f"{name}: contract escapes workbench root")
            continue
        try:
            contract = read_json(contract_path)
        except ValueError as exc:
            errors.append(f"{name}: {exc}")
            continue

        missing = sorted(REQUIRED_CONTRACT_KEYS - contract.keys())
        if missing:
            errors.append(f"{name}: contract missing keys: {', '.join(missing)}")
        if contract.get("workflow") != name:
            errors.append(f"{name}: contract.workflow must match catalog key")
        if contract.get("asset_kind") not in ALLOWED_ASSET_KINDS:
            errors.append(f"{name}: unsupported asset_kind {contract.get('asset_kind')!r}")
        if not isinstance(contract.get("frame_count"), int) or contract.get("frame_count", 0) < 1:
            errors.append(f"{name}: frame_count must be a positive integer")
        for key in ("views", "generation_order", "required_templates", "review_artifacts", "hard_gates"):
            if not isinstance(contract.get(key), list) or not contract.get(key):
                errors.append(f"{name}: {key} must be a non-empty list")

        candidate_rel = entry.get("candidate_root")
        if not isinstance(candidate_rel, str) or not candidate_rel:
            errors.append(f"{name}: candidate_root is required")
        else:
            candidate_path = root / candidate_rel
            assets_root = root.parent
            if not inside(candidate_path, assets_root):
                errors.append(f"{name}: candidate_root escapes assets root")

        contracts.append({
            "workflow": name,
            "status": status,
            "contract": str(contract_path),
            "asset_kind": contract.get("asset_kind"),
            "views": contract.get("views", []),
            "frame_count": contract.get("frame_count"),
            "hard_gate_count": len(contract.get("hard_gates", [])) if isinstance(contract.get("hard_gates"), list) else 0,
        })

    cycle = find_dependency_cycle(entries)
    if cycle:
        errors.append("workbench dependency cycle: " + " -> ".join(cycle))

    return {
        "ok": not errors,
        "kind": "workflow-workbench-check",
        "root": str(root.resolve()),
        "active": active,
        "contract_count": len(contracts),
        "contracts": contracts,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = validate(args.root)
    payload = json.dumps(report, indent=2) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

