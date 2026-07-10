#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""QA gate for tileset/asset slot naming, bounds, pivots, and review overlays."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from runio import atomic_save_image, atomic_write_text
from spritecore.image_ops import (
    ArtMode,
    inspect_hard_alpha,
    resize_policy_from_sampling_policy,
    validate_frame,
)


ASSET_KINDS = {"tileset", "texture", "asset", "prop", "props", "icon", "ui", "vfx"}
FULL_CELL_KINDS = {"tileset", "texture"}
PROP_STRATEGY_CLASSES = {
    "compact_prop",
    "wide_or_long_object",
    "tall_or_large_object",
    "collision_bearing_object",
    "tileset_or_strip_piece",
}
SQUARE_PACK_FORBIDDEN = {
    "wide_or_long_object",
    "tall_or_large_object",
    "collision_bearing_object",
    "tileset_or_strip_piece",
}
LABEL_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
GENERIC_LABEL_RE = re.compile(r"^(row|frame|slot|asset|item|tile|prop)-?\d*$")


def alpha_nonzero_count(image: Image.Image) -> int:
    return sum(image.convert("RGBA").getchannel("A").histogram()[1:])


def edge_alpha_count(image: Image.Image, margin: int) -> int:
    alpha = image.convert("RGBA").getchannel("A")
    width, height = image.size
    boxes = (
        (0, 0, width, margin),
        (0, height - margin, width, height),
        (0, 0, margin, height),
        (width - margin, 0, width, height),
    )
    return sum(sum(alpha.crop(box).histogram()[1:]) for box in boxes)


def cell_geometry(cell: dict[str, Any]) -> tuple[int, int]:
    width = int(cell.get("width", cell.get("size", 0)))
    height = int(cell.get("height", cell.get("size", 0)))
    if width <= 0 or height <= 0:
        raise SystemExit("sprite-request.json cell width/height must be positive")
    return width, height


def row_labels(request: dict[str, Any], row: dict[str, Any]) -> list[str]:
    state = str(row["state"])
    entry = request.get("states", {}).get(state, {})
    for source in (row, entry):
        for key in ("labels", "asset_labels", "asset_names"):
            raw = source.get(key) if isinstance(source, dict) else None
            if isinstance(raw, list):
                return [str(item) for item in raw]
    return []


def catalog_items(request: dict[str, Any]) -> dict[str, dict[str, Any]]:
    catalog = request.get("asset_catalog")
    if not isinstance(catalog, dict):
        return {}
    items = catalog.get("items")
    if not isinstance(items, dict):
        return {}
    return {str(key): value for key, value in items.items() if isinstance(value, dict)}


def pivot_ok(value: Any) -> bool:
    return isinstance(value, list) and len(value) == 2 and all(isinstance(item, (int, float)) for item in value)


def strategy_class(meta: dict[str, Any]) -> str | None:
    raw = meta.get("strategy_class") or meta.get("asset_strategy") or meta.get("object_class")
    return str(raw) if isinstance(raw, str) and raw else None


def label_errors(label: str) -> list[str]:
    errors = []
    if not LABEL_RE.fullmatch(label):
        errors.append(f"{label}: label must be kebab-case")
    if GENERIC_LABEL_RE.fullmatch(label):
        errors.append(f"{label}: label is generic; use a runtime asset name")
    return errors


def make_overlay(
    run_dir: Path,
    rows: list[dict[str, Any]],
    cell_size: tuple[int, int],
    records: list[dict[str, Any]],
) -> str:
    cell_w, cell_h = cell_size
    label_h = 18
    gutter = 8
    max_frames = max((int(row.get("frames", 0)) for row in rows), default=1)
    width = max_frames * (cell_w + gutter) + gutter
    height = len(rows) * (cell_h + label_h + gutter) + gutter
    overlay = Image.new("RGBA", (max(1, width), max(1, height)), (8, 8, 8, 255))
    draw = ImageDraw.Draw(overlay)
    by_state_frame = {(item["state"], item["frame"]): item for item in records}
    for row_index, row in enumerate(rows):
        state = str(row["state"])
        y = gutter + row_index * (cell_h + label_h + gutter)
        draw.text((gutter, y), state, fill=(235, 235, 235, 255))
        files = row.get("files", [])
        for frame_index, rel in enumerate(files):
            x = gutter + frame_index * (cell_w + gutter)
            with Image.open(run_dir / rel) as opened:
                frame = opened.convert("RGBA")
            tile = Image.new("RGBA", (cell_w, cell_h), (18, 18, 18, 255))
            tile.alpha_composite(frame)
            overlay.alpha_composite(tile, (x, y + label_h))
            rec = by_state_frame.get((state, frame_index), {})
            label = str(rec.get("label", f"frame-{frame_index}"))
            color = (132, 204, 22, 255) if rec.get("ok") else (248, 113, 113, 255)
            draw.rectangle((x, y + label_h, x + cell_w, y + label_h + cell_h), outline=color, width=1)
            bbox = rec.get("bbox")
            if bbox:
                bx0, by0, bx1, by1 = bbox
                draw.rectangle((x + bx0, y + label_h + by0, x + bx1, y + label_h + by1), outline=(80, 190, 255, 220), width=1)
            pivot = rec.get("pivot")
            if isinstance(pivot, list) and len(pivot) == 2:
                px, py = int(pivot[0]), int(pivot[1])
                draw.line((x + px - 4, y + label_h + py, x + px + 4, y + label_h + py), fill=(245, 158, 11, 255))
                draw.line((x + px, y + label_h + py - 4, x + px, y + label_h + py + 4), fill=(245, 158, 11, 255))
            draw.text((x + 2, y + label_h + 2), label[:24], fill=color)
    out = run_dir / "qa" / "asset-slot-overlay.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    atomic_save_image(overlay, out)
    return str(out.relative_to(run_dir))


