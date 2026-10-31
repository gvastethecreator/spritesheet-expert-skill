#!/usr/bin/env python3
"""Describe workflow lanes or execute the final gate for one declared lane."""
import argparse
import json
from pathlib import Path
import subprocess

from spritecore.workflow_lanes import registry, final_command, describe_run
from spritecore.item_delivery import artifact


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--lane", choices=tuple(registry()["lanes"]))
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--draft", action="store_true")
    parser.add_argument("--allow-imported-source", action="store_true")
    parser.add_argument("--allow-fixture", action="store_true")
    parser.add_argument("--describe", action="store_true", help="print typed argv without executing")
    args = parser.parse_args()
    try:
        if args.list:
            print(json.dumps(registry(), indent=2)); return 0
        if args.run_dir is None:
            raise ValueError("--run-dir is required")
        lane, state = describe_run(args.run_dir, lane=args.lane)
        manifest = args.manifest
        if lane == "static-items" and manifest is None:
            manifest = artifact(args.run_dir, state["manifest"])
        command = final_command(lane, args.run_dir, manifest=manifest, draft=args.draft,
            allow_imported=args.allow_imported_source, allow_fixture=args.allow_fixture)
        if args.describe:
            print(json.dumps({"lane": lane, "argv": command})); return 0
        return subprocess.run(command, check=False).returncode
    except (ValueError, OSError, KeyError) as error:
        print(json.dumps({"status": "blocked", "error": str(error)})); return 3


if __name__ == "__main__":
    raise SystemExit(main())
