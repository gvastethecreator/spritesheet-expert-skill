#!/usr/bin/env python3
"""Create, inspect and organize portable sprite workspaces with Studio's contracts."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

from spritecore.workspace import Workspace
from serve_item_studio import SKILL, Studio


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    for operation in ("create", "inspect", "import", "adopt-run", "organize", "handoff", "run", "export"):
        command = sub.add_parser(operation)
        command.add_argument("--workspace", type=Path, required=True)
        if operation == "create":
            command.add_argument("--name", required=True)
        if operation in {"import", "adopt-run"}:
            command.add_argument("--source", type=Path, required=True)
            command.add_argument("--name")
            command.add_argument("--collection", default="")
        if operation == "adopt-run":
            command.add_argument("--lane", choices=("true-grid", "animation", "tileset", "static-items"))
        if operation == "import":
            command.add_argument("--job-id")
        if operation in {"organize", "run", "export"}:
            command.add_argument("--run-id", required=True)
        if operation == "organize":
            command.add_argument("--name")
            command.add_argument("--collection")
            command.add_argument("--archived", choices=("true", "false"))
        if operation == "handoff":
            command.add_argument("--file", type=Path, required=True, help="JSON add/archive operation")
        if operation == "run":
            command.add_argument("--models", choices=("none", "standard", "light"), default="standard")
            command.add_argument("--quantum", type=int, default=32)
            command.add_argument("--padding", type=int, default=16)
            command.add_argument("--max-width", type=int, default=0)
            command.add_argument("--max-height", type=int, default=8192)
            command.add_argument("--max-pages", type=int, default=16)
            command.add_argument("--max-page-pixels", type=int, default=16_777_216)
            command.add_argument("--max-total-pixels", type=int, default=50_000_000)
            command.add_argument("--runtime-config", type=Path, default=SKILL / ".local/item-model-runtime.json")
        if operation == "export":
            command.add_argument("--draft", action="store_true")
    args = parser.parse_args()
    try:
        store = Workspace.create(args.workspace, args.name) if args.operation == "create" else Workspace(args.workspace)
        if args.operation in {"create", "inspect"}:
            result = store.catalog()
            result["handoffs"] = store.handoffs()
        elif args.operation == "import":
            if args.source.stat().st_size > 128 * 1024 * 1024:
                raise ValueError("source exceeds 128 MiB")
            result = store.import_image(args.source.read_bytes(), args.name or args.source.name,
                                        collection=args.collection, job_id=args.job_id)
        elif args.operation == "adopt-run":
            result = store.adopt_run(args.source, name=args.name or args.source.name, collection=args.collection, lane=args.lane)
        elif args.operation == "organize":
            changes = {key: getattr(args, key) for key in ("name", "collection") if getattr(args, key) is not None}
            if args.archived is not None:
                changes["archived"] = args.archived == "true"
            result = store.organize(args.run_id, changes)
        elif args.operation == "handoff":
            result = store.handoff(json.loads(args.file.read_text(encoding="utf-8")))
        else:
            studio = Studio(store.root, getattr(args, "runtime_config", SKILL / ".local/item-model-runtime.json"))
            if args.operation == "export":
                if store.metadata(args.run_id).get("lane") in {"true-grid", "animation", "tileset"}:
                    if not args.draft:
                        raise ValueError("component-row workspace archives require --draft; use the lane's engine exporter for delivery")
                    result = store.archive_run(args.run_id)
                else:
                    result = studio.export(args.run_id, {"draft": args.draft}, saved=True)
            else:
                result = studio.start(args.run_id, {key: getattr(args, key) for key in
                    ("models", "quantum", "padding", "max_width", "max_height", "max_pages", "max_page_pixels", "max_total_pixels")})
                process = studio.processes.get(args.run_id)
                try:
                    while process is not None and process.poll() is None:
                        time.sleep(.2)
                except KeyboardInterrupt:
                    (studio.run_root(args.run_id) / "cancel.request").touch()
                    raise
                result = studio.snapshot(args.run_id)
                if process is not None and process.returncode:
                    raise ValueError(result.get("error", "workflow failed"))
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (ValueError, OSError, KeyError, RuntimeError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