def make_tile_repeat_review(run_dir: Path, rows: list[dict[str, Any]], cell_size: tuple[int, int]) -> str | None:
    samples: list[tuple[str, Image.Image]] = []
    for row in rows:
        for rel in row.get("files", [])[:2]:
            with Image.open(run_dir / rel) as opened:
                samples.append((str(row["state"]), opened.convert("RGBA")))
            if len(samples) >= 6:
                break
        if len(samples) >= 6:
            break
    if not samples:
        return None
    cell_w, cell_h = cell_size
    scale = 3
    gutter = 10
    label_h = 18
    panel_w = cell_w * scale
    panel_h = cell_h * scale + label_h
    cols = min(3, len(samples))
    rows_count = (len(samples) + cols - 1) // cols
    review = Image.new("RGBA", (cols * (panel_w + gutter) + gutter, rows_count * (panel_h + gutter) + gutter), (8, 8, 8, 255))
    draw = ImageDraw.Draw(review)
    for index, (label, sample) in enumerate(samples):
        col = index % cols
        row = index // cols
        x0 = gutter + col * (panel_w + gutter)
        y0 = gutter + row * (panel_h + gutter)
        draw.text((x0, y0), label, fill=(235, 235, 235, 255))
        for ty in range(scale):
            for tx in range(scale):
                review.alpha_composite(sample, (x0 + tx * cell_w, y0 + label_h + ty * cell_h))
        draw.rectangle((x0, y0 + label_h, x0 + panel_w, y0 + label_h + cell_h * scale), outline=(80, 190, 255, 180), width=1)
    out = run_dir / "qa" / "tile-repeat-review.png"
    atomic_save_image(review, out)
    return str(out.relative_to(run_dir))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument(
        "--min-used-pixels",
        type=int,
        default=None,
        help="explicit absolute sparse-slot override; default uses scale-aware profiles",
    )
    parser.add_argument("--edge-margin", type=int, default=2)
    parser.add_argument(
        "--max-prop-edge-pixels",
        type=int,
        default=None,
        help="explicit legacy edge-pixel override; default uses normalized edge contact",
    )
    parser.add_argument("--strict-catalog", action="store_true", default=True)
    parser.add_argument("--no-strict-catalog", dest="strict_catalog", action="store_false")
    args = parser.parse_args()

    run_dir = args.run_dir.expanduser().resolve()
    request = json.loads((run_dir / "sprite-request.json").read_text(encoding="utf-8"))
    frames_manifest = json.loads((run_dir / "frames" / "frames-manifest.json").read_text(encoding="utf-8"))
    asset_kind = str(request.get("asset_kind", "sprite"))
    resize_policy = resize_policy_from_sampling_policy(request.get("sampling_policy"))
    cell_size = cell_geometry(request["cell"])
    cell_w, cell_h = cell_size
    square_like_cell = abs((cell_w / max(1, cell_h)) - 1.0) <= 0.25
    rows = frames_manifest.get("rows", [])
    if asset_kind not in ASSET_KINDS:
        raise SystemExit(f"check_asset_slots.py is for non-sprite asset modes, got {asset_kind!r}")

    errors: list[str] = []
    warnings: list[str] = []
    records: list[dict[str, Any]] = []
    seen_labels: set[str] = set()
    if frames_manifest.get("ok") is not True:
        errors.append("frames/frames-manifest.json is missing ok:true")
    catalog = catalog_items(request)
    if args.strict_catalog and not catalog:
        errors.append("missing sprite-request.json.asset_catalog.items; asset sheets need reviewed runtime metadata")
    request_states = request.get("states", {})
    if not isinstance(request_states, dict) or not request_states:
        errors.append("sprite-request.json.states must be a non-empty object")
    expected_states = set(request_states) if isinstance(request_states, dict) else set()
    checked_states = {
        str(row.get("state", "")) for row in rows if isinstance(row, dict)
    }
    for state in sorted(expected_states - checked_states):
        errors.append(f"{state}: expected request state has no frames-manifest row")

    for row in rows:
        state = str(row["state"])
        files = [str(path) for path in row.get("files", [])]
        labels = row_labels(request, row)
        if not labels:
            errors.append(f"{state}: missing per-slot asset_labels")
            labels = [f"{state}-{index}" for index in range(len(files))]
        if len(labels) != len(files):
            errors.append(f"{state}: {len(labels)} labels for {len(files)} slots")
        for index, rel in enumerate(files):
            label = labels[index] if index < len(labels) else f"{state}-{index}"
            item_errors = label_errors(label)
            if label in seen_labels:
                item_errors.append(f"{label}: duplicate label")
            seen_labels.add(label)
            meta = catalog.get(label, {})
            if args.strict_catalog:
                if label not in catalog:
                    item_errors.append(f"{label}: missing asset_catalog item metadata")
                else:
                    if not meta.get("category"):
                        item_errors.append(f"{label}: missing catalog category")
                    if not pivot_ok(meta.get("pivot")):
                        item_errors.append(f"{label}: missing catalog pivot [x,y]")
                    if asset_kind == "tileset" and not (meta.get("tile_role") or meta.get("edge_role") or meta.get("collision")):
                        item_errors.append(f"{label}: tileset catalog item needs tile_role, edge_role, or collision")
                    if asset_kind in {"asset", "prop", "props"}:
                        strategy = strategy_class(meta)
                        if strategy not in PROP_STRATEGY_CLASSES:
                            item_errors.append(f"{label}: missing/invalid strategy_class; classify compact_prop, wide_or_long_object, tall_or_large_object, collision_bearing_object, or tileset_or_strip_piece")
                        elif square_like_cell and strategy in SQUARE_PACK_FORBIDDEN:
                            item_errors.append(f"{label}: strategy_class {strategy} cannot be approved inside a square compact prop pack; regenerate as one-by-one, strip, custom wide cell, or tileset")
            frame_path = run_dir / rel
            with Image.open(frame_path) as opened:
                frame = opened.convert("RGBA")
            bbox = frame.getbbox()
            nontransparent = alpha_nonzero_count(frame)
            edge_pixels = edge_alpha_count(frame, args.edge_margin)
            validation = validate_frame(
                frame,
                allow_full_cell=asset_kind in FULL_CELL_KINDS,
            )
            if resize_policy.mode is ArtMode.PIXEL:
                alpha_invariant = inspect_hard_alpha(frame)
                if not alpha_invariant.ok:
                    item_errors.append(
                        f"{label}: alpha invariant violation: "
                        f"{len(alpha_invariant.new_fractional_alpha_values)} "
                        "fractional alpha values"
                    )
            if args.min_used_pixels is not None:
                if nontransparent < args.min_used_pixels:
                    item_errors.append(
                        f"{label}: empty or too sparse ({nontransparent} pixels)"
                    )
            profile_failures = validation.failures
            item_errors.extend(f"{label}: {failure}" for failure in profile_failures)
            if (
                args.max_prop_edge_pixels is not None
                and asset_kind not in FULL_CELL_KINDS
                and edge_pixels > args.max_prop_edge_pixels
            ):
                item_errors.append(
                    f"{label}: {edge_pixels} non-transparent edge pixels; "
                    "probable clipping or slot bleed"
                )
            edge_touch = (
                edge_pixels > args.max_prop_edge_pixels
                if args.max_prop_edge_pixels is not None
                else validation.metrics.edge_contact_pixels > 0
            )
            occupancy = round(nontransparent / max(1, frame.width * frame.height), 4)
            if asset_kind in {"icon", "ui"} and occupancy < 0.05:
                warnings.append(f"{label}: icon occupancy is very small; review readability")
            record = {
                "state": state,
                "frame": index,
                "label": label,
                "file": rel,
                "bbox": list(bbox) if bbox else None,
                "suggested_pivot": [round((bbox[0] + bbox[2]) / 2), bbox[3]] if bbox else None,
                "pivot": meta.get("pivot"),
                "category": meta.get("category"),
                "nontransparent_pixels": nontransparent,
                "edge_pixels": edge_pixels,
                "edge_touch": edge_touch,
                "occupancy": occupancy,
                "strategy_class": strategy_class(meta),
                "ok": not item_errors,
                "errors": item_errors,
            }
            records.append(record)
            errors.extend(f"{state}/{index}: {message}" for message in item_errors)

    if not records:
        errors.append("no asset slots were checked; nothing checked")
    for label in sorted(set(catalog) - seen_labels):
        errors.append(f"{label}: expected asset_catalog item was not checked")

    overlay = make_overlay(run_dir, rows, cell_size, records)
    repeat_review = make_tile_repeat_review(run_dir, rows, cell_size) if asset_kind in {"tileset", "texture"} else None
    report = {
        "ok": not errors,
        "engine": "asset-slot-review",
        "run_dir": str(run_dir),
        "asset_kind": asset_kind,
        "manual_review_required": True,
        "quality_gate_note": "Review qa/asset-slot-overlay.png and tile-repeat-review.png when present; labels, pivots, boxes, and projection must make runtime sense.",
        "overlay": overlay,
        "tile_repeat_review": repeat_review,
        "errors": errors,
        "warnings": warnings,
        "records": records,
    }
    atomic_write_text(run_dir / "qa" / "asset-slot-review.json", json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({key: value for key, value in report.items() if key != "records"}, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
