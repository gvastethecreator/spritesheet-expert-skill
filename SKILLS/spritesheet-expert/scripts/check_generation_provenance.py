#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Validate exact, hash-bound provenance for every accepted source row."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from runio import atomic_write_text
from spritecore.provenance import validate_provenance


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument(
        "--allow-imported-source",
        action="store_true",
        help="accept verified imported/user-provided source provenance",
    )
    parser.add_argument(
        "--allow-fixture",
        action="store_true",
        help="accept verified fixture provenance; never representative production art",
    )
    args = parser.parse_args()

    result = validate_provenance(
        args.run_dir,
        allow_imported=args.allow_imported_source,
        allow_fixture=args.allow_fixture,
    )
    payload = result.to_dict()
    qa_dir = args.run_dir.expanduser().resolve() / "qa"
    qa_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        qa_dir / "generation-provenance-report.json",
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
