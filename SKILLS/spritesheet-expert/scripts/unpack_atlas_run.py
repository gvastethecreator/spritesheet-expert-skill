#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Unpack a composed sprite sheet back into a curator-ready run directory.

This is the inverse of `compose_sprite_atlas.py`. When only the combined
`sprite-sheet-alpha.png` (+ optional manifest) survives — for example a deployed
asset whose original `frames/` source is gone — this rebuilds the per-frame
editable representation so the curation webview can open it.

Layout source priority (explicit wins, auto-detect is the no-instruction
default — and the chosen path is always reported, never silent):

  1. --boxes-file <json>      reviewed authored source rectangles.
  2. --grid <cols>x<rows>     a human said the grid; slice uniform cells (position-faithful).
  3. --projection-grid CxR    split expected rows by alpha projection + DP repair.
  4. --manifest <json>        read exact frame rectangles from the manifest.
  5. auto-detect (default)    matte the sheet when needed, then detect content blobs.

Output (a normal sprite-gen run dir):

  <out-dir>/
    sprite-request.json        synthesized recipe (fps/loop are defaults unless a manifest had them)
    frames/<state>/frame-N.png
    frames/frames-manifest.json
    qa/segmentation-*.json/png import-cut QA before registration
    unpack-source.json         provenance + original manifest format, for a future writeback

