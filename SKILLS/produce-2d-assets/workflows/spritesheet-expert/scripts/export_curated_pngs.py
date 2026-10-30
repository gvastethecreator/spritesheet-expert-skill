#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Export curated frames back to named PNGs (the inverse of an imported set).

For an imported still set (e.g. a furniture pack), the natural deliverable is
not a single atlas but the same separate PNGs with the curation transform baked
in, keeping each item's original filename so the consuming app needs no change.

Output defaults to `<run-dir>/curated/`; `--out-dir` selects another destination.
Before writing, the command checks every input and output path. It rejects
missing frames, unsafe or duplicate names, and destinations that replace source
artifacts. Filesystem or image errors still fail the export.
Existing output files are kept. The returned file list identifies this export;
use a new destination for a folder containing only the current selection.

    python3 export_curated_pngs.py --run-dir <run-dir> [--state <name>] [--out-dir <path>]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path

from PIL import Image

from curation import apply_transform, load_curation, state_plan
from compose_sprite_atlas import resize_policy_for_request
from runio import acquire_run_dir_lock, atomic_save_image
from spritecore.paths import PathSafetyError, resolve_run_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--state", help="state to export; defaults to all states")
    parser.add_argument("--out-dir", type=Path, help="output dir (default: <run-dir>/curated)")
    parser.add_argument("--selected-only", action="store_true", help="export only selected frames")
    args = parser.parse_args()

    run_dir = args.run_dir.expanduser().resolve()
    acquire_run_dir_lock(run_dir, "export_curated_pngs")
    request = json.loads((run_dir / "sprite-request.json").read_text(encoding="utf-8"))
    resize_policy = resize_policy_for_request(request)
    cell = request["cell"]
    cell_size = (int(cell.get("width", cell.get("size", 0))), int(cell.get("height", cell.get("size", 0))))
    curation = load_curation(run_dir)

    frames_manifest = json.loads((run_dir / "frames" / "frames-manifest.json").read_text(encoding="utf-8"))
    labels_by_state = {row["state"]: row.get("labels", []) for row in frames_manifest.get("rows", [])}

    out_dir = (args.out_dir.expanduser().resolve() if args.out_dir else run_dir / "curated")
    if any(out_dir.is_relative_to(run_dir / name) for name in ("frames", "raw", "source", "references", "qa")):
        raise SystemExit("export destination cannot replace source artifacts")

    source_meta = None
    protected = {path.resolve() for path in run_dir.iterdir() if path.is_file()}
    unpack_src = run_dir / "unpack-source.json"
    if unpack_src.is_file():
        info = json.loads(unpack_src.read_text(encoding="utf-8"))
        if info.get("source_dir"):
            source_dir = Path(info["source_dir"]).expanduser().resolve()
            protected.update((source_dir / name).resolve() for name in info.get("files", []))
            candidate = source_dir / "meta.json"
            if candidate.is_file():
                source_meta = candidate
                protected.add(candidate.resolve())

    states = [args.state] if args.state else list(request["states"])
    planned, destinations = [], set()
    for state in states:
        if state not in request["states"]:
            raise SystemExit(f"unknown state: {state}")
        default_count = int(request["states"][state]["frames"])
        ordered, transforms = state_plan(curation, state, default_count)
        indices = ordered if args.selected_only else list(range(default_count))
        labels = labels_by_state.get(state, [])
        multi_state = len(states) > 1
        for index in indices:
            src_path = resolve_run_path(run_dir, f"frames/{state}/frame-{index}.png")
            if not src_path.is_file():
                raise SystemExit(f"missing frame: {src_path}")
            name = labels[index] if index < len(labels) and labels[index] else f"frame-{index}"
            filename = f"{state}-{name}.png" if multi_state else f"{name}.png"
            if "/" in filename or "\\" in filename:
                raise SystemExit("export labels must be filenames, not paths")
            try:
                dest = resolve_run_path(out_dir, filename)
            except PathSafetyError as exc:
                raise SystemExit(str(exc)) from exc
            if dest in protected or dest in destinations:
                raise SystemExit(f"export destination replaces a source or duplicates another output: {dest}")
            destinations.add(dest)
            planned.append((src_path, dest, transforms.get(index)))

    meta_output = resolve_run_path(out_dir, "meta.json") if source_meta and planned else None
    if meta_output in protected:
        raise SystemExit("export metadata cannot replace its source")
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise SystemExit(f"cannot create output dir {out_dir}: {exc}")
    if not os.access(out_dir, os.W_OK):
        raise SystemExit(f"output dir not writable: {out_dir}")
    written = []
    for src_path, dest, transform in planned:
        with Image.open(src_path) as opened:
            baked = apply_transform(opened.convert("RGBA"), transform, cell_size, policy=resize_policy)
        atomic_save_image(baked, dest)
        written.append(str(dest))
    if meta_output:
        shutil.copy2(source_meta, meta_output)

    print(json.dumps({
        "ok": True,
        "out_dir": str(out_dir),
        "count": len(written),
        "files": written,
        "meta_copied": str(meta_output) if meta_output else None,
        "note": "Exported PNG copies; source artifacts were preserved.",
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
