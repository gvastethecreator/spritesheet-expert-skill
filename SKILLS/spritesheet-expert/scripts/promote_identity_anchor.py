#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Promote a generated row frame into the canonical identity anchor."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from extract_sprite_row_frames import (
    DEFAULT_REMBG_MODEL,
    cell_geometry,
    extract_component_sprites,
    extract_slot_sprites,
    fit_to_cell,
    remove_background,
)
from runio import atomic_save_image, atomic_write_text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--state", default="idle")
    parser.add_argument("--frame", type=int, default=0)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--allow-slot-fallback", action="store_true")
    parser.add_argument("--key-threshold", type=float, default=96.0)
    parser.add_argument("--fringe-key-threshold", type=float, default=180.0)
    parser.add_argument("--fringe-delta", type=float, default=18.0)
    args = parser.parse_args()

    run_dir = args.run_dir.expanduser().resolve()
    request = json.loads((run_dir / "sprite-request.json").read_text(encoding="utf-8"))
    state_entry = request["states"].get(args.state)
    if state_entry is None:
        raise SystemExit(f"unknown state {args.state!r}")
    frame_count = int(state_entry["frames"])
    if args.frame < 0 or args.frame >= frame_count:
        raise SystemExit(f"--frame must be between 0 and {frame_count - 1}")

    raw_path = run_dir / "raw" / f"{args.state}.png"
    if not raw_path.is_file():
        raise SystemExit(f"missing raw strip: {raw_path}")

    chroma_key = tuple(int(value) for value in request["chroma_key"]["rgb"])
    background_config = request.get("background_removal")
    if not isinstance(background_config, dict):
        background_config = {"method": "chroma", "model": DEFAULT_REMBG_MODEL, "device": "auto", "alpha_matting": False}
    background_args = SimpleNamespace(
        key_threshold=args.key_threshold,
        fringe_key_threshold=args.fringe_key_threshold,
        fringe_delta=args.fringe_delta,
        matte_threshold=float(background_config.get("matte_threshold", 28.0)),
        matte_max_colors=int(background_config.get("matte_max_colors", 8)),
        edge_refine=str(background_config.get("edge_refine", "conservative")),
        edge_refine_threshold=float(background_config.get("edge_refine_threshold", 36.0)),
        edge_refine_feather=float(background_config.get("edge_refine_feather", 36.0)),
        edge_refine_passes=int(background_config.get("edge_refine_passes", 1)),
    )
    with Image.open(raw_path) as opened:
        strip, background_method = remove_background(opened, chroma_key, background_config, background_args, {})

    sprites = extract_component_sprites(strip, frame_count)
    method = "components"
    if sprites is None:
        if not args.allow_slot_fallback:
            raise SystemExit(f"could not extract {frame_count} sprite components from {raw_path}")
        sprites = extract_slot_sprites(strip, frame_count)
        method = "slots-explicit"

    cell_width, cell_height, safe_margin_x, safe_margin_y = cell_geometry(request["cell"])
    anchor = fit_to_cell(sprites[args.frame], cell_width, cell_height, safe_margin_x, safe_margin_y)
    out_path = args.out or run_dir / "references" / "identity-anchor.png"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_save_image(anchor, out_path)

    sidecar = {
        "state": args.state,
        "frame": args.frame,
        "source": str(raw_path.relative_to(run_dir)),
        "output": str(out_path.relative_to(run_dir)),
        "method": method,
        "background_method": background_method,
        "cell": request["cell"],
    }
    atomic_write_text(out_path.with_suffix(".json"), json.dumps(sidecar, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"ok": True, "anchor": str(out_path), **sidecar}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
