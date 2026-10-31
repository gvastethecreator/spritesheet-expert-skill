#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Fail closed unless required locomotion references came from Image Gen."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from PIL import Image


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit(f"expected JSON object: {path}")
    return value


def inspect_reference(run_dir: Path, state: str, contract: dict[str, Any]) -> dict[str, Any]:
    relative = Path(str(contract.get("expected_output", "")))
    image_path = (run_dir / relative).resolve()
    reference_root = (run_dir / "references" / "motion-references").resolve()
    errors: list[str] = []
    if reference_root not in image_path.parents:
        errors.append("expected_output escapes references/motion-references")
    if not image_path.is_file():
        errors.append(f"missing Image Gen motion reference: {relative.as_posix()}")

    width = height = 0
    if image_path.is_file():
        try:
            with Image.open(image_path) as opened:
                width, height = opened.size
                opened.verify()
        except (OSError, ValueError) as exc:
            errors.append(f"invalid motion reference image: {exc}")
        if width < 512 or height < 512:
            errors.append(f"motion reference is too small for anatomy review: {width}x{height}; minimum 512x512")

    provenance_path = image_path.with_suffix(".provenance.json")
    try:
        provenance_display = provenance_path.relative_to(run_dir).as_posix()
    except ValueError:
        provenance_display = str(provenance_path)
    provenance: dict[str, Any] = {}
    if not provenance_path.is_file():
        errors.append(f"missing Image Gen provenance: {provenance_display}")
    else:
        provenance = load_json(provenance_path)
        if provenance.get("art_engine") != "imagegen":
            errors.append("motion reference provenance must declare art_engine=imagegen")
        if provenance.get("state") != state:
            errors.append(f"motion reference provenance state must be {state!r}")
        if not provenance.get("selected_source"):
            errors.append("motion reference provenance must record selected_source")

    return {
        "state": state,
        "ok": not errors,
        "image": relative.as_posix(),
        "provenance": provenance_display,
        "size": [width, height],
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    args = parser.parse_args()
    run_dir = args.run_dir.expanduser().resolve()
    plan_path = run_dir / "references" / "motion-reference-plan.json"
    plan = load_json(plan_path)
    rows = plan.get("rows")
    if not isinstance(rows, dict):
        raise SystemExit(f"motion reference plan has invalid rows: {plan_path}")

    invalid_contracts = [state for state, contract in rows.items() if not isinstance(contract, dict)]
    if invalid_contracts:
        raise SystemExit(f"motion reference contracts must be objects: {', '.join(invalid_contracts)}")
    results = [inspect_reference(run_dir, state, contract) for state, contract in rows.items()]
    report = {
        "ok": all(item["ok"] for item in results),
        "checked_states": [item["state"] for item in results],
        "references": results,
    }
    report_path = run_dir / "qa" / "motion-reference-report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
