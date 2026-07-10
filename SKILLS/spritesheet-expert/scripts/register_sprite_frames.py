#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Register extracted sprite frames to a stable runtime pivot.

Use after `unpack_atlas_run.py` or `extract_sprite_row_frames.py` when frames are
cut correctly but the character drifts inside each cell. The script creates a
new run folder with clean cell-sized frames, a registration report, and a visual
overlay. Compose the registered run with `compose_sprite_atlas.py`.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from runio import acquire_run_dir_lock, atomic_save_image, atomic_write_text
from spritecore.image_ops import (
    ArtMode,
    ImagePolicyError,
    ResizePolicy,
    inspect_transform_invariants,
    inspect_hard_alpha,
    resize_image,
    resize_policy_from_sampling_policy,
    validate_frame,
)


def parse_cell(value: str) -> tuple[int, int]:
    left, right = value.lower().split("x", 1)
    return int(left), int(right)


def alpha_bbox(image: Image.Image, threshold: int) -> tuple[int, int, int, int] | None:
    alpha = image.getchannel("A")
    mask = alpha.point(lambda value: 255 if value > threshold else 0)
    return mask.getbbox()


def alpha_nonzero_count(image: Image.Image) -> int:
    return sum(image.getchannel("A").histogram()[1:])


def weighted_anchor_x(
    image: Image.Image,
    bbox: tuple[int, int, int, int],
    threshold: int,
    start_ratio: float,
    end_ratio: float,
) -> tuple[float | None, int]:
    x0, y0, x1, y1 = bbox
    height = max(1, y1 - y0)
    start_y = max(y0, min(y1 - 1, round(y0 + height * start_ratio)))
    end_y = max(start_y + 1, min(y1, round(y0 + height * end_ratio)))
    alpha = image.getchannel("A")
    total = 0
    weighted = 0.0
    for y in range(start_y, end_y):
        for x in range(x0, x1):
            value = alpha.getpixel((x, y))
            if value > threshold:
                total += value
                weighted += x * value
    if total <= 0:
        return None, 0
    return weighted / total, total


def anchor_for(
    image: Image.Image,
    bbox: tuple[int, int, int, int],
    mode: str,
    threshold: int,
) -> tuple[float, float, dict[str, Any]]:
    x0, y0, x1, y1 = bbox
    if mode == "bbox-bottom":
        return (x0 + x1) / 2, float(y1), {"source": "bbox-bottom"}
    if mode == "center":
        return (x0 + x1) / 2, (y0 + y1) / 2, {"source": "bbox-center"}

    if mode == "footprint":
        anchor_x, pixels = weighted_anchor_x(image, bbox, threshold, 0.72, 1.0)
        if anchor_x is not None:
            return anchor_x, float(y1), {"source": "footprint", "weighted_alpha": pixels}
        return (x0 + x1) / 2, float(y1), {"source": "footprint-fallback-bbox"}

    # body-bottom: stable actor root. X comes from torso/upper-body mass, Y from
    # the grounded baseline. This preserves leg motion better than pinning the
    # active contact foot.
    anchor_x, pixels = weighted_anchor_x(image, bbox, threshold, 0.22, 0.68)
    if anchor_x is not None:
        return anchor_x, float(y1), {"source": "body-band", "weighted_alpha": pixels}
    return (x0 + x1) / 2, float(y1), {"source": "body-fallback-bbox"}


def clipped_alpha_composite(target: Image.Image, source: Image.Image, left: int, top: int) -> bool:
    src_left = max(0, -left)
    src_top = max(0, -top)
    src_right = min(source.width, target.width - left)
    src_bottom = min(source.height, target.height - top)
    if src_left >= src_right or src_top >= src_bottom:
        return True
    crop = source.crop((src_left, src_top, src_right, src_bottom))
    target.alpha_composite(crop, (max(0, left), max(0, top)))
    return src_left > 0 or src_top > 0 or src_right < source.width or src_bottom < source.height


