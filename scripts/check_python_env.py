#!/usr/bin/env python3
"""Check the pinned Python runtime required by the public skill CLIs."""

from __future__ import annotations

import argparse
from importlib import import_module, metadata
import json


CORE = {
    "Pillow": ("PIL", "12.3.0"),
    "jsonschema": ("jsonschema", "4.26.0"),
}
TEST = {
    "pytest": ("pytest", "9.1.1"),
    "pytest-cov": ("pytest_cov", "7.1.0"),
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test", action="store_true", help="include test dependencies")
    args = parser.parse_args()
    requirements = {**CORE, **(TEST if args.test else {})}
    checks = []
    for distribution, (module, expected) in requirements.items():
        try:
            import_module(module)
            actual = metadata.version(distribution)
        except (ImportError, metadata.PackageNotFoundError):
            checks.append(
                {
                    "distribution": distribution,
                    "expected": expected,
                    "actual": None,
                    "ok": False,
                }
            )
            continue
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
                "profile": "test" if args.test else "core",
                "checks": checks,
                "install": (
                    'python -m pip install -e ".[test]"'
                    if args.test
                    else "python -m pip install -e ."
                ),
            },
            indent=2,
        )
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