Then: serve_curation.py --run-dir <out-dir>
"""

from __future__ import annotations

import argparse
import atexit
from hashlib import sha256
from io import BytesIO
import json
import re
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from extract_sprite_row_frames import (
    DEFAULT_BEN2_MODEL,
    DEFAULT_LUCIDA_INPUT_SIZE,
    DEFAULT_LUCIDA_MODEL,
    DEFAULT_LUCIDA_REVISION,
    DEFAULT_REMBG_MODEL,
    default_background_model,
    default_background_revision,
    remove_background,
)
from runio import atomic_save_image, atomic_write_bytes, atomic_write_text
from segmentation import projection_spans
from spritecore.contracts import ContractError, normalize_contract
from spritecore.models import is_state_slug
from spritecore.locks import RunLock, RunLockError, acquire_run_lock
from spritecore.paths import PathSafetyError, create_run_marker, remove_known_outputs, resolve_run_path

ALPHA_THRESHOLD = 16  # a pixel counts as content above this alpha
MIN_GUTTER = 1        # a fully-empty line of >= this many px separates frames
BACKGROUND_REMOVAL_METHODS = {
    "none",
    "auto",
    "chroma",
    "matte",
    "rembg",
    "ben2",
    "lucida",
}
UNPACK_KNOWN_OUTPUTS = (
    "frames",
    "qa",
    "sprite-request.json",
    "unpack-source.json",
    "source-provenance.json",
    "manifest.json",
)


def parse_hex_color(value: str) -> tuple[int, int, int]:
    value = value.strip()
    if value.startswith("#"):
        value = value[1:]
    if len(value) != 6:
        raise SystemExit("chroma key must be #RRGGBB")
    try:
        return tuple(int(value[index : index + 2], 16) for index in (0, 2, 4))
    except ValueError as exc:
        raise SystemExit("chroma key must be #RRGGBB") from exc


def chroma_key_doc(rgb: tuple[int, int, int]) -> dict[str, Any]:
    return {
        "name": "custom",
        "hex": f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}",
        "rgb": list(rgb),
    }


def chroma_key_from_manifest(manifest: dict[str, Any] | None, fallback: tuple[int, int, int]) -> tuple[int, int, int]:
    if not isinstance(manifest, dict):
        return fallback
    raw = manifest.get("chroma_key")
    if isinstance(raw, dict) and isinstance(raw.get("rgb"), list) and len(raw["rgb"]) == 3:
        return tuple(int(value) for value in raw["rgb"])
    return fallback


def preprocess_atlas_background(
    atlas: Image.Image,
    mode: str,
    chroma_key: tuple[int, int, int],
    args: argparse.Namespace,
) -> tuple[Image.Image, str, dict[str, Any]]:
    rgba = atlas.convert("RGBA")
    revision = args.background_revision or default_background_revision(mode)
    if mode == "lucida" and (
        not isinstance(revision, str)
        or re.fullmatch(r"[0-9a-f]{40}", revision) is None
    ):
        raise SystemExit(
            "--background-revision must be a 40-character lowercase commit SHA for Lucida"
        )
    input_size = args.background_input_size or (
        DEFAULT_LUCIDA_INPUT_SIZE if mode == "lucida" else None
    )
    if mode == "lucida" and not 256 <= input_size <= 2048:
        raise SystemExit("--background-input-size must be from 256 to 2048")
    if args.hard_alpha_threshold is not None and not 1 <= args.hard_alpha_threshold <= 255:
        raise SystemExit("--hard-alpha-threshold must be from 1 to 255")
    config = {
        "method": mode,
        "model": args.background_model or default_background_model(mode),
        "device": args.background_device or "auto",
        "alpha_matting": bool(args.alpha_matting),
        "alpha_mode": args.alpha_mode or "soft",
        "hard_alpha_threshold": args.hard_alpha_threshold,
        "post_rembg_chroma_cleanup": bool(args.post_rembg_chroma_cleanup),
        "matte_threshold": args.matte_threshold,
        "matte_max_colors": args.matte_max_colors,
        "edge_refine": args.edge_refine,
        "edge_refine_threshold": args.edge_refine_threshold,
        "edge_refine_feather": args.edge_refine_feather,
        "edge_refine_passes": args.edge_refine_passes,
        "chroma_mask": "border-connected",
        "chroma_matte": "soft-edge-despill",
        "matte_mask": "edge-palette-border-connected",
    }
    if mode == "lucida":
        config["revision"] = revision
        config["input_size"] = input_size
    if mode == "none":
        return rgba, "preserved", config
    processed, method = remove_background(rgba, chroma_key, config, args, {})
    return processed, method, config


def segmentation_report_rows(states: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for state in states:
        rects = [
            {"x": int(x), "y": int(y), "w": int(w), "h": int(h)}
            for x, y, w, h in state["rects"]
        ]
        widths = [rect["w"] for rect in rects]
        heights = [rect["h"] for rect in rects]
        rows.append(
            {
                "state": state["name"],
                "frames": len(rects),
                "rects": rects,
                "width_range": [min(widths), max(widths)] if widths else [0, 0],
                "height_range": [min(heights), max(heights)] if heights else [0, 0],
                "segmentation": state.get("segmentation"),
            }
        )
    return rows


def segmentation_warnings(states: list[dict[str, Any]], expected_names: list[str] | None, layout_source: str) -> list[str]:
    warnings: list[str] = []
    if layout_source == "auto-detect":
        warnings.append(
            "auto-detect content boxes are diagnostic; production cuts require a trusted manifest, explicit grid, or reviewed authored boxes"
        )
    if expected_names and len(states) != len(expected_names):
        warnings.append(f"detected {len(states)} rows but {len(expected_names)} state names were provided")
    frame_counts = [len(state["rects"]) for state in states]
    if frame_counts and len(set(frame_counts)) > 1:
        warnings.append(f"detected uneven frame counts by row: {frame_counts}")
    for state in states:
        widths = [rect[2] for rect in state["rects"]]
        heights = [rect[3] for rect in state["rects"]]
        if widths and max(widths) > max(1, min(widths)) * 1.8:
            warnings.append(f"{state['name']}: frame widths vary strongly; inspect segmentation overlay")
        if heights and max(heights) > max(1, min(heights)) * 1.8:
            warnings.append(f"{state['name']}: frame heights vary strongly; inspect segmentation overlay")
    return warnings


def make_segmentation_overlay(
    atlas: Image.Image,
    states: list[dict[str, Any]],
    out_dir: Path,
    layout_source: str,
    background_method: str,
) -> str:
    qa_dir = out_dir / "qa"
    qa_dir.mkdir(parents=True, exist_ok=True)
    max_preview_w = 1400
    scale = min(1.0, max_preview_w / max(1, atlas.width))
    preview = atlas.convert("RGBA")
    if scale < 1.0:
        preview = preview.resize((round(atlas.width * scale), round(atlas.height * scale)), Image.Resampling.LANCZOS)
    try:
        font = ImageFont.truetype("arial.ttf", 14)
        small = ImageFont.truetype("arial.ttf", 11)
    except Exception:
        font = None
        small = None
    caption = f"segmentation: {layout_source}; background: {background_method}"
    header = 36
    caption_width = ImageDraw.Draw(preview).textbbox((0, 0), caption, font=font)[2] + 20
    overlay = Image.new("RGBA", (max(preview.width, caption_width), preview.height + header), (17, 17, 17, 255))
    overlay.alpha_composite(preview, (0, header))
    draw = ImageDraw.Draw(overlay, "RGBA")
    colors = [
        (220, 220, 220, 230),
        (245, 158, 11, 230),
        (132, 204, 22, 230),
        (244, 114, 182, 230),
        (196, 181, 253, 230),
    ]
    draw.text((10, 8), caption, fill=(235, 235, 235, 255), font=font)
    for row_index, state in enumerate(states):
        color = colors[row_index % len(colors)]
        for frame_index, (x, y, w, h) in enumerate(state["rects"]):
            box = (
                round(x * scale),
                round(y * scale) + header,
                round((x + w) * scale),
                round((y + h) * scale) + header,
            )
            draw.rectangle(box, outline=color, width=2)
            draw.text((box[0] + 4, box[1] + 4), f"{state['name']} f{frame_index + 1}", fill=color, font=small)
    path = qa_dir / "segmentation-overlay.png"
    atomic_save_image(overlay, path)
    return str(path.relative_to(out_dir))


def write_segmentation_report(
    out_dir: Path,
    atlas: Image.Image,
    states: list[dict[str, Any]],
    cell: tuple[int, int],
    layout_source: str,
    background_method: str,
    background_config: dict[str, Any],
    expected_names: list[str] | None,
    extra_warnings: list[str] | None = None,
    diagnostic: bool = False,
) -> tuple[str, list[str]]:
    overlay = make_segmentation_overlay(atlas, states, out_dir, layout_source, background_method)
    warnings = segmentation_warnings(states, expected_names, layout_source)
    if extra_warnings:
        warnings.extend(extra_warnings)
    trusted_layout = layout_source in {"authored-boxes", "grid-explicit", "manifest"}
    report = {
        "ok": not warnings,
        "engine": "sprite-sheet-segmentation",
        "layout_source": layout_source,
        "background_method": background_method,
        "background_removal": background_config,
        "cell": {"width": cell[0], "height": cell[1]},
        "overlay": overlay,
        "diagnostic": diagnostic,
        "production_eligible": trusted_layout and not warnings and not diagnostic,
        "warnings": warnings,
        "rows": segmentation_report_rows(states),
    }
    atomic_write_text(out_dir / "qa" / "segmentation-report.json", json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return overlay, warnings


# --- auto-detect (visual blob clustering) -----------------------------------

def _components(mask: list[bool], w: int, h: int, min_area: int) -> list[tuple[int, int, int, int]]:
    """4-neighbour connected components over a boolean mask -> list of bboxes."""
    visited = bytearray(len(mask))
    boxes: list[tuple[int, int, int, int]] = []
    for seed in range(len(mask)):
        if not mask[seed] or visited[seed]:
            continue
        stack = [seed]
        visited[seed] = 1
        minx = miny = 1 << 30
        maxx = maxy = -1
        area = 0
        while stack:
            cur = stack.pop()
            area += 1
            x, y = cur % w, cur // w
            minx, miny, maxx, maxy = min(minx, x), min(miny, y), max(maxx, x), max(maxy, y)
            if x > 0 and mask[cur - 1] and not visited[cur - 1]:
                visited[cur - 1] = 1; stack.append(cur - 1)
            if x < w - 1 and mask[cur + 1] and not visited[cur + 1]:
                visited[cur + 1] = 1; stack.append(cur + 1)
            if y > 0 and mask[cur - w] and not visited[cur - w]:
                visited[cur - w] = 1; stack.append(cur - w)
            if y < h - 1 and mask[cur + w] and not visited[cur + w]:
                visited[cur + w] = 1; stack.append(cur + w)
        if area >= min_area:
            boxes.append((minx, miny, maxx + 1, maxy + 1))
    return boxes


def auto_detect(atlas: Image.Image) -> tuple[list[dict[str, Any]], tuple[int, int]]:
    """Read the sheet visually: find content blobs, cluster them into a grid.

    Blobs are clustered into rows by vertical center, then into frames by
    horizontal overlap. Touching poses can merge and detached parts can split;
    review the diagnostic overlay before authoring production rectangles.

    Returns (states, cell_size). Each frame rect is the blob's content bbox;
    write_run centers it in the cell.
    """
    scale = max(1, max(atlas.width, atlas.height) // 600)  # downsample for speed
    sw, sh = atlas.width // scale, atlas.height // scale
    small = atlas.getchannel("A").resize((sw, sh), Image.BILINEAR)
    mask = [b > ALPHA_THRESHOLD for b in small.tobytes()]  # 'L' mode: 1 byte/px
    boxes_small = _components(mask, sw, sh, min_area=max(6, (sw * sh) // 4000))
    if not boxes_small:
        raise SystemExit("auto-detect found no content blobs in the atlas")

    # map blob bboxes back to full resolution
    boxes = [(x0 * scale, y0 * scale, x1 * scale, y1 * scale) for (x0, y0, x1, y1) in boxes_small]
    heights = sorted(y1 - y0 for _x0, y0, _x1, y1 in boxes)
    widths = sorted(x1 - x0 for x0, _y0, x1, _y1 in boxes)
    med_h = heights[len(heights) // 2]
    med_w = widths[len(widths) // 2]

    # cluster into rows by vertical center
    boxes.sort(key=lambda b: (b[1] + b[3]) / 2)
    rows: list[list[tuple[int, int, int, int]]] = []
    row_tol = med_h * 0.6
    for box in boxes:
        cy = (box[1] + box[3]) / 2
        if rows and abs(cy - sum((b[1] + b[3]) / 2 for b in rows[-1]) / len(rows[-1])) <= row_tol:
            rows[-1].append(box)
        else:
            rows.append([box])

    states: list[dict[str, Any]] = []
    max_w = max_h = 0
    for row_index, row_boxes in enumerate(rows):
        row_boxes.sort(key=lambda b: b[0])
        # merge horizontally overlapping / near blobs into one frame
        frames: list[list[int]] = []
        gap = med_w * 0.3
        for box in row_boxes:
            if frames and box[0] - frames[-1][2] <= gap:
                f = frames[-1]
                f[0], f[1] = min(f[0], box[0]), min(f[1], box[1])
                f[2], f[3] = max(f[2], box[2]), max(f[3], box[3])
            else:
                frames.append(list(box))
        rects = []
        for f in frames:
            rect = (f[0], f[1], f[2] - f[0], f[3] - f[1])
            rects.append(rect)
            max_w, max_h = max(max_w, rect[2]), max(max_h, rect[3])
        if rects:
            states.append({"name": f"row-{row_index}", "rects": rects})

    if max_w == 0 or max_h == 0:
        raise SystemExit("auto-detect could not size any frame")
    cell = (max_w + 8, max_h + 8)  # pad so centered content is not flush to the edge
    return states, cell


# --- explicit layout sources ------------------------------------------------

def grid_layout(atlas: Image.Image, cols: int, rows: int) -> tuple[list[dict[str, Any]], tuple[int, int]]:
    cell_w = atlas.width // cols
    cell_h = atlas.height // rows
    states = []
    for r in range(rows):
        rects = []
        for c in range(cols):
            rect = (c * cell_w, r * cell_h, cell_w, cell_h)
            rects.append(rect)
        states.append({"name": f"row-{r}", "rects": rects})
    return states, (cell_w, cell_h)


def projection_grid_layout(atlas: Image.Image, cols: int, rows: int) -> tuple[list[dict[str, Any]], tuple[int, int], list[str]]:
    states: list[dict[str, Any]] = []
    warnings: list[str] = []
    max_w = 1
    max_h = 1
    for row_index in range(rows):
        top = round(row_index * atlas.height / rows)
        bottom = round((row_index + 1) * atlas.height / rows)
        row_image = atlas.crop((0, top, atlas.width, bottom))
        spans, report = projection_spans(row_image, cols, "x")
        if len(spans) != cols:
            warnings.append(f"row-{row_index}: projection produced {len(spans)} spans for expected {cols}")
            spans = []
        row_rects = []
        for span in spans:
            rect = (span.start, top, span.width, bottom - top)
            row_rects.append(rect)
            max_w = max(max_w, rect[2])
            max_h = max(max_h, rect[3])
        if row_rects:
            state = {"name": f"row-{row_index}", "rects": row_rects, "segmentation": report}
            states.append(state)
            for warning in report.get("warnings", []):
                warnings.append(f"row-{row_index}: {warning}")
    return states, (max_w + 8, max_h), warnings


def _rect_from_json(value: Any) -> tuple[int, int, int, int]:
    if isinstance(value, dict):
        value = [value.get(key) for key in ("x", "y", "w", "h")]
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise SystemExit("rectangles must be {x,y,w,h} objects or [x,y,w,h] arrays")
    x, y, w, h = (_integer(item, "rectangle coordinate", minimum=0) for item in value)
    if not w or not h:
        raise SystemExit("rectangle width and height must be positive")
    return x, y, w, h


def _integer(value: Any, name: str, *, minimum: int = 1) -> int:
    if type(value) is not int or value < minimum:
        raise SystemExit(f"{name} must be an integer >= {minimum}")
    return value


def authored_boxes_layout(data: dict[str, Any]) -> tuple[list[dict[str, Any]], tuple[int, int], dict[str, Any]]:
    raw_rows = data.get("rows")
    states: list[dict[str, Any]] = []
    meta: dict[str, Any] = {}
    if isinstance(raw_rows, list):
        for index, row in enumerate(raw_rows):
            if not isinstance(row, dict):
                raise SystemExit("boxes-file rows must be objects")
            name = row.get("state", row.get("name", f"row-{index}"))
            if not is_state_slug(name):
                raise SystemExit(f"invalid state id: {name!r}")
            rects = [_rect_from_json(rect) for rect in row.get("rects", [])]
            if rects:
                states.append({"name": name, "rects": rects})
                meta[name] = {key: row[key] for key in ("fps", "loop", "action", "animation_workflows") if key in row}
    else:
        for name, rects_raw in data.items():
            if name in {"cell", "meta", "kind", "version"}:
                continue
            if isinstance(rects_raw, list):
                rects = [_rect_from_json(rect) for rect in rects_raw]
                if rects:
                    states.append({"name": name, "rects": rects})
    if not states:
        raise SystemExit("boxes-file did not contain any rects")
    cell_raw = data.get("cell") if isinstance(data.get("cell"), dict) else {}
    cell_w = _integer(cell_raw.get("width", cell_raw.get("w", max(rect[2] for state in states for rect in state["rects"]))), "cell width")
    cell_h = _integer(cell_raw.get("height", cell_raw.get("h", max(rect[3] for state in states for rect in state["rects"]))), "cell height")
    return states, (cell_w, cell_h), meta


def manifest_layout(
    manifest: dict[str, Any],
    direction: str | None,
    cell_override: tuple[int, int] | None = None,
) -> tuple[list[dict[str, Any]], tuple[int, int], str, dict[str, Any]]:
    """Resolve frame rectangles from a known manifest format.

    Returns (states, cell, atlas_filename, per_state_meta).
    """
    cell = manifest.get("cell", {})
    cell_w = cell.get("width", cell.get("size", 0))
    cell_h = cell.get("height", cell.get("size", 0))
    if cell_override:
        cell_w, cell_h = cell_override

    # compose-format: explicit frame_layout rectangles
    if "frame_layout" in manifest and manifest["frame_layout"].get("rows"):
        fl = manifest["frame_layout"]
        cell_w = cell_w or fl.get("cellWidth", 0)
        cell_h = cell_h or fl.get("cellHeight", 0)
        states = []
        meta = {}
        anim = manifest.get("animation", {}).get("rows", {})
        for state, rects in fl["rows"].items():
            states.append({"name": state, "rects": [_rect_from_json(r) for r in rects]})
            row_anim = anim.get(state, {})
            meta[state] = {"fps": row_anim.get("fps", 6), "loop": row_anim.get("loop", True)}
            for key in ("action", "animation_workflows"):
                if key in row_anim:
                    meta[state][key] = row_anim[key]
        atlas_file = manifest.get("game_input") or manifest.get("sprite_sheet_alpha")
        return states, (cell_w, cell_h), atlas_file, meta

    # archive-2dir-mirror / grid-row format: rows carry {row, frames, fps, loop}
    rows_src = None
    atlas_file = None
    if "directions" in manifest:
        directions = manifest["directions"]
        chosen = direction or next(iter(directions))
        if chosen not in directions:
            raise SystemExit(f"direction '{chosen}' not in manifest; have {list(directions)}")
        rows_src = directions[chosen]["rows"]
        atlas_file = directions[chosen]["sprite_sheet"]
    elif manifest.get("animation", {}).get("rows"):
        rows_src = {k: v for k, v in manifest["animation"]["rows"].items()}
        atlas_file = manifest.get("game_input") or manifest.get("sprite_sheet_alpha")

    if not rows_src:
        raise SystemExit("manifest has no frame_layout, directions, or animation rows to read")
    if not (cell_w and cell_h):
        raise SystemExit("manifest cell width/height missing; pass --cell WxH")
    cell_w, cell_h = _integer(cell_w, "cell width"), _integer(cell_h, "cell height")

    states = []
    meta = {}
    for state, info in rows_src.items():
        row = _integer(info["row"], "row index", minimum=0)
        frames = _integer(info["frames"], "frame count")
        rects = [(c * cell_w, row * cell_h, cell_w, cell_h) for c in range(frames)]
        states.append({"name": state, "rects": rects})
        meta[state] = {key: info[key] for key in ("fps", "loop", "action", "animation_workflows") if key in info}
    return states, (cell_w, cell_h), atlas_file, meta


# --- writing ----------------------------------------------------------------

def prepare_output(out_dir: Path, force: bool, input_paths: list[Path]) -> RunLock:
    """Take ownership and the writer lock only after input validation succeeds."""
    inputs = {path.resolve() for path in input_paths}
    outputs = [name for name in UNPACK_KNOWN_OUTPUTS
               if not (name == "manifest.json" and (out_dir / name).resolve() in inputs)]
    for name in outputs:
        target = (out_dir / name).resolve()
        if any(path == target or path.is_relative_to(target) for path in inputs):
            raise SystemExit(f"input overlaps output {name}; choose another --out-dir")
    if out_dir.exists() and any(path.name != ".sprite-gen-run.json" for path in out_dir.iterdir()) and not force:
        raise SystemExit(f"out-dir not empty: {out_dir} (use --force)")
    try:
        create_run_marker(out_dir, run_id=out_dir.name)
    except PathSafetyError as exc:
        raise SystemExit(f"cannot use run marker: {exc}") from exc
    lease = acquire_run_lock(out_dir, "unpack_atlas_run")
    try:
        if force:
            remove_known_outputs(out_dir, outputs)
    except BaseException:
        lease.release()
        raise
    return lease


def write_run(
    out_dir: Path,
    atlas: Image.Image,
    states: list[dict[str, Any]],
    cell: tuple[int, int],
    meta: dict[str, Any],
    layout_source: str,
    provenance: dict[str, Any],
    *,
    force: bool = False,
    input_paths: list[Path] | None = None,
) -> dict[str, Any]:
    invalid_states = [state.get("name") for state in states if not is_state_slug(state.get("name"))]
    if invalid_states:
        raise SystemExit(f"invalid state ids in imported layout: {invalid_states}")
    names = [state["name"] for state in states]
    if not names or len(names) != len(set(names)):
        raise SystemExit("imported layout must have distinct, non-empty states")
    cell_w, cell_h = (_integer(value, "cell dimension") for value in cell)
    for state in states:
        rects = [_rect_from_json(rect) for rect in state["rects"]]
        if not rects:
            raise SystemExit(f"state {state['name']} has no frames")
        for x, y, w, h in rects:
            if x + w > atlas.width or y + h > atlas.height:
                raise SystemExit(f"rectangle outside atlas bounds in {state['name']}: {(x, y, w, h)}")
            if w > cell_w or h > cell_h:
                raise SystemExit(f"rectangle exceeds target cell in {state['name']}")
    frames_root = out_dir / "frames"
    chroma_key = provenance.get("chroma_key")
    if not isinstance(chroma_key, dict):
        chroma_key = {"name": "magenta", "hex": "#FF00FF", "rgb": [255, 0, 255]}

    request_states = {}
    semantics = provenance.get("frame_semantics") or ("variants" if any(state.get("labels") for state in states)
        else "animation" if provenance.get("asset_kind", "sprite") == "sprite" else "still-assets")
    temporal = semantics in {"animation", "effects"}
    manifest_rows = []
    for state in states:
        name = state["name"]
        labels = state.get("labels", [])
        if "labels" in state and (not isinstance(labels, list) or len(labels) != len(state["rects"])
                                   or any(not isinstance(label, str) or not label.strip() for label in labels)):
            raise SystemExit(f"{name}: asset labels must contain one non-empty string per frame")
        state_dir = frames_root / name
        files = [(state_dir / f"frame-{index}.png").relative_to(out_dir).as_posix() for index in range(len(state["rects"]))]
        m = meta.get(name, {})
        request_states[name] = {
            "frames": len(state["rects"]),
            "fps": m.get("fps", 6) if temporal else 1,
            "loop": m.get("loop", True) if temporal else False,
            "action": m.get("action", ""),
        }
        if temporal and m.get("animation_workflows"):
            if not isinstance(m["animation_workflows"], list) or any(not isinstance(value, str) for value in m["animation_workflows"]):
                raise SystemExit(f"{name}: animation_workflows must be a list of strings")
            request_states[name]["animation_workflows"] = m["animation_workflows"]
        if labels:
            request_states[name]["asset_labels"] = labels
        row_record = {"state": name, "frames": len(state["rects"]), "method": "unpacked", "files": files, "ok": True}
        if labels:
            row_record["labels"] = labels
        manifest_rows.append(row_record)

    request = {
        "version": 1,
        "kind": "sprite-gen-request",
        "engine": "component-row",
        "asset_kind": provenance.get("asset_kind", "sprite"),
        "frame_semantics": semantics,
        "extraction_mode": provenance.get("extraction_mode", "components"),
        "character": {"id": out_dir.name, "description": f"unpacked from atlas ({layout_source})"},
        "cell": {"shape": "rect" if cell_w != cell_h else "square", "width": cell_w, "height": cell_h, "size": cell_w, "safe_margin": 0},
        "chroma_key": chroma_key,
        "states": request_states,
    }
    if isinstance(provenance.get("background_removal"), dict):
        request["background_removal"] = provenance["background_removal"]
    if isinstance(provenance.get("asset_catalog"), dict):
        request["asset_catalog"] = provenance["asset_catalog"]
    try:
        request = normalize_contract(request, expected_kind="sprite-request").to_dict()
    except ContractError as exc:
        raise SystemExit(str(exc)) from exc
    lease = prepare_output(out_dir, force, input_paths or [])
    # The CLI still writes QA and source evidence after this frame writer.
    atexit.register(lease.release)
    for state in states:
        state_dir = frames_root / state["name"]
        state_dir.mkdir(parents=True, exist_ok=True)
        for index, (x, y, w, h) in enumerate(state["rects"]):
            crop = atlas.crop((x, y, x + w, y + h)).convert("RGBA")
            framed = crop
            if crop.size != (cell_w, cell_h):
                framed = Image.new("RGBA", (cell_w, cell_h), (0, 0, 0, 0))
                framed.alpha_composite(crop, ((cell_w - w) // 2, (cell_h - h) // 2))
            atomic_save_image(framed, state_dir / f"frame-{index}.png")
    atomic_write_text(out_dir / "sprite-request.json", json.dumps(request, ensure_ascii=False, indent=2) + "\n")
    atomic_write_text(
        frames_root / "frames-manifest.json",
        json.dumps({"ok": True, "engine": "component-row", "run_dir": str(out_dir), "cell": request["cell"], "rows": manifest_rows, "errors": [], "warnings": provenance.get("segmentation_warnings", [])}, ensure_ascii=False, indent=2) + "\n",
    )
    source_doc = {
        "version": 1,
        "kind": "sprite-gen-unpack-source",
        "layout_source": layout_source,
        "cell": {"width": cell_w, "height": cell_h},
        **provenance,
    }
    atomic_write_text(out_dir / "unpack-source.json", json.dumps(source_doc, ensure_ascii=False, indent=2) + "\n")
    return {"layout_source": layout_source, "states": [s["name"] for s in states], "cell": [cell_w, cell_h]}


def import_pngs(out_dir: Path, png_paths: list[Path], state_name: str, labels: list[str], iso: dict[str, Any] | None = None, source_type: str = "imported", *, force: bool = False, input_paths: list[Path] | None = None) -> dict[str, Any]:
    """Import a folder of separate PNGs as one state's frames (e.g. furniture set).

    Each PNG becomes one frame so they can be compared side by side and given a
    per-item transform in the curator. Originals are copied, not modified.
    """
    if not is_state_slug(state_name):
        raise SystemExit(f"invalid state id {state_name!r}; use a 1-64 character lowercase kebab slug")
    if not png_paths or not isinstance(labels, list) or len(labels) != len(png_paths) or any(not isinstance(label, str) or not label.strip() for label in labels):
        raise SystemExit("PNG imports require one non-empty label per image")
    if source_type not in {"imported", "fixture"}:
        raise SystemExit("PNG imports must declare source_type imported or fixture")
    payloads = [path.read_bytes() for path in png_paths]
    imgs = []
    for payload in payloads:
        with Image.open(BytesIO(payload)) as image:
            imgs.append(image.convert("RGBA"))
    cell_w = max(i.width for i in imgs)
    cell_h = max(i.height for i in imgs)
    state_dir = out_dir / "frames" / state_name
    files = [f"frames/{state_name}/frame-{index}.png" for index in range(len(imgs))]
    snapshots = [resolve_run_path(out_dir, f"source/imported-{index:04d}.png") for index in range(len(imgs))]
    inputs = {path.resolve() for path in png_paths}
    for target, payload in zip(snapshots, payloads):
        if target in inputs and target.read_bytes() != payload:
            raise SystemExit("source snapshot would overwrite an input; choose another --out-dir")

    request = {
        "version": 1,
        "kind": "sprite-gen-request",
        "engine": "component-row",
        "asset_kind": "asset",
        "frame_semantics": "still-assets",
        "extraction_mode": "slots",
        "character": {"id": out_dir.name, "description": f"imported PNG set from {png_paths[0].parent}"},
        "cell": {"shape": "square" if cell_w == cell_h else "rect", "width": cell_w, "height": cell_h, "size": cell_w, "safe_margin": 0},
        "chroma_key": {"name": "magenta", "hex": "#FF00FF", "rgb": [255, 0, 255]},
        "states": {state_name: {"frames": len(imgs), "fps": 1, "loop": False, "action": "imported still set", "asset_labels": labels}},
    }
    if iso:
        request["iso"] = iso  # ground-grid geometry for the curator overlay
    try:
        request = normalize_contract(request, expected_kind="sprite-request").to_dict()
    except ContractError as exc:
        raise SystemExit(str(exc)) from exc
    with prepare_output(out_dir, force, [*png_paths, *(input_paths or [])]):
        state_dir.mkdir(parents=True, exist_ok=True)
        for index, im in enumerate(imgs):
            framed = im
            if im.size != (cell_w, cell_h):
                framed = Image.new("RGBA", (cell_w, cell_h), (0, 0, 0, 0))
                framed.alpha_composite(im, ((cell_w - im.width) // 2, (cell_h - im.height) // 2))
            atomic_save_image(framed, state_dir / f"frame-{index}.png")
        atomic_write_text(out_dir / "sprite-request.json", json.dumps(request, ensure_ascii=False, indent=2) + "\n")
        atomic_write_text(
            out_dir / "frames" / "frames-manifest.json",
            json.dumps({"ok": True, "engine": "component-row", "run_dir": str(out_dir), "cell": request["cell"],
                        "rows": [{"state": state_name, "frames": len(imgs), "method": "imported-pngs", "files": files, "labels": labels, "ok": True}],
                        "errors": [], "warnings": []}, ensure_ascii=False, indent=2) + "\n",
        )
        atomic_write_text(
            out_dir / "unpack-source.json",
            json.dumps({"version": 1, "kind": "sprite-gen-unpack-source", "layout_source": "imported-pngs",
                        "cell": {"width": cell_w, "height": cell_h}, "source_dir": str(png_paths[0].parent),
                        "files": [p.name for p in png_paths], "labels": labels}, ensure_ascii=False, indent=2) + "\n",
        )
        accepted = []
        for index, payload in enumerate(payloads):
            relative = f"source/imported-{index:04d}.png"
            target = snapshots[index]
            target.parent.mkdir(exist_ok=True)
            if target not in inputs:
                atomic_write_bytes(target, payload)
            accepted.append({"path": relative, "sha256": sha256(payload).hexdigest(), "size_bytes": len(payload), "states": [state_name]})
        atomic_write_text(out_dir / "source-provenance.json", json.dumps({"version": 2, "kind": "sprite-source-provenance",
            "source_type": source_type, "art_engine": source_type, "fixture": source_type == "fixture",
            "verification_status": "verified", "state_coverage": [state_name], "accepted_sources": accepted}, indent=2) + "\n")
        return {"layout_source": "imported-pngs", "states": [state_name], "cell": [cell_w, cell_h], "frames": len(imgs)}


def parse_grid(value: str) -> tuple[int, int]:
    if re.fullmatch(r"[1-9][0-9]*[xX][1-9][0-9]*", value) is None:
        raise argparse.ArgumentTypeError("expected positive integer dimensions, e.g. 8x4")
    cols, rows = value.lower().split("x")
    return int(cols), int(rows)


def load_asset_labels(path: Path | None) -> dict[str, list[str]]:
    if not path:
        return {}
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise SystemExit("--asset-labels-file must be a JSON object")
    labels: dict[str, list[str]] = {}
    for state, values in data.items():
        if not isinstance(values, list):
            raise SystemExit(f"asset labels for {state!r} must be a list")
        labels[state] = values
    return labels


def load_asset_catalog(path: Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict) or not isinstance(data.get("items"), dict):
        raise SystemExit("--asset-catalog-file must be a JSON object with an items object")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--atlas", type=Path, help="sprite sheet PNG (or use --manifest)")
    parser.add_argument("--manifest", type=Path, help="manifest JSON with frame layout")
    parser.add_argument("--boxes-file", type=Path, help="authored source rectangles JSON; use after manual review fixes bad cuts")
    parser.add_argument("--pngs-dir", type=Path, help="folder of separate PNGs to import as one state's frames")
    parser.add_argument("--state-name", default="items", help="state name for --pngs-dir import")
    parser.add_argument("--out-dir", type=Path, help="run dir for output; defaults to a '<source>-curator' folder next to the input so it is easy to find")
    parser.add_argument("--grid", type=parse_grid, help="explicit COLSxROWS, for example 8x9")
    parser.add_argument("--projection-grid", type=parse_grid, help="expected COLSxROWS; split each row by alpha projection and DP repair")
    parser.add_argument("--cell", type=parse_grid, help="explicit cell WxH (for manifests missing cell size)")
    parser.add_argument("--direction", help="which direction to unpack from a multi-direction manifest")
    parser.add_argument("--states", help="comma-separated state names to override detected/row names")
    parser.add_argument("--asset-kind", choices=["sprite", "tileset", "texture", "asset", "prop", "props", "icon", "ui", "vfx"], help="asset kind for synthesized sprite-request.json")
    parser.add_argument("--source-type", choices=["imported", "fixture"], default="imported", help="declare test fixtures explicitly; imported media is not provider-generated art")
    parser.add_argument("--frame-semantics", choices=["animation", "effects", "variants", "still-assets", "tiles", "seamless-textures"], help="explicit temporal or static meaning of imported slots")
    parser.add_argument("--extraction-mode", choices=["components", "slots"], help="extraction mode for synthesized sprite-request.json")
    parser.add_argument("--asset-labels-file", type=Path, help="JSON object mapping state name to per-slot asset labels")
    parser.add_argument("--asset-catalog-file", type=Path, help="JSON asset_catalog with items metadata for runtime naming/pivots/categories")
    parser.add_argument("--auto", action="store_true", help="force alpha auto-detect even if a manifest is given")
    parser.add_argument(
        "--diagnostic",
        action="store_true",
        help="allow untrusted/failed segmentation for review; its report cannot satisfy production validation",
    )
    parser.add_argument(
        "--background-removal",
        choices=sorted(BACKGROUND_REMOVAL_METHODS),
        default=None,
        help="background matte before segmentation; default is auto for alpha auto-detect, none for explicit grid/manifest",
    )
    parser.add_argument(
        "--background-model",
        default=None,
        help=(
            f"model name; lucida default {DEFAULT_LUCIDA_MODEL}; "
            f"rembg default {DEFAULT_REMBG_MODEL}; ben2 default {DEFAULT_BEN2_MODEL}"
        ),
    )
    parser.add_argument(
        "--background-revision",
        default=None,
        help=f"immutable model commit SHA; Lucida default {DEFAULT_LUCIDA_REVISION}",
    )
    parser.add_argument("--background-input-size", type=int, default=None)
    parser.add_argument("--background-device", default=None, help="model-backed background removal device: auto, cpu, cuda, cuda:0, etc.")
    parser.add_argument("--alpha-matting", action="store_true")
    parser.add_argument("--alpha-mode", choices=["soft", "hard"], default=None)
    parser.add_argument("--hard-alpha-threshold", type=int, default=None)
    parser.add_argument("--post-rembg-chroma-cleanup", action="store_true", help="after rembg, also run conservative border-connected chroma cleanup; off by default to avoid subject over-removal")
    parser.add_argument("--chroma-key", default="#FF00FF")
    parser.add_argument("--key-threshold", type=float, default=96.0)
    parser.add_argument("--fringe-key-threshold", type=float, default=180.0)
    parser.add_argument("--fringe-delta", type=float, default=18.0)
    parser.add_argument("--matte-threshold", type=float, default=28.0)
    parser.add_argument("--matte-max-colors", type=int, default=8)
    parser.add_argument("--edge-refine", choices=["off", "conservative"], default="conservative")
    parser.add_argument("--edge-refine-threshold", type=float, default=36.0)
    parser.add_argument("--edge-refine-feather", type=float, default=36.0)
    parser.add_argument("--edge-refine-passes", type=int, default=1)
    parser.add_argument("--force", action="store_true", help="overwrite an existing out-dir")
    args = parser.parse_args()
    if args.fringe_key_threshold < args.key_threshold:
        raise SystemExit("--fringe-key-threshold must be greater than or equal to --key-threshold")

    for attribute in ("atlas", "manifest", "boxes_file", "asset_labels_file", "asset_catalog_file"):
        source = getattr(args, attribute)
        if source is None:
            continue
        resolved = source.expanduser().resolve()
        if not resolved.is_file():
            raise SystemExit(f"missing --{attribute.replace('_', '-')} file: {resolved}")
        setattr(args, attribute, resolved)
    if args.pngs_dir is not None:
        args.pngs_dir = args.pngs_dir.expanduser().resolve()
        if not args.pngs_dir.is_dir():
            raise SystemExit(f"missing --pngs-dir directory: {args.pngs_dir}")

    # default the run dir to a clearly-findable sibling next to the input.
    if args.out_dir:
        out_dir = args.out_dir.expanduser().resolve()
    else:
        if args.pngs_dir:
            base = args.pngs_dir.expanduser().resolve()
            out_dir = base.parent / f"{base.name}-curator"
        elif args.atlas:
            base = args.atlas.expanduser().resolve()
            out_dir = base.parent / f"{base.stem}-curator"
        elif args.boxes_file:
            base = args.boxes_file.expanduser().resolve()
            out_dir = base.parent / f"{base.stem}-curator"
        elif args.manifest:
            base = args.manifest.expanduser().resolve()
            out_dir = base.parent / f"{base.stem}-curator"
        else:
            raise SystemExit("need one of --pngs-dir / --atlas / --manifest / --boxes-file (or pass --out-dir)")

    input_paths = [getattr(args, name) for name in ("atlas", "manifest", "boxes_file", "asset_labels_file", "asset_catalog_file")
                   if getattr(args, name) is not None]

    # --pngs-dir: import a folder of separate PNGs (e.g. a furniture set)
    if args.pngs_dir:
        src = args.pngs_dir.expanduser().resolve()
        png_paths = sorted(p for p in src.glob("*.png"))
        if not png_paths:
            raise SystemExit(f"no PNGs in {src}")
        # prefer human names from a sibling meta.json (file -> item name), else filename stem
        labels = [p.stem for p in png_paths]
        iso = None
        meta_path = src / "meta.json"
        if meta_path.is_file():
            input_paths.append(meta_path)
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            file_to_name = {info.get("file"): name for name, info in meta.get("items", {}).items() if isinstance(info, dict)}
            labels = [file_to_name.get(p.name, p.stem) for p in png_paths]
            tile = meta.get("tile")
            anchor = meta.get("anchor")
            if tile and anchor:
                iso = {
                    "tile": {"width": int(tile["width"]), "height": int(tile["height"])},
                    "projection": tile.get("projection", "2:1 dimetric diamond"),
                    "anchor_pixel": anchor.get("pixel", [128, 222]),
                    "canvas": meta.get("style", {}).get("canvas", [256, 256]),
                }
        result = import_pngs(out_dir, png_paths, args.state_name, labels, iso, args.source_type,
                             force=args.force, input_paths=input_paths)
        result["ok"] = True
        result["out_dir"] = str(out_dir)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    manifest = json.loads(args.manifest.read_text(encoding="utf-8")) if args.manifest else None
    boxes = json.loads(args.boxes_file.read_text(encoding="utf-8-sig")) if args.boxes_file else None
    if args.manifest and not isinstance(manifest, dict):
        raise SystemExit("manifest must be a JSON object")
    if args.boxes_file and not isinstance(boxes, dict):
        raise SystemExit("boxes-file must be a JSON object")
    chroma_rgb = chroma_key_from_manifest(manifest, parse_hex_color(args.chroma_key))
    provenance: dict[str, Any] = {
        "atlas": str(args.atlas) if args.atlas else None,
        "manifest": str(args.manifest) if args.manifest else None,
        "boxes_file": str(args.boxes_file) if args.boxes_file else None,
        "direction": args.direction,
        "chroma_key": chroma_key_doc(chroma_rgb),
    }
    layout_warnings: list[str] = []
    if args.asset_kind:
        provenance["asset_kind"] = args.asset_kind
    if args.extraction_mode:
        provenance["extraction_mode"] = args.extraction_mode
    elif args.asset_kind and args.asset_kind != "sprite":
        provenance["extraction_mode"] = "slots"
    asset_catalog = load_asset_catalog(args.asset_catalog_file)
    if asset_catalog:
        provenance["asset_catalog"] = asset_catalog

    # resolve layout + atlas image
    atlas_path = args.atlas
    meta: dict[str, Any] = {}
    uses_visual_auto_detect = bool(args.projection_grid or (not args.grid and not boxes and not (manifest and not args.auto)))
    background_mode = args.background_removal or ("auto" if uses_visual_auto_detect else "none")
    if not boxes and not args.grid and not args.projection_grid and manifest and not args.auto:
        states, cell, atlas_name, meta = manifest_layout(manifest, args.direction, args.cell)
        for key in ("asset_kind", "extraction_mode"):
            if key in manifest:
                provenance[key] = manifest[key]
        if not atlas_path:
            atlas_path = (args.manifest.parent / atlas_name) if atlas_name else None
    if not atlas_path or not Path(atlas_path).is_file():
        raise SystemExit("could not locate atlas image; pass --atlas or a manifest with an image path")
    atlas_path = Path(atlas_path).resolve()
    input_paths.append(atlas_path)
    original_bytes = atlas_path.read_bytes()
    with Image.open(BytesIO(original_bytes)) as image:
        source_atlas = image.convert("RGBA")
    atlas, background_method, background_config = preprocess_atlas_background(source_atlas, background_mode, chroma_rgb, args)
    source_snapshot = resolve_run_path(out_dir, "source/imported-atlas.png")
    if source_snapshot in {path.resolve() for path in input_paths} and source_snapshot.read_bytes() != original_bytes:
        raise SystemExit("source snapshot would overwrite an input; choose another --out-dir")
    if boxes:
        layout_source = "authored-boxes"
        states, cell, meta = authored_boxes_layout(boxes)
    elif args.grid:
        layout_source = "grid-explicit"
        cols, grid_rows = args.grid
        if source_atlas.width % cols or source_atlas.height % grid_rows:
            layout_warnings.append(
                f"explicit grid {cols}x{grid_rows} does not divide source {source_atlas.width}x{source_atlas.height}; "
                "crop/resize or provide authored boxes before production slicing"
            )
        states, cell = grid_layout(atlas, *args.grid)
    elif args.projection_grid:
        layout_source = "projection-grid"
        states, cell, projection_warnings = projection_grid_layout(atlas, *args.projection_grid)
        layout_warnings.extend(projection_warnings)
    elif manifest and not args.auto:
        layout_source = "manifest"
    else:
        layout_source = "auto-detect"
        states, cell = auto_detect(atlas)

    expected_names = [name.strip() for name in args.states.split(",")] if args.states else None
    if args.states:
        renamed_meta = {}
        for i, name in enumerate(expected_names or []):
            if i < len(states):
                renamed_meta[name] = meta.get(states[i]["name"], {})
                states[i]["name"] = name
        meta.update(renamed_meta)
    asset_labels = load_asset_labels(args.asset_labels_file)
    for state in states:
        labels = asset_labels.get(state["name"])
        if labels is not None:
            state["labels"] = labels
    provenance["asset_labels_file"] = str(args.asset_labels_file) if args.asset_labels_file else None
    provenance["asset_catalog_file"] = str(args.asset_catalog_file) if args.asset_catalog_file else None

    provenance["atlas"] = str(atlas_path)
    provenance["background_method"] = background_method
    provenance["background_removal"] = background_config
    provenance["segmentation_overlay"] = "qa/segmentation-overlay.png"
    provenance["segmentation_warnings"] = segmentation_warnings(states, expected_names, layout_source) + layout_warnings
    provenance["frame_semantics"] = args.frame_semantics or (manifest or {}).get("frame_semantics")
    if background_mode != "none":
        provenance["preprocessed_atlas"] = "qa/preprocessed-atlas-alpha.png"
    result = write_run(out_dir, atlas, states, cell, meta, layout_source, provenance,
                       force=args.force, input_paths=input_paths)
    if background_mode != "none":
        qa_dir = out_dir / "qa"
        qa_dir.mkdir(parents=True, exist_ok=True)
        preprocessed = qa_dir / "preprocessed-atlas-alpha.png"
        atomic_save_image(atlas, preprocessed)
    segmentation_overlay, warnings = write_segmentation_report(
        out_dir,
        atlas,
        states,
        cell,
        layout_source,
        background_method,
        background_config,
        expected_names,
        layout_warnings,
        args.diagnostic,
    )
    source_snapshot.parent.mkdir(exist_ok=True)
    if source_snapshot != atlas_path:
        atomic_write_bytes(source_snapshot, original_bytes)
    covered_states = [state["name"] for state in states]
    atomic_write_text(out_dir / "source-provenance.json", json.dumps({"version": 2,
        "kind": "sprite-source-provenance", "source_type": args.source_type, "art_engine": args.source_type,
        "fixture": args.source_type == "fixture", "verification_status": "verified", "state_coverage": covered_states,
        "accepted_sources": [{"path": "source/imported-atlas.png", "sha256": sha256(original_bytes).hexdigest(),
            "size_bytes": len(original_bytes), "states": covered_states}]}, indent=2) + "\n")
    result["ok"] = not warnings
    result["segmentation_ok"] = not warnings
    result["out_dir"] = str(out_dir)
    result["background_method"] = background_method
    result["segmentation_overlay"] = segmentation_overlay
    result["segmentation_warnings"] = warnings
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.diagnostic:
        return 0
    if warnings:
        return 1
    if layout_source in {"auto-detect", "projection-grid"}:
        return 2
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RunLockError) as exc:
        raise SystemExit(f"cannot unpack atlas: {exc}") from exc
