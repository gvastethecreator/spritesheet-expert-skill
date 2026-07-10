#!/usr/bin/env python3
"""Validate and migrate one legacy spritesheet contract to canonical v2 JSON."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from runio import atomic_write_text
from spritecore.contracts import ContractError, load_contract
from spritecore.models import ContractKind


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--kind", required=True, choices=[kind.value for kind in ContractKind])
    parser.add_argument("--write", action="store_true", help="replace the source after writing a backup")
    parser.add_argument("--backup-suffix", default=".v1.bak")
    args = parser.parse_args()

    source = args.source.expanduser().resolve()
    try:
        original = json.loads(source.read_text(encoding="utf-8-sig"))
        contract = load_contract(source, expected_kind=args.kind)
        canonical = contract.to_dict()
    except ContractError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (OSError, ValueError) as exc:
        print(f"could not read contract: {exc}", file=sys.stderr)
        return 3

    changed = original != canonical
    backup: Path | None = None
    if args.write and changed:
        backup = source.with_name(source.name + args.backup_suffix)
        if backup.exists():
            print(f"backup already exists: {backup}", file=sys.stderr)
            return 1
        try:
            shutil.copy2(source, backup)
            atomic_write_text(source, json.dumps(canonical, ensure_ascii=False, indent=2) + "\n")
        except OSError as exc:
            print(f"could not write migrated contract: {exc}", file=sys.stderr)
            return 3

    report = {
        "ok": True,
        "source": str(source),
        "kind": contract.kind.value,
        "from_version": original.get("version", 1) if isinstance(original, dict) else None,
        "to_version": contract.version,
        "changed": changed,
        "written": bool(args.write and changed),
        "backup": str(backup) if backup else None,
        "contract": canonical,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
