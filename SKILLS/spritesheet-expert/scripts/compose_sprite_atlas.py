#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Compose component-row frames into a game atlas and runtime manifest."""

from __future__ import annotations

import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from PIL import Image

from curation import apply_transform, load_curation, state_plan
from runio import acquire_run_dir_lock, atomic_save_image, atomic_write_text
from spritecore.contracts import ContractError, validate_contract
from spritecore.image_ops import (
    ArtMode,
    ResizePolicy,
    resize_policy_from_sampling_policy,
    validate_frame,
)


FULL_CELL_ASSET_KINDS = {"tileset", "texture", "ui"}
SUPPORTED_OUTPUT_FORMATS = {"png", "webp"}


def alpha_nonzero_count(image: Image.Image) -> int:
    return sum(image.getchannel("A").histogram()[1:])


def cell_geometry(cell: dict[str, Any]) -> tuple[int, int]:
    width = int(cell.get("width", cell.get("size", 0)))
    height = int(cell.get("height", cell.get("size", 0)))
    if width <= 0 or height <= 0:
        raise SystemExit("cell width/height must be positive in sprite-request.json")
    return width, height


def resize_policy_for_request(request: dict[str, Any]) -> ResizePolicy:
    sampling_policy = request.get("sampling_policy")
    if isinstance(sampling_policy, dict):
        return resize_policy_from_sampling_policy(sampling_policy)
    art_direction = request.get("art_direction")
    is_pixel = request.get("style_preset") == "pixel-art" or (
        isinstance(art_direction, dict) and art_direction.get("mode") == "pixel-art"
    )
    return ResizePolicy(mode=ArtMode.PIXEL if is_pixel else ArtMode.ILLUSTRATED)


def output_formats_for_request(request: dict[str, Any]) -> list[str]:
    output = request.get("output")
    raw_formats = output.get("formats") if isinstance(output, dict) else None
    if raw_formats is None:
        preset = request.get("preset")
        raw_formats = preset.get("formats") if isinstance(preset, dict) else None
    if raw_formats is None:
        return ["png"]
    if not isinstance(raw_formats, list) or not raw_formats:
        raise SystemExit("output.formats must be a non-empty list")
    formats: list[str] = []
    for value in raw_formats:
        fmt = str(value).strip().lower()
        if fmt not in SUPPORTED_OUTPUT_FORMATS:
            raise SystemExit(f"unsupported output format: {value!r}")
        if fmt not in formats:
            formats.append(fmt)
    return formats


def output_path_for_format(atlas_name: str, fmt: str) -> Path:
    atlas_path = Path(atlas_name)
    return atlas_path if atlas_path.suffix.lower() == f".{fmt}" else atlas_path.with_suffix(f".{fmt}")


def output_metadata(path: Path, relative_path: Path, *, lossless: bool) -> dict[str, Any]:
    return {
        "path": relative_path.as_posix(),
        "sha256": sha256(path.read_bytes()).hexdigest(),
        "size_bytes": path.stat().st_size,
        "lossless": lossless,
    }


def atlas_packing_for_request(request: dict[str, Any]) -> tuple[int, int]:
    output = request.get("output")
    output = output if isinstance(output, dict) else {}
    values = []
    for key in ("atlas_gutter", "atlas_extrusion"):
        value = output.get(key, 0)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise SystemExit(f"output.{key} must be a non-negative integer")
        values.append(value)
    return values[0], values[1]


