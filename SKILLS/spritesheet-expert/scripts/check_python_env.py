#!/usr/bin/env python3
"""Check the pinned Python runtime shipped with this installed skill."""

from __future__ import annotations

from importlib import import_module, metadata
import json
from pathlib import Path


REQUIREMENTS = Path(__file__).resolve().with_name("requirements-core.txt")
CORE = {
    "Pillow": ("PIL", "12.3.0"),
    "jsonschema": ("jsonschema", "4.26.0"),
}


def main() -> int:
    checks = []
    for distribution, (module, expected) in CORE.items():
        try:
            import_module(module)
            actual = metadata.version(distribution)
        except (ImportError, metadata.PackageNotFoundError):
            actual = None
        checks.append(
            {
                "distribution": distribution,
                "expected": expected,
                "actual": actual,
                "ok": actual == expected,
            }
        )
    ok = all(check["ok"] for check in checks)
    print(
        json.dumps(
            {
                "ok": ok,
                "profile": "core",
                "checks": checks,
                "install": f'python -m pip install -r "{REQUIREMENTS}"',
            },
            indent=2,
        )
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