def register_frame(
    image: Image.Image,
    cell: tuple[int, int],
    args: argparse.Namespace,
    resize_policy: ResizePolicy | None = None,
) -> tuple[Image.Image, dict[str, Any], list[str]]:
    cell_w, cell_h = cell
    warnings: list[str] = []
    rgba = image.convert("RGBA")
    bbox = alpha_bbox(rgba, args.alpha_threshold)
    target = Image.new("RGBA", (cell_w, cell_h), (0, 0, 0, 0))
    if bbox is None:
        warnings.append("blank frame")
        return target, {"bbox": None, "blank": True}, warnings

    anchor_x, anchor_y, anchor_meta = anchor_for(rgba, bbox, args.anchor, args.alpha_threshold)
    crop = rgba.crop(bbox)
    local_anchor_x = anchor_x - bbox[0]
    local_anchor_y = anchor_y - bbox[1]

    max_w = max(1, cell_w - args.safe_margin_x * 2)
    max_h = max(1, cell_h - args.safe_margin_y * 2)
    scale = min(1.0, max_w / crop.width, max_h / crop.height)
    if scale < 1.0:
        new_size = (max(1, round(crop.width * scale)), max(1, round(crop.height * scale)))
        source_crop = crop
        effective_policy = resize_policy or ResizePolicy(mode=ArtMode.ILLUSTRATED)
        crop = resize_image(source_crop, new_size, policy=effective_policy)
        if effective_policy.mode is ArtMode.PIXEL:
            invariants = inspect_transform_invariants(source_crop, crop)
            if not invariants.ok:
                raise ImagePolicyError(
                    "pixel registration violated palette or hard-alpha invariants"
                )
        local_anchor_x *= scale
        local_anchor_y *= scale

    target_x = round(cell_w * args.target_x)
    target_y = args.target_bottom if args.target_bottom is not None else cell_h - args.safe_margin_y
    left = round(target_x - local_anchor_x)
    top = round(target_y - local_anchor_y)
    left = max(
        args.safe_margin_x,
        min(cell_w - args.safe_margin_x - crop.width, left),
    )
    top = max(
        args.safe_margin_y,
        min(cell_h - args.safe_margin_y - crop.height, top),
    )
    clipped = clipped_alpha_composite(target, crop, left, top)
    if clipped:
        warnings.append("registered crop clipped by target cell")

    out_bbox = alpha_bbox(target, args.alpha_threshold)
    metrics = {
        "bbox": list(bbox),
        "anchor": [round(anchor_x, 3), round(anchor_y, 3)],
        "anchor_meta": anchor_meta,
        "scale": round(scale, 4),
        "crop_size": [crop.width, crop.height],
        "paste": [left, top],
        "target_anchor": [target_x, target_y],
        "output_bbox": list(out_bbox) if out_bbox else None,
        "clipped": clipped,
    }
    return target, metrics, warnings


def load_manifest_rows(run_dir: Path) -> list[dict[str, Any]]:
    manifest = json.loads((run_dir / "frames" / "frames-manifest.json").read_text(encoding="utf-8"))
    if not manifest.get("ok"):
        raise SystemExit("frames-manifest.json is not ok; fix extraction before registration")
    return list(manifest.get("rows", []))


def copy_optional_sidecars(run_dir: Path, out_dir: Path) -> None:
    for name in ("unpack-source.json",):
        src = run_dir / name
        if src.is_file():
            shutil.copyfile(src, out_dir / name)
    references = run_dir / "references"
    if references.is_dir() and not (out_dir / "references").exists():
        shutil.copytree(references, out_dir / "references")