def composite_with_extrusion(
    atlas: Image.Image,
    frame: Image.Image,
    left: int,
    top: int,
    extrusion: int,
) -> None:
    if extrusion:
        width, height = frame.size
        nearest = Image.Resampling.NEAREST
        atlas.alpha_composite(
            frame.crop((0, 0, width, 1)).resize((width, extrusion), nearest),
            (left, top - extrusion),
        )
        atlas.alpha_composite(
            frame.crop((0, height - 1, width, height)).resize(
                (width, extrusion), nearest
            ),
            (left, top + height),
        )
        atlas.alpha_composite(
            frame.crop((0, 0, 1, height)).resize((extrusion, height), nearest),
            (left - extrusion, top),
        )
        atlas.alpha_composite(
            frame.crop((width - 1, 0, width, height)).resize(
                (extrusion, height), nearest
            ),
            (left + width, top),
        )
        corners = (
            ((0, 0, 1, 1), (left - extrusion, top - extrusion)),
            ((width - 1, 0, width, 1), (left + width, top - extrusion)),
            ((0, height - 1, 1, height), (left - extrusion, top + height)),
            (
                (width - 1, height - 1, width, height),
                (left + width, top + height),
            ),
        )
        for crop, position in corners:
            atlas.alpha_composite(
                frame.crop(crop).resize((extrusion, extrusion), nearest), position
            )
    atlas.alpha_composite(frame, (left, top))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--atlas", default="sprite-sheet-alpha.png")
    parser.add_argument("--manifest", default="manifest.json")
    parser.add_argument("--report", default="sprite-sheet-alpha.report.json")
    parser.add_argument(
        "--min-used-pixels",
        type=int,
        default=None,
        help="legacy fixed-pixel minimum; default validation is scale-aware",
    )
    args = parser.parse_args()

    run_dir = args.run_dir.expanduser().resolve()
    acquire_run_dir_lock(run_dir, "compose_sprite_atlas")
    request = json.loads((run_dir / "sprite-request.json").read_text(encoding="utf-8"))
    if request.get("asset_kind") == "vfx":
        try:
            request = validate_contract(
                request, expected_kind="sprite-request"
            ).to_dict()
        except ContractError as exc:
            raise SystemExit(str(exc)) from exc
    frames_manifest = json.loads((run_dir / "frames" / "frames-manifest.json").read_text(encoding="utf-8"))
    if not frames_manifest.get("ok"):
        raise SystemExit("frames-manifest.json is not ok; fix extraction before composing atlas")

    states = list(request["states"])
    cell_width, cell_height = cell_geometry(request["cell"])
    cell_size = (cell_width, cell_height)
    resize_policy = resize_policy_for_request(request)
    allow_full_cell = request.get("asset_kind") in FULL_CELL_ASSET_KINDS
    output_formats = output_formats_for_request(request)
    atlas_gutter, atlas_extrusion = atlas_packing_for_request(request)

    # curation.json is an optional non-destructive sidecar. When absent, every
    # state uses all extracted frames in order with identity transform.
    curation = load_curation(run_dir)
    plans = {
        state: state_plan(curation, state, int(request["states"][state]["frames"]))
        for state in states
    }

    max_frames = max(len(ordered) for ordered, _transforms in plans.values())
    atlas_padding = atlas_gutter + atlas_extrusion
    slot_width = cell_width + atlas_padding * 2
    slot_height = cell_height + atlas_padding * 2
    atlas = Image.new(
        "RGBA",
        (max_frames * slot_width, len(states) * slot_height),
        (0, 0, 0, 0),
    )
    frame_layout: dict[str, Any] = {
        "sheetWidth": atlas.width,
        "sheetHeight": atlas.height,
        "cellWidth": cell_width,
        "cellHeight": cell_height,
        "rows": {},
    }
    if atlas_padding:
        frame_layout["packing"] = {
            "atlas_gutter": atlas_gutter,
            "atlas_extrusion": atlas_extrusion,
            "slotWidth": slot_width,
            "slotHeight": slot_height,
            "runtimeRects": "interior-cells",
            "extrusionMode": "edge-duplicate",
        }
    animation: dict[str, Any] = {
        "cellWidth": cell_width,
        "cellHeight": cell_height,
        "columns": max_frames,
        "rows": {},
    }
    errors: list[str] = []
    cells: list[dict[str, Any]] = []

    for row_index, state in enumerate(states):
        entry = request["states"][state]
        ordered, transforms = plans[state]
        frames = []
        for column, frame_index in enumerate(ordered):
            frame_path = run_dir / "frames" / state / f"frame-{frame_index}.png"
            if not frame_path.is_file():
                errors.append(f"missing frame: {frame_path}")
                continue
            with Image.open(frame_path) as opened:
                source = opened.convert("RGBA")
            if source.size != cell_size:
                errors.append(f"{frame_path} is {source.width}x{source.height}; expected {cell_width}x{cell_height}")
            # apply the human curation transform (identity when uncurated)
            frame = apply_transform(
                source,
                transforms.get(frame_index),
                cell_size,
                policy=resize_policy,
            )
            nontransparent = alpha_nonzero_count(frame)
            validation = validate_frame(frame, allow_full_cell=allow_full_cell)
            errors.extend(
                f"{state} frame {frame_index}: {failure}"
                for failure in validation.failures
            )
            if args.min_used_pixels is not None and nontransparent < args.min_used_pixels:
                errors.append(f"{state} frame {frame_index} is too sparse ({nontransparent})")
            left = column * slot_width + atlas_padding
            top = row_index * slot_height + atlas_padding
            composite_with_extrusion(atlas, frame, left, top, atlas_extrusion)
            rect = {"x": left, "y": top, "w": cell_width, "h": cell_height}
            frames.append(rect)
            cells.append(
                {
                    "state": state,
                    "frame": frame_index,
                    "nontransparent_pixels": nontransparent,
                    "validation_profile": validation.profile.name,
                    "allow_full_cell": allow_full_cell,
                    "validation_warnings": list(validation.warnings),
                    **rect,
                }
            )

        frame_layout["rows"][state] = frames
        animation["rows"][state] = {
            "row": row_index,
            "frames": len(ordered),
            "fps": int(entry.get("fps", 6)),
            "loop": bool(entry.get("loop", True)),
        }
        if "durations_ms" in entry:
            animation["rows"][state]["durations_ms"] = entry["durations_ms"]
        if request.get("asset_kind") == "vfx":
            runtime_vfx = deepcopy(entry["vfx"])
            runtime_vfx["phase_sequence"] = [
                entry["vfx"]["phase_sequence"][frame_index]
                for frame_index in ordered
            ]
            animation["rows"][state]["vfx"] = runtime_vfx

    report = {
        "ok": not errors,
        "engine": "component-row",
        "curation_applied": curation is not None,
        "errors": errors,
        "atlas": args.atlas,
        "manifest": args.manifest,
        "cell": request["cell"],
        "states": states,
        "cells": cells,
        "frame_layout": frame_layout,
    }

    report_path = run_dir / args.report
    if errors:
        atomic_write_text(report_path, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps({k: v for k, v in report.items() if k != "cells"}, ensure_ascii=False, indent=2))
        return 1

    output_paths: dict[str, tuple[Path, Path]] = {}
    atlas_outputs: dict[str, dict[str, Any]] = {}
    for fmt in output_formats:
        relative_path = output_path_for_format(args.atlas, fmt)
        atlas_path = run_dir / relative_path
        atlas_path.parent.mkdir(parents=True, exist_ok=True)
        save_kwargs = {"lossless": True, "method": 6} if fmt == "webp" else {}
        atomic_save_image(atlas, atlas_path, **save_kwargs)
        output_paths[fmt] = (atlas_path, relative_path)
        atlas_outputs[fmt] = output_metadata(
            atlas_path, relative_path, lossless=True
        )
    primary_format = "png" if "png" in output_paths else output_formats[0]
    atlas_path, primary_relative_path = output_paths[primary_format]
    report["atlas"] = primary_relative_path.as_posix()
    report["atlas_outputs"] = atlas_outputs
    atomic_write_text(report_path, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    manifest = {
        "characterId": request["character"]["id"],
        "engine": "component-row",
        "game_input": primary_relative_path.as_posix(),
        "degraded_static_fallback": False,
        "curation_applied": curation is not None,
        "sprite_sheet_alpha": primary_relative_path.as_posix(),
        "sprite_sheet_alpha_report": args.report,
        "atlas_outputs": atlas_outputs,
        "base_image": request["character"].get("base_image"),
        "cell": request["cell"],
        "chroma_key": request["chroma_key"],
        "animation": animation,
        "frame_layout": frame_layout,
    }
    for key in ("preset", "output", "asset_kind", "extraction_mode", "frame_budget", "background_removal", "asset_catalog", "iso", "tile"):
        if key in request:
            manifest[key] = request[key]
    atomic_write_text(run_dir / args.manifest, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                "ok": True,
                "atlas": str(atlas_path),
                "atlas_outputs": atlas_outputs,
                "manifest": str(run_dir / args.manifest),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
