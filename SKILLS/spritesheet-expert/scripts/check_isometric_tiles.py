#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""QA gate for isometric tileset geometry, pivots, roles, and depth previews."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from runio import atomic_save_image, atomic_write_text
from check_asset_slots import cell_geometry, pivot_ok, review_output, row_labels
from check_animation_contracts import frame_rows_by_state
from spritecore.paths import resolve_run_path


def load_json(path: Path, fallback: Any = None) -> Any:
    if not path.is_file():
        return fallback
    def invalid_constant(value: str):
        raise ValueError(f"nonfinite JSON number: {value}")
    data = json.loads(path.read_text(encoding="utf-8-sig"), parse_constant=invalid_constant)
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} must be a JSON object")
    return data


def catalog_from(request: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    for source in (request, manifest):
        catalog = source.get("asset_catalog") if isinstance(source, dict) else None
        if isinstance(catalog, dict):
            return catalog
    return {}


def catalog_items(catalog: dict[str, Any]) -> dict[str, dict[str, Any]]:
    items = catalog.get("items")
    if not isinstance(items, dict):
        return {}
    return {str(key): value for key, value in items.items() if isinstance(value, dict)}


def pivot(meta: dict[str, Any]) -> tuple[float, float] | None:
    value = meta.get("pivot")
    if not pivot_ok(value):
        return None
    return float(value[0]), float(value[1])


def round_even(value: float) -> int:
    rounded = max(2, int(round(value)))
    return rounded if rounded % 2 == 0 else rounded + 1


def frame_index(run_dir: Path, request: dict[str, Any], frames_manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for state, row in frame_rows_by_state(frames_manifest).items():
        files = row.get("files", [])
        if not isinstance(files, list) or any(not isinstance(path, str) for path in files):
            raise ValueError(f"{state}: files must be an array of relative paths")
        entry = request.get("states", {}).get(state)
        if isinstance(entry, dict):
            expected = entry.get("frames")
            if type(expected) is not int or expected <= 0 or len(files) != expected:
                raise ValueError(f"{state}: extracted frame count does not match request")
            if "frames" in row and (type(row["frames"]) is not int or row["frames"] != expected):
                raise ValueError(f"{state}: declared extracted count does not match request")
        labels = row_labels(request, row)
        if labels and len(labels) != len(files):
            raise ValueError(f"{state}: label count does not match extracted frames")
        for frame, rel in enumerate(files):
            label = labels[frame] if frame < len(labels) else f"{state}-{frame}"
            if label in indexed:
                raise ValueError(f"duplicate extracted label: {label}")
            indexed[label] = {
                "label": label,
                "state": state,
                "frame": frame,
                "file": rel,
                "path": resolve_run_path(run_dir, rel),
            }
    return indexed


def safe_composite(canvas: Image.Image, layer: Image.Image, x: int, y: int) -> None:
    left = max(0, x)
    top = max(0, y)
    right = min(canvas.width, x + layer.width)
    bottom = min(canvas.height, y + layer.height)
    if right <= left or bottom <= top:
        return
    crop = layer.crop((left - x, top - y, right - x, bottom - y))
    canvas.alpha_composite(crop, (left, top))


def load_scaled(path: Path, scale: float) -> Image.Image:
    with Image.open(path) as opened:
        image = opened.convert("RGBA")
    if scale == 1:
        return image
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    return image.resize(size, Image.Resampling.NEAREST)


def draw_diamond(
    draw: ImageDraw.ImageDraw,
    center_x: float,
    center_y: float,
    tile_w: float,
    tile_h: float,
    fill: tuple[int, int, int, int] | None,
    outline: tuple[int, int, int, int],
) -> None:
    points = [
        (center_x, center_y - tile_h / 2),
        (center_x + tile_w / 2, center_y),
        (center_x, center_y + tile_h / 2),
        (center_x - tile_w / 2, center_y),
    ]
    draw.polygon(points, fill=fill, outline=outline)


def grid_to_screen(row: int, col: int, tile_w: float, tile_h: float, origin_x: float = 0, origin_y: float = 0, z_height: float = 0) -> list[float]:
    return [
        origin_x + (col - row) * tile_w / 2,
        origin_y + (col + row) * tile_h / 2 - z_height,
    ]


def suggested_pivot_from_record(record: dict[str, Any], fallback: tuple[float, float]) -> tuple[float, float]:
    value = record.get("suggested_pivot")
    if isinstance(value, list) and len(value) == 2:
        return float(value[0]), float(value[1])
    return fallback


def render_pivot_overlay(
    run_dir: Path,
    indexed: dict[str, dict[str, Any]],
    items: dict[str, dict[str, Any]],
    cell: tuple[int, int],
    tile: dict[str, Any],
    record_map: dict[str, dict[str, Any]],
) -> str:
    scale = 0.62 if max(cell) > 180 else 1.0
    cell_w, cell_h = cell
    labels = [label for label in indexed if label in items]
    measure = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    label_width = max((measure.textbbox((0, 0), label[:28])[2] for label in labels), default=0)
    panel_w = max(1, round(cell_w * scale), label_width + 8)
    panel_h = max(1, round(cell_h * scale))
    label_h = 18
    gutter = 8
    cols = 4
    rows = max(1, (len(labels) + cols - 1) // cols)
    overlay = Image.new(
        "RGBA",
        (cols * (panel_w + gutter) + gutter, rows * (panel_h + label_h + gutter) + gutter),
        (17, 17, 17, 255),
    )
    draw = ImageDraw.Draw(overlay)
    tile_w = float(tile.get("width", 0)) * scale
    tile_h = float(tile.get("height", 0)) * scale
    for index, label in enumerate(labels):
        col = index % cols
        row = index // cols
        x = gutter + col * (panel_w + gutter)
        y = gutter + row * (panel_h + label_h + gutter)
        draw.text((x, y), label[:28], fill=(232, 232, 232, 255))
        panel_y = y + label_h
        draw.rectangle((x, panel_y, x + panel_w, panel_y + panel_h), outline=(110, 110, 110, 255))
        scaled = load_scaled(indexed[label]["path"], scale)
        image_x = x + (panel_w - scaled.width) // 2
        safe_composite(overlay, scaled, image_x, panel_y)
        px, py = suggested_pivot_from_record(record_map.get(label, {}), pivot(items[label]) or (cell_w / 2, cell_h / 2))
        px = image_x + px * scale
        py = panel_y + py * scale
        draw_diamond(draw, px, py - tile_h / 2, tile_w, tile_h, None, (247, 209, 95, 220))
        draw.line((px - 5, py, px + 5, py), fill=(220, 220, 220, 255))
        draw.line((px, py - 5, px, py + 5), fill=(220, 220, 220, 255))
    out = run_dir / "qa" / "isometric-pivot-overlay.png"
    atomic_save_image(overlay, out)
    return str(out.relative_to(run_dir))


def choose_label(indexed: dict[str, Any], *candidates: str) -> str | None:
    for label in candidates:
        if label in indexed:
            return label
    return next(iter(indexed), None)


def render_iso_scene(
    run_dir: Path,
    indexed: dict[str, dict[str, Any]],
    items: dict[str, dict[str, Any]],
    cell: tuple[int, int],
    tile: dict[str, Any],
    record_map: dict[str, dict[str, Any]],
    depth: bool,
) -> str:
    canvas = Image.new("RGBA", (880, 520), (17, 17, 17, 255))
    draw = ImageDraw.Draw(canvas)
    tile_w = float(tile.get("width", 128))
    tile_h = float(tile.get("height", 64))
    scale = 0.72 if max(cell) > 180 else 1.0
    origin_x = 440
    origin_y = 120
    step_x = tile_w * scale / 2
    step_y = tile_h * scale / 2

    base_a = choose_label(indexed, "grass-flat", "dark-grass", "mossy-stone-floor")
    base_b = choose_label(indexed, "grass-dirt-patch", "leaf-litter", "cracked-dirt", base_a or "")
    detail = choose_label(indexed, "trampled-path", "flower-floor", "root-floor", base_a or "")
    hazard = choose_label(indexed, "shallow-water", "mud", "electric-puddle", base_b or "")
    ledge = choose_label(indexed, "raised-ledge", "outer-corner", "north-edge", base_a or "")
    bridge = choose_label(indexed, "bridge-tile", "dirt-grass-transition", detail or "")
    pattern = [
        [None, base_a, base_b, base_a, None],
        [base_a, detail, base_a, bridge, base_a],
        [base_b, base_a, hazard, base_a, base_b],
        [base_a, ledge if depth else detail, base_a, detail, base_a],
        [None, base_b, base_a, base_b, None],
    ]
    placements: list[tuple[float, int, int, str, int]] = []
    for gy, row in enumerate(pattern):
        for gx, label in enumerate(row):
            if label:
                z = 1 if depth and label == ledge else 0
                placements.append((gx + gy + z, gx, gy, label, z))
    placements.sort()

    for _, gx, gy, label, z in placements:
        meta = items.get(label, {})
        px, py = suggested_pivot_from_record(record_map.get(label, {}), pivot(meta) or (cell[0] / 2, cell[1] * 0.75))
        screen_x = origin_x + (gx - gy) * step_x
        screen_y = origin_y + (gx + gy) * step_y - z * tile_h * scale
        anchor_y = screen_y + tile_h * scale / 2
        draw_diamond(
            draw,
            screen_x,
            screen_y,
            tile_w * scale,
            tile_h * scale,
            (35, 35, 35, 70),
            (110, 110, 110, 165),
        )
        layer = load_scaled(indexed[label]["path"], scale)
        x = round(screen_x - px * scale)
        y = round(anchor_y - py * scale)
        safe_composite(canvas, layer, x, y)

    caption = "isometric depth review: z/height sort" if depth else "isometric map review: pivot-anchored 2:1 grid"
    caption_width = draw.textbbox((0, 0), caption)[2]
    draw.rectangle((10, 10, 26 + caption_width, 34), fill=(17, 17, 17, 255), outline=(110, 110, 110, 220))
    draw.text((18, 18), caption, fill=(232, 232, 232, 255))
    out = run_dir / "qa" / ("isometric-depth-review.png" if depth else "isometric-map-review.png")
    atomic_save_image(canvas, out)
    return str(out.relative_to(run_dir))


def collect_records(
    indexed: dict[str, dict[str, Any]],
    items: dict[str, dict[str, Any]],
    cell: tuple[int, int],
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    records: list[dict[str, Any]] = []
    for label, frame in indexed.items():
        meta = items.get(label)
        if not meta:
            errors.append(f"{label}: missing asset_catalog item")
            continue
        item_pivot = pivot(meta)
        item_errors: list[str] = []
        if item_pivot is None:
            item_errors.append("missing pivot [x,y]")
        else:
            px, py = item_pivot
            if px < 0 or py < 0 or px > cell[0] or py > cell[1]:
                item_errors.append(f"pivot outside cell: {item_pivot}")
        if not meta.get("category"):
            item_errors.append("missing category")
        if not (meta.get("tile_role") or meta.get("edge_role")):
            item_errors.append("missing tile_role or edge_role")
        if not meta.get("collision"):
            item_errors.append("missing collision")
        with Image.open(frame["path"]) as opened:
            if opened.size != cell:
                item_errors.append(f"frame dimensions {opened.size} do not match cell {cell}")
            bbox = opened.convert("RGBA").getchannel("A").getbbox()
        if not bbox:
            item_errors.append("empty frame")
        suggested = [round((bbox[0] + bbox[2]) / 2), bbox[3]] if bbox else None
        records.append(
            {
                "label": label,
                "state": frame["state"],
                "frame": frame["frame"],
                "file": frame["file"],
                "pivot": list(item_pivot) if item_pivot else None,
                "suggested_pivot": suggested,
                "category": meta.get("category"),
                "tile_role": meta.get("tile_role"),
                "edge_role": meta.get("edge_role"),
                "collision": meta.get("collision"),
                "bbox": list(bbox) if bbox else None,
                "ok": not item_errors,
                "errors": item_errors,
            }
        )
        errors.extend(f"{label}: {message}" for message in item_errors)
    return records, errors, warnings


def infer_grid_calibration(records: list[dict[str, Any]]) -> dict[str, Any]:
    base_records = [
        item
        for item in records
        if item.get("bbox") and item.get("tile_role") in {"base", "bridge", "water", "mud", "detail", "transition"}
    ]
    if not base_records:
        base_records = [item for item in records if item.get("bbox")]
    if not base_records:
        return {"source": "none", "ok": False, "warnings": ["no bbox records available for grid calibration"]}
    widths = [item["bbox"][2] - item["bbox"][0] for item in base_records]
    centers = [(item["bbox"][0] + item["bbox"][2]) / 2 for item in base_records]
    bottoms = [item["bbox"][3] for item in base_records]
    footprint_w = round_even(statistics.median(widths))
    footprint_h = round_even(footprint_w / 2)
    pivot_x = round(statistics.median(centers))
    pivot_y = round(statistics.median(bottoms))
    by_label = {
        str(item["label"]): {
            "suggested_pivot": item.get("suggested_pivot"),
            "bbox": item.get("bbox"),
        }
        for item in records
        if item.get("suggested_pivot")
    }
    return {
        "source": "alpha-bbox median heuristic; visual footprint approval required",
        "ok": True,
        "tile": {"width": footprint_w, "height": footprint_h},
        "pivot": [pivot_x, pivot_y],
        "sample_count": len(base_records),
        "width_range": [min(widths), max(widths)],
        "bottom_range": [min(bottoms), max(bottoms)],
        "records": by_label,
    }


def runtime_pivot(record: dict[str, Any], meta: dict[str, Any], fallback: list[int]) -> list[int]:
    suggested = record.get("suggested_pivot")
    if isinstance(suggested, list) and len(suggested) == 2:
        return [round(float(suggested[0])), round(float(suggested[1]))]
    item_pivot = pivot(meta)
    if item_pivot:
        return [round(item_pivot[0]), round(item_pivot[1])]
    return fallback


def normalized_effective_tile(effective_tile: dict[str, Any], cell: tuple[int, int]) -> dict[str, Any]:
    return {
        "width": round(float(effective_tile.get("width", 0))),
        "height": round(float(effective_tile.get("height", 0))),
        "runtimeCell": [cell[0], cell[1]],
    }


def build_runtime_metadata(
    catalog: dict[str, Any],
    items: dict[str, dict[str, Any]],
    records: list[dict[str, Any]],
    effective_tile: dict[str, Any],
    calibration: dict[str, Any],
    cell: tuple[int, int],
    ok: bool,
) -> dict[str, Any]:
    tile = normalized_effective_tile(effective_tile, cell)
    default_pivot = calibration.get("pivot") if isinstance(calibration.get("pivot"), list) else [cell[0] // 2, cell[1]]
    center = grid_to_screen(1, 2, float(tile["width"]), float(tile["height"]))
    runtime_items: dict[str, Any] = {}
    for source_order, record in enumerate(records):
        label = str(record["label"])
        meta = items.get(label, {})
        item = {
            "file": record.get("file"),
            "source_order": source_order,
            "pivot": runtime_pivot(record, meta, default_pivot),
            "catalog_pivot": meta.get("pivot"),
            "bbox": record.get("bbox"),
            "category": meta.get("category"),
            "tile_role": meta.get("tile_role"),
            "edge_role": meta.get("edge_role"),
            "collision": meta.get("collision"),
            "z_offset": meta.get("z_offset", 0),
        }
        if meta.get("footprint"):
            item["footprint"] = meta.get("footprint")
        runtime_items[label] = item
    return {
        "ok": ok,
        "engine": "isometric-runtime-metadata",
        "projection": catalog.get("projection", "2:1 isometric"),
        "placement_model": "center-plus-bottom-anchor",
        "manual_review_required": True,
        "quality_gate_note": "These alpha-bbox footprint/pivot candidates need visual approval before runtime import; passing numeric checks does not prove the logical floor geometry.",
        "cell": {"width": cell[0], "height": cell[1]},
        "tile": tile,
        "defaultPivot": default_pivot,
        "formula": {
            "center_x": "origin_x + (col - row) * tile_width / 2",
            "center_y": "origin_y + (col + row) * tile_height / 2 - z_height",
            "object_anchor_y": "center_y + tile_height / 2",
            "draw_x": "center_x - pivot_x",
            "draw_y": "object_anchor_y - pivot_y",
            "depth": "row + col + z_offset; tie-break by source_order",
        },
        "example": {
            "row": 1,
            "col": 2,
            "center": center,
            "object_anchor_y": center[1] + float(tile["height"]) / 2,
        },
        "calibration": calibration,
        "items": runtime_items,
    }


def build_calibrated_catalog(
    catalog: dict[str, Any],
    items: dict[str, dict[str, Any]],
    records: list[dict[str, Any]],
    effective_tile: dict[str, Any],
    calibration: dict[str, Any],
    cell: tuple[int, int],
) -> dict[str, Any]:
    updated = json.loads(json.dumps(catalog or {}, ensure_ascii=False))
    updated["projection"] = updated.get("projection", "2:1 isometric")
    updated["tile"] = normalized_effective_tile(effective_tile, cell)
    default_pivot = calibration.get("pivot") if isinstance(calibration.get("pivot"), list) else [cell[0] // 2, cell[1]]
    updated_items = updated.get("items") if isinstance(updated.get("items"), dict) else {}
    for record in records:
        label = str(record["label"])
        meta = dict(items.get(label, updated_items.get(label, {})))
        old_pivot = meta.get("pivot")
        meta["pivot"] = runtime_pivot(record, meta, default_pivot)
        if old_pivot and old_pivot != meta["pivot"]:
            meta["catalog_pivot_before_calibration"] = old_pivot
        meta["review_bbox"] = record.get("bbox")
        meta["review_file"] = record.get("file")
        updated_items[label] = meta
    updated["items"] = updated_items
    updated["review_status"] = {
        "manual_review_required": True,
        "source": "check_isometric_tiles.py calibrated from extracted alpha bboxes",
        "next_step": "Review pivots/roles visually, then copy approved values into the source asset catalog before final packaging.",
    }
    return updated


def write_runtime_artifacts(
    run_dir: Path,
    runtime_metadata: dict[str, Any],
    calibrated_catalog: dict[str, Any],
) -> dict[str, str]:
    runtime_path = run_dir / "qa" / "isometric-runtime-metadata.json"
    catalog_path = run_dir / "qa" / "isometric-calibrated-catalog.json"
    atomic_write_text(runtime_path, json.dumps(runtime_metadata, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    atomic_write_text(catalog_path, json.dumps(calibrated_catalog, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    return {
        "runtime_metadata": str(runtime_path.relative_to(run_dir)),
        "calibrated_catalog": str(catalog_path.relative_to(run_dir)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--ratio-tolerance", type=float, default=0.12)
    args = parser.parse_args()
    if not math.isfinite(args.ratio_tolerance) or args.ratio_tolerance < 0:
        parser.error("--ratio-tolerance must be finite and non-negative")

    run_dir = args.run_dir.expanduser().resolve()
    qa_dir = resolve_run_path(run_dir, "qa")
    qa_dir.mkdir(parents=True, exist_ok=True)
    request = load_json(resolve_run_path(run_dir, "sprite-request.json"), {})
    if not isinstance(request.get("states", {}), dict):
        raise ValueError("sprite-request.json.states must be an object")
    manifest_path = resolve_run_path(run_dir, "manifest.json")
    manifest = load_json(manifest_path, {})
    frames_manifest = load_json(resolve_run_path(run_dir, "frames/frames-manifest.json"), {})
    segmentation = load_json(resolve_run_path(run_dir, "qa/segmentation-report.json"), {})
    asset_slot_report = load_json(resolve_run_path(run_dir, "qa/asset-slot-review.json"), {})
    asset_kind = str(request.get("asset_kind", "sprite"))
    cell = cell_geometry(request.get("cell", {}))
    catalog = catalog_from(request, manifest)
    items = catalog_items(catalog)
    tile = catalog.get("tile") if isinstance(catalog.get("tile"), dict) else {}
    indexed = frame_index(run_dir, request, frames_manifest)
    sources = {frame["path"] for frame in indexed.values()} | {
        resolve_run_path(run_dir, relative) for relative in (
            "manifest.json", "qa/segmentation-report.json", "qa/asset-slot-review.json"
        )
    }
    for name in (
        "isometric-tile-review.json", "isometric-pivot-overlay.png", "isometric-map-review.png",
        "isometric-depth-review.png", "isometric-runtime-metadata.json", "isometric-calibrated-catalog.json",
    ):
        review_output(run_dir, f"qa/{name}", sources)

    errors: list[str] = []
    warnings: list[str] = []
    if frames_manifest.get("ok") is not True:
        errors.append("frames/frames-manifest.json is missing ok:true")
    if not manifest_path.is_file():
        errors.append("manifest.json is missing")
    if manifest.get("ok") is False:
        errors.append("manifest.json is marked ok:false")
    if asset_slot_report and asset_slot_report.get("ok") is False:
        errors.append("qa/asset-slot-review.json is marked ok:false")
    if asset_kind != "tileset":
        errors.append(f"isometric tile QA requires asset_kind=tileset, got {asset_kind!r}")
    projection = str(catalog.get("projection", request.get("projection", ""))).lower()
    if "iso" not in projection and "dimetric" not in projection and "2:1" not in projection:
        errors.append("asset_catalog.projection must declare isometric/2:1/dimetric projection")
    if not tile:
        errors.append("asset_catalog.tile must declare isometric footprint width/height")
        tile = {"width": 0, "height": 0}
    if any(type(tile.get(key, 0)) not in (int, float) for key in ("width", "height")):
        raise ValueError("asset_catalog.tile width/height must be finite numbers")
    tile_w = float(tile.get("width", 0))
    tile_h = float(tile.get("height", 0))
    if tile_w <= 0 or tile_h <= 0:
        errors.append("asset_catalog.tile width/height must be positive")
    else:
        ratio = tile_w / tile_h
        if abs(ratio - 2.0) > args.ratio_tolerance:
            errors.append(f"isometric footprint must be 2:1, got {tile_w:g}x{tile_h:g} ratio {ratio:.2f}")
    runtime_cell = tile.get("runtimeCell") or tile.get("runtime_cell")
    if isinstance(runtime_cell, list) and len(runtime_cell) == 2:
        if any(type(value) is not int or value <= 0 for value in runtime_cell):
            raise ValueError("asset_catalog.tile.runtimeCell must contain positive integers")
        expected = list(runtime_cell)
        actual = [cell[0], cell[1]]
        if expected != actual:
            errors.append(f"asset_catalog.tile.runtimeCell {expected} does not match actual cut cell {actual}")
    else:
        if runtime_cell is not None:
            errors.append("asset_catalog.tile.runtimeCell must contain two positive integers")
        else:
            warnings.append("asset_catalog.tile.runtimeCell missing; runtime importer must infer atlas cell from request.cell")
    if segmentation and segmentation.get("ok") is False:
        errors.append("segmentation report is marked ok:false")
        for message in segmentation.get("warnings", []) or []:
            errors.append(f"segmentation blocked: {message}")

    records, record_errors, record_warnings = collect_records(indexed, items, cell)
    errors.extend(record_errors)
    warnings.extend(record_warnings)
    request_states = request.get("states", {})
    if not isinstance(request_states, dict) or not request_states:
        errors.append("sprite-request.json.states must be a non-empty object")
    expected_states = set(request_states) if isinstance(request_states, dict) else set()
    manifest_rows = frames_manifest.get("rows", [])
    checked_states = {
        str(row.get("state", ""))
        for row in manifest_rows
        if isinstance(row, dict)
    }
    for state in sorted(expected_states - checked_states):
        errors.append(f"{state}: expected request state has no frames-manifest row")
    if not indexed:
        errors.append("no isometric tiles were checked; nothing checked")
    for label in sorted(set(items) - set(indexed)):
        errors.append(f"{label}: expected asset_catalog item was not checked")
    calibration = infer_grid_calibration(records)
    effective_tile = dict(tile)
    if calibration.get("ok"):
        inferred_tile = calibration["tile"]
        inferred_pivot = calibration["pivot"]
        if tile_w > 0 and tile_h > 0:
            width_delta = abs(float(tile.get("width", 0)) - float(inferred_tile["width"]))
            height_delta = abs(float(tile.get("height", 0)) - float(inferred_tile["height"]))
            if width_delta > 8 or height_delta > 8:
                errors.append(
                    "catalog footprint "
                    f"{tile.get('width')}x{tile.get('height')} does not match inferred real footprint "
                    f"{inferred_tile['width']}x{inferred_tile['height']}"
                )
        catalog_pivots = [pivot(meta) for meta in items.values()]
        catalog_pivots = [item for item in catalog_pivots if item is not None]
        if catalog_pivots:
            catalog_pivot = [round(statistics.median([item[0] for item in catalog_pivots])), round(statistics.median([item[1] for item in catalog_pivots]))]
            if abs(catalog_pivot[0] - inferred_pivot[0]) > 8 or abs(catalog_pivot[1] - inferred_pivot[1]) > 8:
                errors.append(f"catalog pivot {catalog_pivot} does not match inferred floor/contact pivot {inferred_pivot}")
        effective_tile = {"width": inferred_tile["width"], "height": inferred_tile["height"], "runtimeCell": [cell[0], cell[1]]}
    roles = {str(meta.get("tile_role", "")) for meta in items.values()}
    edges = {str(meta.get("edge_role", "")) for meta in items.values()}
    if "base" not in roles:
        errors.append("tileset needs at least one tile_role=base tile")
    for edge in ("north", "south", "east", "west"):
        if edge not in edges:
            errors.append(f"tileset missing edge_role={edge}")
    if not ({"outer-corner", "inner-corner"} & edges):
        warnings.append("tileset has no explicit inner/outer corner role; map edges may not close cleanly")

    pivot_overlay = None
    map_review = None
    depth_review = None
    record_map = {str(item["label"]): item for item in records}
    if indexed and items and float(effective_tile.get("width", 0)) > 0 and float(effective_tile.get("height", 0)) > 0:
        pivot_overlay = render_pivot_overlay(run_dir, indexed, items, cell, effective_tile, record_map)
        map_review = render_iso_scene(run_dir, indexed, items, cell, effective_tile, record_map, depth=False)
        depth_review = render_iso_scene(run_dir, indexed, items, cell, effective_tile, record_map, depth=True)
    runtime_metadata = build_runtime_metadata(catalog, items, records, effective_tile, calibration, cell, not errors)
    calibrated_catalog = build_calibrated_catalog(catalog, items, records, effective_tile, calibration, cell)
    runtime_artifacts = write_runtime_artifacts(run_dir, runtime_metadata, calibrated_catalog)

    report = {
        "ok": not errors,
        "engine": "isometric-tile-review",
        "run_dir": str(run_dir),
        "manual_review_required": True,
        "quality_gate_note": "Review pivot, map and depth previews. This checker targets 2:1 grids. Alpha bboxes only suggest footprint/pivot candidates; approve the logical floor geometry visually before runtime import.",
        "contract": {
            "asset_kind": asset_kind,
            "projection": catalog.get("projection"),
            "cell": {"width": cell[0], "height": cell[1]},
            "tile": tile,
        },
        "calibration": calibration,
        "effective_tile": effective_tile,
        "overlays": {
            "pivot_overlay": pivot_overlay,
            "map_review": map_review,
            "depth_review": depth_review,
        },
        "runtime_artifacts": runtime_artifacts,
        "errors": errors,
        "warnings": warnings,
        "records": records,
    }
    atomic_write_text(qa_dir / "isometric-tile-review.json", json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    print(json.dumps({key: value for key, value in report.items() if key != "records"}, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, TypeError) as exc:
        print(str(exc), file=sys.stderr)
        print(json.dumps({"ok": False, "complete": False, "status": "operational-error", "errors": [str(exc)]}))
        raise SystemExit(3)
