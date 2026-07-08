#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Gate sprite runs on real art provenance.

Production sprite-atlas work must be backed by imagegen or an explicitly
imported/user-provided art source. Synthetic/PIL/procedural rows are fixtures
only and should not be allowed to stand in for representative art.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from runio import atomic_write_text


IMAGEGEN_MARKERS = ("imagegen", "$imagegen", "openai-image", "generated-images")
IMPORTED_MARKERS = ("user-provided", "user provided", "imported", "provided by user", "existing sheet")
FIXTURE_MARKERS = ("synthetic", "procedural", "imagebrush", "fixture")


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"could not read JSON: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"expected JSON object: {path}")
    return data


def flatten_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.lower()]
    if isinstance(value, dict):
        out: list[str] = []
        for key, item in value.items():
            out.extend(flatten_strings(key))
            out.extend(flatten_strings(item))
        return out
    if isinstance(value, list):
        out = []
        for item in value:
            out.extend(flatten_strings(item))
        return out
    return []


def has_marker(strings: list[str], markers: tuple[str, ...]) -> bool:
    return any(marker in value for value in strings for marker in markers)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--allow-imported-source", action="store_true", help="accept explicit user/imported source provenance")
    parser.add_argument("--allow-fixture", action="store_true", help="accept synthetic/procedural fixture runs")
    args = parser.parse_args()

    run_dir = args.run_dir
    docs: dict[str, dict[str, Any]] = {}
    for name in ("source-provenance.json", "sprite-request.json", "unpack-source.json"):
        data = read_json(run_dir / name)
        if data is not None:
            docs[name] = data

    strings: list[str] = []
    for data in docs.values():
        strings.extend(flatten_strings(data))

    imagegen = has_marker(strings, IMAGEGEN_MARKERS)
    imported = has_marker(strings, IMPORTED_MARKERS) or "unpack-source.json" in docs
    fixture = has_marker(strings, FIXTURE_MARKERS)

    errors: list[str] = []
    warnings: list[str] = []
    fixture_allowed = fixture and args.allow_fixture
    if fixture and not args.allow_fixture:
        errors.append("synthetic/procedural fixture provenance is not allowed for production art")
    if fixture_allowed:
        warnings.append("accepted synthetic/procedural art as an explicit fixture")
    elif imagegen:
        pass
    elif imported and args.allow_imported_source:
        warnings.append("accepted explicit imported/user-provided source; not imagegen-generated art")
    elif imported:
        errors.append("imported/user-provided source requires --allow-imported-source and clear provenance")
    else:
        errors.append("missing imagegen provenance; add source-provenance.json with art_engine=imagegen before production QA")

    report = {
        "ok": not errors,
        "engine": "generation-provenance-gate",
        "run_dir": str(run_dir),
        "imagegen": imagegen,
        "imported_source": imported,
        "fixture": fixture,
        "checked_files": sorted(docs),
        "errors": errors,
        "warnings": warnings,
    }
    qa_dir = run_dir / "qa"
    qa_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_text(qa_dir / "generation-provenance-report.json", json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