def make_overlay(out_dir: Path, rows: list[dict[str, Any]], cell: tuple[int, int], args: argparse.Namespace) -> Path:
    cell_w, cell_h = cell
    thumb = args.overlay_cell
    label_w = 190
    pad = 10
    max_frames = max((row["frames"] for row in rows), default=1)
    width = label_w + max_frames * (thumb + pad) + pad
    height = 58 + len(rows) * (thumb + 42)
    overlay = Image.new("RGBA", (width, height), (10, 10, 10, 255))
    draw = ImageDraw.Draw(overlay, "RGBA")
    try:
        font = ImageFont.truetype("arial.ttf", 14)
        small = ImageFont.truetype("arial.ttf", 11)
    except Exception:
        font = None
        small = None

    draw.text((12, 10), "Sprite Registration QA", fill=(235, 235, 235, 255), font=font)
    draw.text(
        (12, 30),
        f"anchor={args.anchor}; target x={args.target_x:.2f}; target bottom={args.target_bottom if args.target_bottom is not None else cell_h - args.safe_margin_y}",
        fill=(170, 170, 170, 255),
        font=small,
    )
    target_x = round(thumb * args.target_x)
    target_y = round(thumb * ((args.target_bottom if args.target_bottom is not None else cell_h - args.safe_margin_y) / cell_h))

    for row_index, row in enumerate(rows):
        y = 58 + row_index * (thumb + 42)
        draw.text((12, y + 8), row["state"], fill=(226, 226, 226, 255), font=font)
        draw.text((12, y + 28), f"{row['frames']} frames", fill=(150, 150, 150, 255), font=small)
        for index in range(row["frames"]):
            x = label_w + index * (thumb + pad)
            for yy in range(0, thumb, 12):
                for xx in range(0, thumb, 12):
                    fill = (28, 28, 28, 255) if ((xx // 12 + yy // 12) & 1) == 0 else (40, 40, 40, 255)
                    draw.rectangle((x + xx, y + yy, x + xx + 11, y + yy + 11), fill=fill)
            frame_path = out_dir / "frames" / row["state"] / f"frame-{index}.png"
            with Image.open(frame_path) as opened:
                thumb_frame = opened.convert("RGBA").resize((thumb, thumb), Image.Resampling.NEAREST)
            overlay.alpha_composite(thumb_frame, (x, y))
            draw.rectangle((x, y, x + thumb, y + thumb), outline=(245, 158, 11, 220))
            draw.line((x + target_x, y, x + target_x, y + thumb), fill=(80, 190, 255, 210), width=1)
            draw.line((x, y + target_y, x + thumb, y + target_y), fill=(80, 190, 255, 210), width=1)
            draw.text((x, y + thumb + 4), f"f{index + 1}", fill=(220, 220, 220, 255), font=small)

    qa_dir = out_dir / "qa"
    qa_dir.mkdir(parents=True, exist_ok=True)
    path = qa_dir / "registration-overlay.png"
    atomic_save_image(overlay, path)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--cell", type=parse_cell, help="output cell WxH; defaults to input request cell")
    parser.add_argument("--states", default="all", help="'all' or comma-separated state names")
    parser.add_argument("--anchor", choices=("body-bottom", "bbox-bottom", "footprint", "center"), default="body-bottom")
    parser.add_argument("--target-x", type=float, default=0.5)
    parser.add_argument("--target-bottom", type=int)
    parser.add_argument("--safe-margin-x", type=int)
    parser.add_argument("--safe-margin-y", type=int)
    parser.add_argument("--alpha-threshold", type=int, default=16)
    parser.add_argument(
        "--min-used-pixels",
        type=int,
        default=None,
        help="explicit absolute sparse-frame override; default uses scale-aware profiles",
    )
    parser.add_argument("--allow-clipping", action="store_true", help="downgrade target-cell clipping to a warning")
    parser.add_argument("--overlay-cell", type=int, default=128)
    parser.add_argument("--force", action="store_true", help="allow writing into an existing out-dir")
    args = parser.parse_args()

    run_dir = args.run_dir.expanduser().resolve()
    out_dir = args.out_dir.expanduser().resolve() if args.out_dir else run_dir.with_name(f"{run_dir.name}-registered")
    if out_dir.exists() and any(out_dir.iterdir()) and not args.force:
        raise SystemExit(f"out-dir not empty: {out_dir} (use --force)")
    out_dir.mkdir(parents=True, exist_ok=True)
    acquire_run_dir_lock(out_dir, "register_sprite_frames")

    request = json.loads((run_dir / "sprite-request.json").read_text(encoding="utf-8"))
    resize_policy = resize_policy_from_sampling_policy(request.get("sampling_policy"))
    input_cell = request.get("cell", {})
    cell = args.cell or (
        int(input_cell.get("width", input_cell.get("size", 0))),
        int(input_cell.get("height", input_cell.get("size", 0))),
    )
    if cell[0] <= 0 or cell[1] <= 0:
        raise SystemExit("output cell must be positive; pass --cell WxH")
    request_margin = int(input_cell.get("safe_margin", 0))
    args.safe_margin_x = (
        int(input_cell.get("safe_margin_x", request_margin))
        if args.safe_margin_x is None and ("safe_margin_x" in input_cell or "safe_margin" in input_cell)
        else args.safe_margin_x
    )
    args.safe_margin_y = (
        int(input_cell.get("safe_margin_y", request_margin))
        if args.safe_margin_y is None and ("safe_margin_y" in input_cell or "safe_margin" in input_cell)
        else args.safe_margin_y
    )
    if args.safe_margin_x is None:
        args.safe_margin_x = max(1, round(cell[0] / 32))
    if args.safe_margin_y is None:
        args.safe_margin_y = max(1, round(cell[1] / 32))
    args.safe_margin_x = max(0, min(args.safe_margin_x, max(0, (cell[0] - 1) // 2)))
    args.safe_margin_y = max(0, min(args.safe_margin_y, max(0, (cell[1] - 1) // 2)))

    selected = None if args.states == "all" else {state.strip() for state in args.states.split(",") if state.strip()}
    rows_by_state = {row["state"]: row for row in load_manifest_rows(run_dir)}
    states = [state for state in request.get("states", {}) if selected is None or state in selected]
    if not states:
        raise SystemExit("no matching states to register")

    copy_optional_sidecars(run_dir, out_dir)
    output_request = dict(request)
    output_request["cell"] = {
        "shape": "square" if cell[0] == cell[1] else "rect",
        "width": cell[0],
        "height": cell[1],
        "size": cell[0],
        "safe_margin": min(args.safe_margin_x, args.safe_margin_y),
    }
    output_request["registration"] = {
        **(output_request.get("registration") if isinstance(output_request.get("registration"), dict) else {}),
        "method": "register_sprite_frames",
        "anchor": args.anchor,
        "target_x": args.target_x,
        "target_bottom": args.target_bottom if args.target_bottom is not None else cell[1] - args.safe_margin_y,
    }
    output_states = {state: output_request["states"][state] for state in states}
    output_request["states"] = output_states
    atomic_write_text(out_dir / "sprite-request.json", json.dumps(output_request, ensure_ascii=False, indent=2) + "\n")

    frames_root = out_dir / "frames"
    frames_root.mkdir(parents=True, exist_ok=True)
    manifest_rows: list[dict[str, Any]] = []
    report_rows: list[dict[str, Any]] = []
    errors: list[str] = []
    warnings: list[str] = []
    allow_full_cell = str(request.get("asset_kind", "sprite")) in {"tileset", "texture"}
    for state in states:
        if state not in rows_by_state:
            errors.append(f"missing extracted row for state: {state}")
            continue
        row = rows_by_state[state]
        state_dir = frames_root / state
        state_dir.mkdir(parents=True, exist_ok=True)
        files: list[str] = []
        frame_reports: list[dict[str, Any]] = []
        for index, rel in enumerate(row.get("files", [])):
            frame_path = run_dir / rel
            if not frame_path.is_file():
                errors.append(f"missing frame: {frame_path}")
                continue
            with Image.open(frame_path) as opened:
                try:
                    registered, metrics, frame_warnings = register_frame(
                        opened.convert("RGBA"), cell, args, resize_policy
                    )
                except ImagePolicyError as exc:
                    errors.append(f"{state} frame {index}: {exc}")
                    continue
            used_pixels = alpha_nonzero_count(registered)
            metrics["nontransparent_pixels"] = used_pixels
            validation = validate_frame(
                registered,
                alpha_threshold=args.alpha_threshold,
                allow_full_cell=allow_full_cell,
            )
            if resize_policy.mode is ArtMode.PIXEL:
                alpha_invariant = inspect_hard_alpha(registered)
                if not alpha_invariant.ok:
                    errors.append(
                        f"{state} frame {index}: alpha invariant violation: "
                        f"{len(alpha_invariant.new_fractional_alpha_values)} "
                        "fractional alpha values"
                    )
            if args.min_used_pixels is not None:
                if used_pixels < args.min_used_pixels:
                    errors.append(
                        f"{state} frame {index}: registered frame is too sparse "
                        f"({used_pixels} pixels)"
                    )
            profile_failures = validation.failures
            errors.extend(
                f"{state} frame {index}: {failure}" for failure in profile_failures
            )
            if metrics.get("clipped") and not args.allow_clipping:
                errors.append(f"{state} frame {index}: registered crop clipped by target cell")
            out_path = state_dir / f"frame-{index}.png"
            atomic_save_image(registered, out_path)
            files.append(str(out_path.relative_to(out_dir)))
            warnings.extend(f"{state} frame {index}: {warning}" for warning in frame_warnings)
            frame_reports.append({"frame": index, **metrics, "warnings": frame_warnings})
        row_errors = [error for error in errors if error.startswith(f"{state} ")]
        manifest_rows.append({"state": state, "frames": len(files), "method": "registered", "files": files, "ok": not row_errors})
        report_rows.append({"state": state, "frames": len(files), "frames_report": frame_reports})

    manifest = {
        "ok": not errors,
        "engine": "component-row",
        "run_dir": str(out_dir),
        "cell": output_request["cell"],
        "rows": manifest_rows,
        "errors": errors,
        "warnings": warnings,
    }
    atomic_write_text(frames_root / "frames-manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    overlay_path = make_overlay(out_dir, manifest_rows, cell, args) if manifest_rows else None
    report = {
        "ok": not errors,
        "engine": "sprite-frame-registration",
        "input_run_dir": str(run_dir),
        "out_dir": str(out_dir),
        "cell": {"width": cell[0], "height": cell[1]},
        "anchor": args.anchor,
        "target": {
            "x": round(cell[0] * args.target_x),
            "bottom": args.target_bottom if args.target_bottom is not None else cell[1] - args.safe_margin_y,
        },
        "overlay": str(overlay_path.relative_to(out_dir)) if overlay_path else None,
        "errors": errors,
        "warnings": warnings,
        "rows": report_rows,
    }
    atomic_write_text(out_dir / "qa" / "registration-report.json", json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
