#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Extract component-row sprite strips into clean RGBA frames."""

from __future__ import annotations

import argparse
import io
import json
import math
import re
from collections import Counter
from pathlib import Path
from statistics import median
from typing import Any

from PIL import Image, ImageDraw

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
from segmentation import alpha_mass_extent_80, projection_sprites


DEFAULT_REMBG_MODEL = "birefnet-general"
DEFAULT_BEN2_MODEL = "PramaLLC/BEN2"
BACKGROUND_REMOVAL_METHODS = {"none", "chroma", "matte", "rembg", "ben2", "auto"}
STABLE_FEATURE_KEYS = ("head_width", "upper_width", "torso_width", "opaque_area", "body_mass_width_80", "body_mass_height_80")


def default_background_model(method: str) -> str:
    return DEFAULT_BEN2_MODEL if method == "ben2" else DEFAULT_REMBG_MODEL


def color_distance(left: tuple[int, int, int], right: tuple[int, int, int]) -> float:
    return math.sqrt(sum((left[index] - right[index]) ** 2 for index in range(3)))


def color_distance_sq(left: tuple[int, int, int], right: tuple[int, int, int]) -> int:
    return sum((left[index] - right[index]) ** 2 for index in range(3))


def alpha_nonzero_count(image: Image.Image) -> int:
    return sum(image.getchannel("A").histogram()[1:])


def median_number(values: list[float]) -> float | None:
    filtered = [value for value in values if value is not None]
    return median(filtered) if filtered else None


def edge_alpha_count(image: Image.Image, margin: int) -> int:
    alpha = image.getchannel("A")
    width, height = image.size
    total = 0
    for box in (
        (0, 0, width, margin),
        (0, height - margin, width, height),
        (0, 0, margin, height),
        (width - margin, 0, width, height),
    ):
        total += sum(alpha.crop(box).histogram()[1:])
    return total


def key_tint_score(color: tuple[int, int, int], chroma_key: tuple[int, int, int]) -> float:
    keyed_channels = [index for index, value in enumerate(chroma_key) if value >= 192]
    unkeyed_channels = [index for index, value in enumerate(chroma_key) if value < 64]
    if not keyed_channels or not unkeyed_channels:
        return 0.0
    keyed_average = sum(color[index] for index in keyed_channels) / len(keyed_channels)
    unkeyed_average = sum(color[index] for index in unkeyed_channels) / len(unkeyed_channels)
    return keyed_average - unkeyed_average


def neutralize_key_tint(color: tuple[int, int, int], chroma_key: tuple[int, int, int]) -> tuple[int, int, int]:
    keyed_channels = [index for index, value in enumerate(chroma_key) if value >= 192]
    unkeyed_channels = [index for index, value in enumerate(chroma_key) if value < 64]
    if not keyed_channels or not unkeyed_channels:
        neutral = round(sum(color) / 3)
    else:
        neutral = round(sum(color[index] for index in unkeyed_channels) / len(unkeyed_channels))
    output = list(color)
    for index in keyed_channels:
        output[index] = min(output[index], neutral)
    return tuple(output)


def smoothstep(edge0: float, edge1: float, value: float) -> float:
    if edge1 <= edge0:
        return 1.0 if value >= edge1 else 0.0
    t = max(0.0, min(1.0, (value - edge0) / (edge1 - edge0)))
    return t * t * (3.0 - 2.0 * t)


def softened_edge_alpha(alpha: int, distance: float, threshold: float, fringe_threshold: float) -> int:
    if alpha <= 16 or distance <= threshold:
        return 0
    if distance >= fringe_threshold:
        return alpha
    return round(alpha * smoothstep(threshold, fringe_threshold, distance))


def chroma_background_candidate(
    color: tuple[int, int, int],
    alpha: int,
    chroma_key: tuple[int, int, int],
    threshold: float,
    fringe_threshold: float,
    fringe_delta: float,
) -> bool:
    if alpha <= 16:
        return True
    distance_sq = color_distance_sq(color, chroma_key)
    if distance_sq <= threshold * threshold:
        return True
    return distance_sq <= fringe_threshold * fringe_threshold and key_tint_score(color, chroma_key) >= fringe_delta


def chroma_background_mask(
    rgba: Image.Image,
    chroma_key: tuple[int, int, int],
    threshold: float,
    fringe_threshold: float,
    fringe_delta: float,
) -> bytearray:
    pixels = rgba.load()
    width, height = rgba.size
    candidates = bytearray(width * height)
    for y in range(height):
        for x in range(width):
            red, green, blue, alpha = pixels[x, y]
            if chroma_background_candidate(
                (red, green, blue),
                alpha,
                chroma_key,
                threshold,
                fringe_threshold,
                fringe_delta,
            ):
                candidates[y * width + x] = 1

    mask = bytearray(width * height)
    stack: list[int] = []
    for x, y in edge_pixel_positions(width, height):
        index = y * width + x
        if candidates[index] and not mask[index]:
            mask[index] = 1
            stack.append(index)

    while stack:
        current = stack.pop()
        x = current % width
        y = current // width
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if nx < 0 or ny < 0 or nx >= width or ny >= height:
                continue
            index = ny * width + nx
            if candidates[index] and not mask[index]:
                mask[index] = 1
                stack.append(index)
    return mask


def expanded_mask(mask: bytearray, width: int, height: int) -> bytearray:
    expanded = bytearray(mask)
    for y in range(height):
        row = y * width
        for x in range(width):
            if not mask[row + x]:
                continue
            for ny in range(max(0, y - 1), min(height, y + 2)):
                target = ny * width
                for nx in range(max(0, x - 1), min(width, x + 2)):
                    expanded[target + nx] = 1
    return expanded


def remove_chroma_background(
    image: Image.Image,
    chroma_key: tuple[int, int, int],
    threshold: float,
    fringe_threshold: float,
    fringe_delta: float,
) -> Image.Image:
    rgba = image.convert("RGBA")
    pixels = rgba.load()
    background = chroma_background_mask(rgba, chroma_key, threshold, fringe_threshold, fringe_delta)
    near_background = expanded_mask(background, rgba.width, rgba.height)
    threshold_sq = threshold * threshold
    fringe_threshold_sq = fringe_threshold * fringe_threshold
    for y in range(rgba.height):
        for x in range(rgba.width):
            red, green, blue, alpha = pixels[x, y]
            color = (red, green, blue)
            index = y * rgba.width + x
            distance_sq = color_distance_sq(color, chroma_key)
            distance = math.sqrt(distance_sq)
            if background[index]:
                pixels[x, y] = (0, 0, 0, 0)
            elif alpha and near_background[index] and distance_sq <= threshold_sq:
                pixels[x, y] = (0, 0, 0, 0)
            elif alpha and near_background[index] and distance_sq <= fringe_threshold_sq:
                softened_alpha = softened_edge_alpha(alpha, distance, threshold, fringe_threshold)
                if softened_alpha <= 16:
                    pixels[x, y] = (0, 0, 0, 0)
                    continue
                if key_tint_score(color, chroma_key) >= fringe_delta:
                    neutral_red, neutral_green, neutral_blue = neutralize_key_tint(color, chroma_key)
                    pixels[x, y] = (neutral_red, neutral_green, neutral_blue, softened_alpha)
                else:
                    pixels[x, y] = (red, green, blue, softened_alpha)
            elif alpha and (distance_sq <= threshold_sq or key_tint_score(color, chroma_key) >= fringe_delta):
                neutral_red, neutral_green, neutral_blue = neutralize_key_tint(color, chroma_key)
                pixels[x, y] = (neutral_red, neutral_green, neutral_blue, alpha)
            elif alpha == 0 and (red or green or blue):
                pixels[x, y] = (0, 0, 0, 0)
    return rgba


def edge_pixel_positions(width: int, height: int):
    for x in range(width):
        yield x, 0
        if height > 1:
            yield x, height - 1
    for y in range(1, max(1, height - 1)):
        yield 0, y
        if width > 1:
            yield width - 1, y


def transparent_edge_ratio(image: Image.Image) -> float:
    rgba = image.convert("RGBA")
    pixels = rgba.load()
    total = 0
    transparent = 0
    for x, y in edge_pixel_positions(rgba.width, rgba.height):
        total += 1
        if pixels[x, y][3] <= 16:
            transparent += 1
    return transparent / total if total else 0.0


def chroma_edge_ratio(image: Image.Image, chroma_key: tuple[int, int, int], threshold: float) -> float:
    rgba = image.convert("RGBA")
    pixels = rgba.load()
    total = 0
    chroma = 0
    for x, y in edge_pixel_positions(rgba.width, rgba.height):
        red, green, blue, alpha = pixels[x, y]
        if alpha <= 16:
            continue
        total += 1
        if color_distance((red, green, blue), chroma_key) <= threshold:
            chroma += 1
    return chroma / total if total else 0.0


def edge_palette_colors(image: Image.Image, threshold: float, max_colors: int) -> list[tuple[int, int, int]]:
    rgba = image.convert("RGBA")
    pixels = rgba.load()
    colors: Counter[tuple[int, int, int]] = Counter()
    for x, y in edge_pixel_positions(rgba.width, rgba.height):
        red, green, blue, alpha = pixels[x, y]
        if alpha <= 16:
            continue
        colors[(red, green, blue)] += 1
    if not colors:
        return []

    selected: list[tuple[int, int, int]] = []
    for color, _count in colors.most_common():
        if any(color_distance(color, existing) <= threshold for existing in selected):
            continue
        selected.append(color)
        if len(selected) >= max_colors:
            break
    return selected


def matte_edge_ratio(image: Image.Image, threshold: float, max_colors: int) -> float:
    rgba = image.convert("RGBA")
    colors = edge_palette_colors(rgba, threshold, max_colors)
    if not colors:
        return 0.0
    pixels = rgba.load()
    total = 0
    matched = 0
    for x, y in edge_pixel_positions(rgba.width, rgba.height):
        red, green, blue, alpha = pixels[x, y]
        if alpha <= 16:
            continue
        total += 1
        if any(color_distance((red, green, blue), color) <= threshold for color in colors):
            matched += 1
    return matched / total if total else 0.0


def matte_background_mask(image: Image.Image, threshold: float, max_colors: int) -> bytearray:
    rgba = image.convert("RGBA")
    colors = edge_palette_colors(rgba, threshold, max_colors)
    if not colors:
        return bytearray(rgba.width * rgba.height)

    pixels = rgba.load()
    width, height = rgba.size
    candidates = bytearray(width * height)
    for y in range(height):
        for x in range(width):
            red, green, blue, alpha = pixels[x, y]
            if alpha <= 16 or any(color_distance((red, green, blue), color) <= threshold for color in colors):
                candidates[y * width + x] = 1

    mask = bytearray(width * height)
    stack: list[int] = []
    for x, y in edge_pixel_positions(width, height):
        index = y * width + x
        if candidates[index] and not mask[index]:
            mask[index] = 1
            stack.append(index)

    while stack:
        current = stack.pop()
        x = current % width
        y = current // width
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if nx < 0 or ny < 0 or nx >= width or ny >= height:
                continue
            index = ny * width + nx
            if candidates[index] and not mask[index]:
                mask[index] = 1
                stack.append(index)
    return mask


def remove_matte_background(image: Image.Image, threshold: float, max_colors: int) -> Image.Image:
    rgba = image.convert("RGBA")
    pixels = rgba.load()
    background = matte_background_mask(rgba, threshold, max_colors)
    for y in range(rgba.height):
        for x in range(rgba.width):
            if background[y * rgba.width + x]:
                pixels[x, y] = (0, 0, 0, 0)
    return rgba


def near_transparent_mask(image: Image.Image, passes: int) -> bytearray:
    alpha = image.convert("RGBA").getchannel("A")
    width, height = image.size
    mask = bytearray(width * height)
    data = alpha.tobytes()
    for index, value in enumerate(data):
        if value <= 16:
            mask[index] = 1
    for _ in range(max(0, passes)):
        mask = expanded_mask(mask, width, height)
    return mask


def refine_cutout_edges(
    image: Image.Image,
    background_colors: list[tuple[int, int, int]],
    threshold: float,
    feather: float,
    passes: int,
) -> Image.Image:
    """Remove border fringe pixels that still match the removed background.

    This is intentionally conservative: only pixels adjacent to transparent
    background are touched, and only when their RGB remains close to the sampled
    background palette. It helps opaque imagegen matte/key outputs with light
    halos without globally deleting white clothing or bright highlights.
    """
    if not background_colors or passes <= 0:
        return image.convert("RGBA")
    rgba = image.convert("RGBA")
    near = near_transparent_mask(rgba, passes)
    pixels = rgba.load()
    fringe = max(threshold, threshold + feather)
    for y in range(rgba.height):
        for x in range(rgba.width):
            index = y * rgba.width + x
            if not near[index]:
                continue
            red, green, blue, alpha = pixels[x, y]
            if alpha <= 16:
                continue
            distance = min(color_distance((red, green, blue), color) for color in background_colors)
            if distance <= threshold:
                pixels[x, y] = (0, 0, 0, 0)
            elif distance < fringe:
                softened_alpha = round(alpha * smoothstep(threshold, fringe, distance))
                if softened_alpha <= 16:
                    pixels[x, y] = (0, 0, 0, 0)
                else:
                    pixels[x, y] = (red, green, blue, softened_alpha)
    return rgba


def effective_edge_feather(args: argparse.Namespace) -> float:
    """Keep pixel-art cutouts binary while retaining soft illustration edges."""

    return 0.0 if bool(getattr(args, "pixel_art", False)) else args.edge_refine_feather


def normalize_background_removal(request: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    raw = request.get("background_removal")
    config = raw if isinstance(raw, dict) else {}
    default_method = "none" if request.get("extraction_mode") == "slots" and str(request.get("asset_kind")) in {"texture", "tileset"} else "auto"
    method = str(config.get("method", default_method))
    if args.background_removal != "request":
        method = args.background_removal
    if method not in BACKGROUND_REMOVAL_METHODS:
        raise SystemExit("background_removal.method must be none, chroma, matte, rembg, ben2, or auto")
    model = args.background_model or str(config.get("model", default_background_model(method)))
    device = str(config.get("device", "auto"))
    if args.background_device:
        device = args.background_device
    alpha_matting = config.get("alpha_matting", False)
    if args.alpha_matting is not None:
        alpha_matting = args.alpha_matting
    if not isinstance(alpha_matting, bool):
        raise SystemExit("background_removal.alpha_matting must be boolean")
    post_rembg_chroma_cleanup = config.get("post_rembg_chroma_cleanup", False)
    if args.post_rembg_chroma_cleanup is not None:
        post_rembg_chroma_cleanup = args.post_rembg_chroma_cleanup
    if not isinstance(post_rembg_chroma_cleanup, bool):
        raise SystemExit("background_removal.post_rembg_chroma_cleanup must be boolean")
    generation_background = request.get("generation_background")
    inferred_family = (
        "neutral"
        if isinstance(generation_background, dict)
        and generation_background.get("family") == "neutral"
        else "legacy-chroma"
    )
    source_family = str(config.get("source_family", inferred_family))
    if source_family not in {"neutral", "legacy-chroma", "unknown"}:
        raise SystemExit(
            "background_removal.source_family must be neutral, legacy-chroma, or unknown"
        )
    if post_rembg_chroma_cleanup and source_family != "legacy-chroma":
        raise SystemExit(
            "post_rembg_chroma_cleanup is valid only for legacy-chroma sources"
        )
    return {
        "method": method,
        "model": model,
        "device": device,
        "alpha_matting": alpha_matting,
        "post_rembg_chroma_cleanup": post_rembg_chroma_cleanup,
        "source_family": source_family,
        "matte_threshold": args.matte_threshold,
        "matte_max_colors": args.matte_max_colors,
        "edge_refine": args.edge_refine,
        "edge_refine_threshold": args.edge_refine_threshold,
        "edge_refine_feather": effective_edge_feather(args),
        "edge_refine_passes": args.edge_refine_passes,
        "chroma_mask": "border-connected",
        "chroma_matte": "soft-edge-despill",
        "matte_mask": "edge-palette-border-connected",
    }


def remove_rembg_background(
    image: Image.Image,
    config: dict[str, Any],
    sessions: dict[str, Any],
) -> Image.Image:
    try:
        from rembg import new_session, remove
    except ImportError as exc:
        raise RuntimeError(
            'background_removal=rembg requires rembg; install with: pip install "rembg[cpu]"'
        ) from exc

    model = str(config.get("model") or DEFAULT_REMBG_MODEL)
    if model not in sessions:
        sessions[model] = new_session(model)
    source = io.BytesIO()
    image.convert("RGBA").save(source, format="PNG")
    output = remove(
        source.getvalue(),
        session=sessions[model],
        alpha_matting=bool(config.get("alpha_matting", False)),
        force_return_bytes=True,
    )
    return Image.open(io.BytesIO(output)).convert("RGBA")


def resolve_torch_device(preferred: str, torch: Any) -> str:
    if preferred != "auto":
        return preferred
    return "cuda" if torch.cuda.is_available() else "cpu"


def remove_ben2_background(
    image: Image.Image,
    config: dict[str, Any],
    sessions: dict[str, Any],
) -> Image.Image:
    try:
        import torch
        from ben2 import AutoModel
    except ImportError as exc:
        raise RuntimeError(
            "background_removal=ben2 requires BEN2 and torch; install with: "
            "pip install git+https://github.com/PramaLLC/BEN2.git"
        ) from exc

    model = str(config.get("model") or DEFAULT_BEN2_MODEL)
    device = resolve_torch_device(str(config.get("device") or "auto"), torch)
    session_key = f"ben2:{model}:{device}"
    if session_key not in sessions:
        loaded = AutoModel.from_pretrained(model)
        loaded.to(device).eval()
        sessions[session_key] = loaded
    with torch.inference_mode():
        cutout = sessions[session_key].inference(image.convert("RGB"))
    return cutout.convert("RGBA")


def remove_background(
    image: Image.Image,
    chroma_key: tuple[int, int, int],
    config: dict[str, Any],
    args: argparse.Namespace,
    sessions: dict[str, Any],
) -> tuple[Image.Image, str]:
    source = image.convert("RGBA")
    method = str(config["method"])
    if method == "none":
        return source, "none"
    if method == "auto":
        if transparent_edge_ratio(source) >= 0.70:
            return source, "alpha"
        if (
            config.get("source_family") == "legacy-chroma"
            and chroma_edge_ratio(source, chroma_key, args.key_threshold) >= 0.45
        ):
            method = "chroma"
        elif matte_edge_ratio(source, args.matte_threshold, args.matte_max_colors) >= 0.82:
            method = "matte"
        else:
            method = "rembg"
    if method == "matte":
        cutout = remove_matte_background(source, args.matte_threshold, args.matte_max_colors)
        if args.edge_refine != "off":
            cutout = refine_cutout_edges(
                cutout,
                edge_palette_colors(source, args.matte_threshold, args.matte_max_colors),
                args.edge_refine_threshold,
                effective_edge_feather(args),
                args.edge_refine_passes,
            )
        return cutout, "matte"
    if method == "rembg":
        cutout = remove_rembg_background(source, config, sessions)
        if config.get("post_rembg_chroma_cleanup"):
            cutout = remove_chroma_background(
                cutout,
                chroma_key,
                args.key_threshold,
                args.fringe_key_threshold,
                args.fringe_delta,
            )
        if args.edge_refine == "conservative":
            cutout = refine_cutout_edges(
                cutout,
                edge_palette_colors(source, args.matte_threshold, args.matte_max_colors),
                args.edge_refine_threshold,
                effective_edge_feather(args),
                args.edge_refine_passes,
            )
        return cutout, "rembg"
    if method == "ben2":
        cutout = remove_ben2_background(source, config, sessions)
        if args.edge_refine == "conservative":
            cutout = refine_cutout_edges(
                cutout,
                edge_palette_colors(source, args.matte_threshold, args.matte_max_colors),
                args.edge_refine_threshold,
                effective_edge_feather(args),
                args.edge_refine_passes,
            )
        return cutout, "ben2"
    cutout = remove_chroma_background(
        source,
        chroma_key,
        args.key_threshold,
        args.fringe_key_threshold,
        args.fringe_delta,
    )
    if args.edge_refine != "off":
        cutout = refine_cutout_edges(
            cutout,
            [chroma_key],
            args.edge_refine_threshold,
            effective_edge_feather(args),
            args.edge_refine_passes,
        )
    return cutout, "chroma"


def checkerboard(size: tuple[int, int], cell: int = 8) -> Image.Image:
    width, height = size
    image = Image.new("RGBA", size, (224, 224, 224, 255))
    draw = ImageDraw.Draw(image)
    for y in range(0, height, cell):
        for x in range(0, width, cell):
            fill = (182, 182, 182, 255) if ((x // cell) + (y // cell)) % 2 else (238, 238, 238, 255)
            draw.rectangle((x, y, min(width, x + cell), min(height, y + cell)), fill=fill)
    return image


def composite_on_color(image: Image.Image, color: tuple[int, int, int]) -> Image.Image:
    background = Image.new("RGBA", image.size, (*color, 255))
    background.alpha_composite(image.convert("RGBA"))
    return background


def alpha_mask_preview(image: Image.Image) -> Image.Image:
    alpha = image.convert("RGBA").getchannel("A")
    return Image.merge("RGBA", (alpha, alpha, alpha, Image.new("L", alpha.size, 255)))


def fit_preview(image: Image.Image, max_width: int, max_height: int) -> Image.Image:
    scale = min(max_width / image.width, max_height / image.height, 1.0)
    if scale >= 0.999:
        return image.copy()
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    return image.resize(size, Image.Resampling.NEAREST)


def labeled_preview(label: str, image: Image.Image, width: int, height: int) -> Image.Image:
    target = Image.new("RGBA", (width, height + 18), (18, 18, 18, 255))
    target.alpha_composite(fit_preview(image, width, height), (0, 18))
    draw = ImageDraw.Draw(target)
    draw.text((4, 3), label, fill=(235, 235, 235, 255))
    return target


def save_background_matte_review(entries: list[dict[str, Any]], out_dir: Path) -> str | None:
    if not entries:
        return None
    qa_dir = out_dir / "qa"
    qa_dir.mkdir(parents=True, exist_ok=True)
    panel_width = 260
    panel_height = 92
    gutter = 8
    label_height = 20
    row_width = panel_width * 6 + gutter * 7
    row_height = panel_height + label_height + gutter * 2
    review = Image.new("RGBA", (row_width, row_height * len(entries)), (7, 7, 7, 255))
    draw = ImageDraw.Draw(review)
    for row_index, entry in enumerate(entries):
        y = row_index * row_height
        state = str(entry["state"])
        method = str(entry["method"])
        raw = entry["raw"].convert("RGBA")
        processed = entry["processed"].convert("RGBA")
        checker = checkerboard(processed.size)
        checker.alpha_composite(processed)
        panels = [
            labeled_preview("raw source", raw, panel_width, panel_height),
            labeled_preview("processed on checker", checker, panel_width, panel_height),
            labeled_preview("processed on black", composite_on_color(processed, (0, 0, 0)), panel_width, panel_height),
            labeled_preview("processed on gray", composite_on_color(processed, (128, 128, 128)), panel_width, panel_height),
            labeled_preview("processed on white", composite_on_color(processed, (255, 255, 255)), panel_width, panel_height),
            labeled_preview("alpha mask", alpha_mask_preview(processed), panel_width, panel_height),
        ]
        draw.text((gutter, y + 4), f"{state} | {method}", fill=(245, 245, 245, 255))
        for index, panel in enumerate(panels):
            x = gutter + index * (panel_width + gutter)
            review.alpha_composite(panel, (x, y + label_height))
    path = qa_dir / "background-matte-review.png"
    atomic_save_image(review, path)
    return path.relative_to(out_dir).as_posix()


def connected_components(image: Image.Image) -> list[dict[str, Any]]:
    alpha = image.getchannel("A")
    width, height = image.size
    data = alpha.tobytes()
    visited = bytearray(width * height)
    components: list[dict[str, Any]] = []

    for start, alpha_value in enumerate(data):
        if alpha_value <= 16 or visited[start]:
            continue
        stack = [start]
        visited[start] = 1
        pixels: list[int] = []
        min_x = width
        min_y = height
        max_x = 0
        max_y = 0

        while stack:
            current = stack.pop()
            pixels.append(current)
            x = current % width
            y = current // width
            min_x = min(min_x, x)
            min_y = min(min_y, y)
            max_x = max(max_x, x)
            max_y = max(max_y, y)

            for neighbor in (current - 1, current + 1, current - width, current + width):
                if neighbor < 0 or neighbor >= len(data) or visited[neighbor]:
                    continue
                nx = neighbor % width
                if abs(nx - x) > 1:
                    continue
                if data[neighbor] > 16:
                    visited[neighbor] = 1
                    stack.append(neighbor)

        components.append(
            {
                "pixels": pixels,
                "area": len(pixels),
                "bbox": (min_x, min_y, max_x + 1, max_y + 1),
                "center_x": (min_x + max_x + 1) / 2,
            }
        )
    return components


def component_group_image(source: Image.Image, components: list[dict[str, Any]], padding: int = 4) -> Image.Image:
    width, height = source.size
    min_x = max(0, min(component["bbox"][0] for component in components) - padding)
    min_y = max(0, min(component["bbox"][1] for component in components) - padding)
    max_x = min(width, max(component["bbox"][2] for component in components) + padding)
    max_y = min(height, max(component["bbox"][3] for component in components) + padding)
    output = Image.new("RGBA", (max_x - min_x, max_y - min_y), (0, 0, 0, 0))
    source_pixels = source.load()
    output_pixels = output.load()
    for component in components:
        for pixel_index in component["pixels"]:
            x = pixel_index % width
            y = pixel_index // width
            output_pixels[x - min_x, y - min_y] = source_pixels[x, y]
    return output


def cell_geometry(cell: dict[str, Any]) -> tuple[int, int, int, int]:
    width = int(cell.get("width", cell.get("size", 0)))
    height = int(cell.get("height", cell.get("size", 0)))
    safe_margin_x = int(cell.get("safe_margin_x", cell.get("safe_margin", 0)))
    safe_margin_y = int(cell.get("safe_margin_y", cell.get("safe_margin", 0)))
    if width <= 0 or height <= 0:
        raise SystemExit("cell width/height must be positive in sprite-request.json")
    return width, height, safe_margin_x, safe_margin_y


def state_tokens(state: str, entry: dict[str, Any] | None = None) -> set[str]:
    text = state
    if entry:
        text = f"{text} {entry.get('action', '')}"
    return {token for token in re.split(r"[^a-z0-9]+", text.lower()) if token}


def inferred_pose_geometry(state: str, entry: dict[str, Any]) -> dict[str, Any] | None:
    tokens = state_tokens(state, entry)
    if tokens & {"crouch", "crouching", "duck", "ducking", "squat", "squatting"}:
        return {
            "kind": "crouch",
            "grounded": True,
            "height_curve": "compress",
            "start_height_vs_reference": 1.00,
            "target_height_vs_reference": 0.70,
            "min_height_vs_reference": 0.62,
            "min_width_vs_reference": 0.78,
            "min_head_width_vs_reference": 0.84,
            "min_upper_width_vs_reference": 0.84,
            "max_height_vs_reference": 1.05,
            "baseline": "feet",
        }
    if tokens & {"knockdown", "downed", "collapse", "collapsing"}:
        return {
            "kind": "knockdown",
            "grounded": False,
            "target_height_vs_reference": 0.70,
            "max_height_vs_reference": 1.12,
            "min_height_vs_reference": 0.45,
            "baseline": "collapse",
        }
    if tokens & {"jump", "jumping", "leap", "leaping", "airborne"}:
        return {
            "kind": "jump",
            "grounded": False,
            "target_height_vs_reference": 1.00,
            "max_height_vs_reference": 1.12,
            "min_head_width_vs_reference": 0.90,
            "min_upper_width_vs_reference": 0.72,
            "arc_peak_ratio": 0.22,
            "baseline": "jump-arc",
        }
    if tokens & {"fall", "falling"}:
        return {
            "kind": "fall",
            "grounded": False,
            "target_height_vs_reference": 1.00,
            "max_height_vs_reference": 1.12,
            "min_head_width_vs_reference": 0.90,
            "min_upper_width_vs_reference": 0.88,
            "airborne_bottom_ratio": 0.18,
            "baseline": "airborne",
        }
    if tokens & {"land", "landing"}:
        return {
            "kind": "land",
            "grounded": True,
            "target_height_vs_reference": 0.78,
            "max_height_vs_reference": 0.95,
            "min_head_width_vs_reference": 0.86,
            "min_upper_width_vs_reference": 0.86,
            "baseline": "feet",
        }
    return None


def state_pose_geometry(state: str, entry: dict[str, Any]) -> dict[str, Any] | None:
    raw = entry.get("pose_geometry")
    if raw is False or raw == "none":
        return None
    inferred = inferred_pose_geometry(state, entry) or {}
    if raw is None:
        return inferred or None
    if not isinstance(raw, dict):
        return inferred or None
    if raw.get("enabled") is False:
        return None
    merged = {**inferred, **raw}
    if merged.get("kind") == "crouch" and str(merged.get("height_curve", "")) == "compress":
        start_ratio = float(merged.get("start_height_vs_reference", 1.0))
        max_ratio = float(merged.get("max_height_vs_reference", start_ratio))
        if max_ratio < start_ratio:
            merged["max_height_vs_reference"] = start_ratio
        if isinstance(raw, dict) and "height_curve" not in raw:
            inferred_target = float(inferred.get("target_height_vs_reference", 0.70))
            target_ratio = float(merged.get("target_height_vs_reference", inferred_target))
            if target_ratio < inferred_target:
                merged["target_height_vs_reference"] = inferred_target
                merged["guide_height_ratio"] = inferred_target
    return merged or None


def side_view_locomotion_geometry(request: dict[str, Any], state: str, entry: dict[str, Any]) -> dict[str, Any] | None:
    preset = request.get("preset") if isinstance(request.get("preset"), dict) else {}
    camera = str(preset.get("camera") or "").lower()
    if not (camera == "side" or "side" in camera or camera == "mascot"):
        return None
    tokens = state_tokens(state, entry)
    action = str(entry.get("action", "")).lower()
    if not (tokens & {"walk", "walking", "run", "running"} or "locomotion" in action):
        return None
    return {
        "kind": "grounded-locomotion",
        "grounded": True,
        "target_height_vs_reference": 1.00,
        "max_height_vs_reference": 1.12,
        "baseline": "feet",
    }


def jump_arc_offset(frame_index: int, frames: int, safe_height: int, peak_ratio: float) -> int:
    if frames <= 1:
        return 0
    return round(math.sin(math.pi * frame_index / (frames - 1)) * safe_height * peak_ratio)


def smooth_progress(frame_index: int, frames: int) -> float:
    if frames <= 1:
        return 1.0
    progress = max(0.0, min(1.0, frame_index / (frames - 1)))
    return progress * progress * (3 - 2 * progress)


def pose_frame_height_ratio(pose_geometry: dict[str, Any], frame_index: int, frames: int) -> float:
    kind = str(pose_geometry.get("kind", ""))
    max_ratio = float(pose_geometry.get("max_height_vs_reference", pose_geometry.get("max_height_vs_idle", 1.15)))
    target_ratio = float(pose_geometry.get("target_height_vs_reference", max_ratio))
    curve = str(pose_geometry.get("height_curve", ""))
    if kind == "crouch" or curve == "compress":
        start_ratio = float(pose_geometry.get("start_height_vs_reference", min(1.0, max_ratio)))
        progress = smooth_progress(frame_index, frames)
        return min(max_ratio, start_ratio + (target_ratio - start_ratio) * progress)
    return max_ratio


def locks_reference_scale(pose_geometry: dict[str, Any] | None) -> bool:
    if not pose_geometry:
        return False
    kind = str(pose_geometry.get("kind", ""))
    curve = str(pose_geometry.get("height_curve", ""))
    return kind in {"crouch", "jump", "fall", "land"} or curve == "compress"


def pose_top_margin(pose_geometry: dict[str, Any] | None, safe_margin_y: int) -> int:
    if not pose_geometry:
        return safe_margin_y
    kind = str(pose_geometry.get("kind", ""))
    if kind in {"jump", "fall"}:
        return 0
    return safe_margin_y


def stable_feature_scale(
    sprite: Image.Image,
    pose_geometry: dict[str, Any] | None,
    reference_metrics: dict[str, float] | None,
) -> float | None:
    if not locks_reference_scale(pose_geometry) or not reference_metrics:
        return None
    base_scale = reference_metrics.get("scale")
    if not isinstance(base_scale, (int, float)) or base_scale <= 0:
        return None
    sprite_metrics = stable_feature_metrics(sprite)
    scale = float(base_scale)
    for metric_key, floor_key in (
        ("head_width", "min_head_width_vs_reference"),
        ("upper_width", "min_upper_width_vs_reference"),
    ):
        reference_value = reference_metrics.get(metric_key)
        sprite_value = sprite_metrics.get(metric_key)
        floor = float(pose_geometry.get(floor_key, 0.0)) if pose_geometry else 0.0
        if not reference_value or not sprite_value or floor <= 0:
            continue
        scale = max(scale, (float(reference_value) * floor) / float(sprite_value))
    return scale


def pose_bottom_y(pose_geometry: dict[str, Any], frame_index: int, frames: int, cell_height: int, safe_margin_y: int) -> int:
    safe_height = cell_height - safe_margin_y * 2
    baseline_y = cell_height - safe_margin_y
    kind = str(pose_geometry.get("kind", ""))
    if kind == "jump":
        peak_ratio = float(pose_geometry.get("arc_peak_ratio", 0.22))
        return baseline_y - jump_arc_offset(frame_index, frames, safe_height, peak_ratio)
    if kind == "fall":
        return baseline_y - round(safe_height * float(pose_geometry.get("airborne_bottom_ratio", 0.18)))
    return baseline_y


def fit_to_cell(
    image: Image.Image,
    cell_width: int,
    cell_height: int,
    safe_margin_x: int,
    safe_margin_y: int,
    *,
    max_height: int | None = None,
    bottom_y: int | None = None,
    scale_override: float | None = None,
    top_margin: int | None = None,
    resize_policy: ResizePolicy | None = None,
) -> Image.Image:
    bbox = image.getbbox()
    target = Image.new("RGBA", (cell_width, cell_height), (0, 0, 0, 0))
    if bbox is None:
        return target
    sprite = image.crop(bbox)
    max_width = max(1, cell_width - safe_margin_x * 2)
    available_height = max(1, cell_height - safe_margin_y * 2)
    if max_height is not None:
        max_height = max(1, min(max_height, available_height))
    else:
        max_height = available_height
    fit_scale = min(max_width / sprite.width, max_height / sprite.height, 1.0)
    scale = min(scale_override, fit_scale) if scale_override else fit_scale
    if scale != 1.0:
        source_sprite = sprite
        sprite = resize_image(
            source_sprite,
            (max(1, round(sprite.width * scale)), max(1, round(sprite.height * scale))),
            policy=resize_policy or ResizePolicy(mode=ArtMode.ILLUSTRATED),
        )
        if resize_policy is not None and resize_policy.mode is ArtMode.PIXEL:
            invariants = inspect_transform_invariants(source_sprite, sprite)
            if not invariants.ok:
                raise ImagePolicyError(
                    "pixel resize violated palette or hard-alpha invariants"
                )
    left = (cell_width - sprite.width) // 2
    if bottom_y is None:
        top = (cell_height - sprite.height) // 2
    else:
        min_top = safe_margin_y if top_margin is None else top_margin
        top = round(bottom_y - sprite.height)
        top = max(min_top, min(cell_height - safe_margin_y - sprite.height, top))
    target.alpha_composite(sprite, (left, top))
    return target


def central_alpha_run_width(alpha: Image.Image, y: int, center_x: int, min_alpha: int = 16) -> int:
    width, _height = alpha.size
    pixels = alpha.load()
    x = center_x
    if pixels[x, y] <= min_alpha:
        fallback = None
        search_radius = max(2, width // 5)
        for delta in range(search_radius + 1):
            for candidate in (center_x - delta, center_x + delta):
                if 0 <= candidate < width and pixels[candidate, y] > min_alpha:
                    fallback = candidate
                    break
            if fallback is not None:
                break
        if fallback is None:
            return 0
        x = fallback
    left = x
    right = x
    while left - 1 >= 0 and pixels[left - 1, y] > min_alpha:
        left -= 1
    while right + 1 < width and pixels[right + 1, y] > min_alpha:
        right += 1
    return right - left + 1


def stable_feature_metrics(image: Image.Image) -> dict[str, int]:
    rgba = image.convert("RGBA")
    bbox = rgba.getbbox()
    if not bbox:
        return {key: 0 for key in STABLE_FEATURE_KEYS}
    left, top, right, bottom = bbox
    height = max(1, bottom - top)
    center_x = (left + right) // 2
    alpha = rgba.getchannel("A")
    head_runs: list[int] = []
    upper_runs: list[int] = []
    torso_runs: list[int] = []
    for y in range(top, bottom):
        rel_y = (y - top) / height
        run = central_alpha_run_width(alpha, y, center_x)
        if run <= 0:
            continue
        if 0.03 <= rel_y <= 0.35:
            head_runs.append(run)
        if 0.15 <= rel_y <= 0.55:
            upper_runs.append(run)
        if 0.45 <= rel_y <= 0.82:
            torso_runs.append(run)

    def middle(values: list[int]) -> int:
        if not values:
            return 0
        ordered = sorted(values)
        return int(ordered[len(ordered) // 2])

    body_mass_width, body_mass_height = alpha_mass_extent_80(rgba)
    return {
        "head_width": middle(head_runs),
        "upper_width": middle(upper_runs),
        "torso_width": middle(torso_runs),
        "opaque_area": alpha_nonzero_count(rgba),
        "body_mass_width_80": body_mass_width,
        "body_mass_height_80": body_mass_height,
    }


def raw_layout_grid(entry: dict[str, Any], frame_count: int) -> tuple[int, int]:
    raw = entry.get("raw_layout") if isinstance(entry, dict) else None
    if isinstance(raw, dict):
        columns = int(raw.get("columns", raw.get("cols", frame_count)))
        rows = int(raw.get("rows", 1))
        if columns > 0 and rows > 0 and columns * rows >= frame_count:
            return columns, rows
    return frame_count, 1


def raw_cell_rect(sheet: Image.Image, columns: int, rows: int, index: int) -> tuple[int, int, int, int]:
    column = index % columns
    row = index // columns
    left = round(column * sheet.width / columns)
    right = round((column + 1) * sheet.width / columns)
    top = round(row * sheet.height / rows)
    bottom = round((row + 1) * sheet.height / rows)
    return left, top, right, bottom


def sprite_from_cell(cell: Image.Image) -> Image.Image | None:
    components = connected_components(cell)
    if not components:
        return None
    largest_area = max(component["area"] for component in components)
    keep_threshold = max(12, largest_area * 0.015)
    kept = [component for component in components if component["area"] >= keep_threshold]
    return component_group_image(cell, kept or components)


def extract_grid_component_sprites(sheet: Image.Image, frame_count: int, columns: int, rows: int) -> list[Image.Image] | None:
    sprites: list[Image.Image] = []
    for index in range(frame_count):
        left, top, right, bottom = raw_cell_rect(sheet, columns, rows, index)
        cell = sheet.crop((left, top, right, bottom))
        sprite = sprite_from_cell(cell)
        if sprite is None:
            return None
        sprites.append(sprite)
    return sprites


def extract_grid_slot_sprites(sheet: Image.Image, frame_count: int, columns: int, rows: int) -> list[Image.Image]:
    sprites: list[Image.Image] = []
    for index in range(frame_count):
        left, top, right, bottom = raw_cell_rect(sheet, columns, rows, index)
        sprites.append(sheet.crop((left, top, right, bottom)))
    return sprites


def extract_component_sprites(strip: Image.Image, frame_count: int) -> list[Image.Image] | None:
    components = connected_components(strip)
    if not components:
        return None
    largest_area = max(component["area"] for component in components)
    seed_threshold = max(120, largest_area * 0.20)
    seeds = [component for component in components if component["area"] >= seed_threshold]
    if len(seeds) < frame_count:
        seeds = sorted(components, key=lambda component: component["area"], reverse=True)[:frame_count]
    if len(seeds) < frame_count:
        return None

    seeds = sorted(
        sorted(seeds, key=lambda component: component["area"], reverse=True)[:frame_count],
        key=lambda component: component["center_x"],
    )
    seed_ids = {id(seed) for seed in seeds}
    groups: list[list[dict[str, Any]]] = [[seed] for seed in seeds]
    noise_threshold = max(12, largest_area * 0.002)

    for component in components:
        if id(component) in seed_ids or component["area"] < noise_threshold:
            continue
        nearest_index = min(
            range(len(seeds)),
            key=lambda index: abs(seeds[index]["center_x"] - component["center_x"]),
        )
        groups[nearest_index].append(component)

    return [component_group_image(strip, group) for group in groups]


def extract_component_frames(strip: Image.Image, frame_count: int, cell_width: int, cell_height: int, safe_margin_x: int, safe_margin_y: int) -> list[Image.Image] | None:
    sprites = extract_component_sprites(strip, frame_count)
    if sprites is None:
        return None
    return [fit_to_cell(sprite, cell_width, cell_height, safe_margin_x, safe_margin_y) for sprite in sprites]


def extract_slot_sprites(strip: Image.Image, frame_count: int) -> list[Image.Image]:
    slot_width = strip.width / frame_count
    sprites = []
    for index in range(frame_count):
        left = round(index * slot_width)
        right = round((index + 1) * slot_width)
        sprites.append(strip.crop((left, 0, right, strip.height)))
    return sprites


def extract_slot_frames(strip: Image.Image, frame_count: int, cell_width: int, cell_height: int, safe_margin_x: int, safe_margin_y: int) -> list[Image.Image]:
    frames = []
    for sprite in extract_slot_sprites(strip, frame_count):
        frames.append(fit_to_cell(sprite, cell_width, cell_height, safe_margin_x, safe_margin_y))
    return frames


def fitted_height(sprite: Image.Image, cell_width: int, cell_height: int, safe_margin_x: int, safe_margin_y: int) -> int:
    frame = fit_to_cell(sprite, cell_width, cell_height, safe_margin_x, safe_margin_y)
    bbox = frame.getbbox()
    return bbox[3] - bbox[1] if bbox else 0


def fitted_reference_metric(
    sprite: Image.Image,
    cell_width: int,
    cell_height: int,
    safe_margin_x: int,
    safe_margin_y: int,
    resize_policy: ResizePolicy | None = None,
) -> dict[str, float] | None:
    bbox = sprite.getbbox()
    if not bbox:
        return None
    raw_width = bbox[2] - bbox[0]
    raw_height = bbox[3] - bbox[1]
    frame = fit_to_cell(
        sprite,
        cell_width,
        cell_height,
        safe_margin_x,
        safe_margin_y,
        resize_policy=resize_policy,
    )
    fitted_bbox = frame.getbbox()
    if not fitted_bbox or raw_width <= 0 or raw_height <= 0:
        return None
    fitted_width = fitted_bbox[2] - fitted_bbox[0]
    fitted_height_value = fitted_bbox[3] - fitted_bbox[1]
    feature_metrics = stable_feature_metrics(frame)
    return {
        "width": fitted_width,
        "height": fitted_height_value,
        "scale": min(fitted_width / raw_width, fitted_height_value / raw_height),
        **feature_metrics,
    }


def reference_row_score(state: str, entry: dict[str, Any]) -> int:
    tokens = state_tokens(state, entry)
    if "idle" in tokens:
        return 0
    if tokens & {"stand", "standing", "wait", "waiting"}:
        return 1
    if not state_pose_geometry(state, entry):
        return 2
    return 3


def reference_metrics_for_rows(
    request: dict[str, Any],
    pending_rows: list[dict[str, Any]],
    cell_width: int,
    cell_height: int,
    safe_margin_x: int,
    safe_margin_y: int,
) -> int | None:
    if str(request.get("asset_kind", "sprite")) != "sprite":
        return None
    states = request.get("states", {})
    registration = request.get("registration") if isinstance(request.get("registration"), dict) else {}
    preferred = str(registration.get("reference_state", "idle"))
    resize_policy = resize_policy_from_sampling_policy(request.get("sampling_policy"))
    candidates = sorted(
        pending_rows,
        key=lambda row: (
            0 if row["state"] == preferred else reference_row_score(row["state"], states.get(row["state"], {})),
            list(states).index(row["state"]) if row["state"] in states else 999,
        ),
    )
    for row in candidates:
        entry = states.get(row["state"], {})
        if state_pose_geometry(row["state"], entry) and row["state"] != preferred:
            continue
        metrics = [
            fitted_reference_metric(
                sprite,
                cell_width,
                cell_height,
                safe_margin_x,
                safe_margin_y,
                resize_policy,
            )
            for sprite in row["sprites"]
        ]
        metrics = [metric for metric in metrics if metric]
        if metrics:
            return {
                "height": round(median([metric["height"] for metric in metrics])),
                "width": round(median([metric["width"] for metric in metrics])),
                "scale": median([metric["scale"] for metric in metrics]),
                **{
                    key: round(median([metric[key] for metric in metrics if metric.get(key)]))
                    for key in STABLE_FEATURE_KEYS
                    if [metric[key] for metric in metrics if metric.get(key)]
                },
            }
    return None


def existing_reference_metrics(request: dict[str, Any], run_dir: Path) -> dict[str, float] | None:
    if str(request.get("asset_kind", "sprite")) != "sprite":
        return None
    states = request.get("states", {})
    registration = request.get("registration") if isinstance(request.get("registration"), dict) else {}
    preferred = str(registration.get("reference_state", "idle"))
    candidates = sorted(
        states,
        key=lambda state: (
            0 if state == preferred else reference_row_score(state, states.get(state, {})),
            list(states).index(state),
        ),
    )
    for state in candidates:
        entry = states.get(state, {})
        if state_pose_geometry(state, entry) and state != preferred:
            continue
        state_dir = run_dir / "frames" / state
        if not state_dir.is_dir():
            continue
        heights = []
        widths = []
        feature_values: dict[str, list[int]] = {key: [] for key in STABLE_FEATURE_KEYS}
        for frame_path in sorted(state_dir.glob("frame-*.png")):
            with Image.open(frame_path) as opened:
                frame = opened.convert("RGBA")
                bbox = frame.getbbox()
                metrics = stable_feature_metrics(frame)
            if bbox:
                heights.append(bbox[3] - bbox[1])
                widths.append(bbox[2] - bbox[0])
                for key in STABLE_FEATURE_KEYS:
                    if metrics.get(key):
                        feature_values[key].append(metrics[key])
        if heights:
            return {
                "height": round(median(heights)),
                "width": round(median(widths)) if widths else 0,
                "scale": None,
                **{
                    key: round(median(values))
                    for key, values in feature_values.items()
                    if values
                },
            }
    return None


def fit_pose_frames(
    sprites: list[Image.Image],
    pose_geometry: dict[str, Any] | None,
    reference_metrics: dict[str, float] | None,
    cell_width: int,
    cell_height: int,
    safe_margin_x: int,
    safe_margin_y: int,
    resize_policy: ResizePolicy | None = None,
) -> list[Image.Image]:
    frames = []
    reference_height = int(reference_metrics.get("height", 0)) if reference_metrics else None
    for index, sprite in enumerate(sprites):
        bottom_y = None
        max_height = None
        top_margin = None
        scale_override = stable_feature_scale(sprite, pose_geometry, reference_metrics)
        if pose_geometry and reference_height:
            ratio = float(pose_geometry.get("max_height_vs_reference", pose_geometry.get("max_height_vs_idle", 1.15)))
            max_height = max(1, round(reference_height * ratio))
        if pose_geometry:
            bottom_y = pose_bottom_y(pose_geometry, index, len(sprites), cell_height, safe_margin_y)
            top_margin = pose_top_margin(pose_geometry, safe_margin_y)
            if top_margin == safe_margin_y:
                arc_height_limit = max(1, bottom_y - safe_margin_y)
                max_height = min(max_height if max_height is not None else cell_height - safe_margin_y * 2, arc_height_limit)
        frames.append(
            fit_to_cell(
                sprite,
                cell_width,
                cell_height,
                safe_margin_x,
                safe_margin_y,
                max_height=max_height,
                bottom_y=bottom_y,
                scale_override=scale_override,
                top_margin=top_margin,
                resize_policy=resize_policy,
            )
        )
    return frames


def chroma_adjacent_count(image: Image.Image, chroma_key: tuple[int, int, int], threshold: float) -> int:
    count = 0
    data = image.convert("RGBA").tobytes()
    for index in range(0, len(data), 4):
        red, green, blue, alpha = data[index : index + 4]
        if alpha > 16 and color_distance((red, green, blue), chroma_key) <= threshold:
            count += 1
    return count


def inspect_pose_geometry(
    state: str,
    frames: list[Image.Image],
    pose_geometry: dict[str, Any] | None,
    reference_metrics: dict[str, float] | None,
    cell_height: int,
    safe_margin_y: int,
    args: argparse.Namespace,
) -> tuple[list[str], list[str]]:
    if not pose_geometry:
        return [], []
    bboxes = [frame.getbbox() for frame in frames]
    bboxes = [bbox for bbox in bboxes if bbox]
    if not bboxes:
        return [], []
    errors: list[str] = []
    warnings: list[str] = []
    heights = [bbox[3] - bbox[1] for bbox in bboxes]
    widths = [bbox[2] - bbox[0] for bbox in bboxes]
    bottoms = [bbox[3] for bbox in bboxes]
    kind = str(pose_geometry.get("kind", "pose"))
    baseline_y = cell_height - safe_margin_y
    reference_height = int(reference_metrics.get("height", 0)) if reference_metrics else None
    reference_width = int(reference_metrics.get("width", 0)) if reference_metrics else None
    if reference_height:
        ratios = [height / reference_height for height in heights]
        max_ratio = float(pose_geometry.get("max_height_vs_reference", pose_geometry.get("max_height_vs_idle", 1.15)))
        if max(ratios) > max_ratio + args.pose_height_tolerance:
            errors.append(f"{kind} height exceeds reference scale ({max(ratios):.2f}x vs max {max_ratio:.2f}x)")
        target_ratio = float(pose_geometry.get("target_height_vs_reference", max_ratio))
        expected = [pose_frame_height_ratio(pose_geometry, index, len(frames)) for index in range(len(frames))]
        over_expected = [
            (index, ratios[index], expected[index])
            for index in range(min(len(ratios), len(expected)))
            if ratios[index] > expected[index] + args.pose_height_tolerance
        ]
        if over_expected:
            index, actual, allowed = over_expected[0]
            errors.append(f"{kind} frame {index:02d} exceeds pose curve ({actual:.2f}x vs expected {allowed:.2f}x)")
        if kind in {"crouch", "land"} and ratios[-1] > target_ratio + args.pose_height_tolerance:
            warnings.append(f"{kind} final pose may still be tall ({ratios[-1]:.2f}x reference; target around {target_ratio:.2f}x)")
        if kind == "crouch" and len(ratios) >= 2 and ratios[-1] > ratios[0] + args.pose_height_tolerance:
            warnings.append(f"{kind} ends taller than it starts ({ratios[0]:.2f}x -> {ratios[-1]:.2f}x)")
    else:
        warnings.append(f"{kind} pose has no idle/standing reference height; scale checked within row only")
    if reference_width and kind == "crouch":
        width_ratios = [width / reference_width for width in widths]
        min_width_ratio = float(pose_geometry.get("min_width_vs_reference", args.pose_width_floor_ratio))
        if width_ratios[-1] < min_width_ratio:
            errors.append(
                f"{kind} final frame looks uniformly scaled down "
                f"(width {width_ratios[-1]:.2f}x reference; expected >= {min_width_ratio:.2f}x)"
            )
    if reference_metrics and kind in {"crouch", "jump", "fall", "land"}:
        feature_rows = [stable_feature_metrics(frame) for frame in frames]
        for metric_key, floor_key, label in (
            ("head_width", "min_head_width_vs_reference", "head proxy"),
            ("upper_width", "min_upper_width_vs_reference", "upper-body proxy"),
        ):
            reference_value = reference_metrics.get(metric_key)
            if not reference_value:
                continue
            floor = float(pose_geometry.get(floor_key, 0.0))
            if floor <= 0:
                continue
            ratios = [
                feature.get(metric_key, 0) / float(reference_value)
                for feature in feature_rows
                if feature.get(metric_key, 0)
            ]
            if ratios and min(ratios) < floor - args.pose_feature_tolerance:
                bad_index = min(range(len(ratios)), key=lambda index: ratios[index])
                errors.append(
                    f"{kind} frame {bad_index:02d} {label} shrinks "
                    f"({ratios[bad_index]:.2f}x reference; expected >= {floor:.2f}x)"
                )
    if bool(pose_geometry.get("grounded", kind in {"crouch", "land"})):
        max_baseline_delta = max(abs(bottom - baseline_y) for bottom in bottoms)
        if max_baseline_delta > args.baseline_tolerance_px:
            errors.append(f"{kind} grounded baseline drifts by {max_baseline_delta}px")
    if kind == "jump" and len(bottoms) >= 3:
        bottom_range = max(bottoms) - min(bottoms)
        if bottom_range < args.baseline_tolerance_px * 2:
            warnings.append("jump vertical arc is barely visible after extraction")
    return errors, warnings


def inspect_frames(
    frames: list[Image.Image],
    chroma_key: tuple[int, int, int],
    args: argparse.Namespace,
    *,
    state: str = "",
    pose_geometry: dict[str, Any] | None = None,
    reference_metrics: dict[str, float] | None = None,
    cell_height: int | None = None,
    safe_margin_y: int | None = None,
) -> tuple[list[str], list[str], list[dict[str, Any]]]:
    errors: list[str] = []
    warnings: list[str] = []
    records: list[dict[str, Any]] = []
    reference_height = int(reference_metrics.get("height", 0)) if reference_metrics else None
    reference_width = int(reference_metrics.get("width", 0)) if reference_metrics else None
    areas = [alpha_nonzero_count(frame) for frame in frames]
    frame_median = median(areas) if areas else 0
    for index, frame in enumerate(frames):
        nontransparent = areas[index]
        edge = edge_alpha_count(frame, args.edge_margin)
        adjacent = chroma_adjacent_count(frame, chroma_key, args.chroma_adjacent_threshold)
        bbox = frame.getbbox()
        feature_metrics = stable_feature_metrics(frame)
        height = bbox[3] - bbox[1] if bbox else 0
        width = bbox[2] - bbox[0] if bbox else 0
        bottom = bbox[3] if bbox else None
        height_ratio = round(height / reference_height, 4) if reference_height and height else None
        width_ratio = round(width / reference_width, 4) if reference_width and width else None
        expected_height_ratio = (
            round(pose_frame_height_ratio(pose_geometry, index, len(frames)), 4)
            if pose_geometry and reference_height
            else None
        )
        records.append(
            {
                "index": index,
                "nontransparent_pixels": nontransparent,
                "bbox": list(bbox) if bbox else None,
                "height_vs_reference": height_ratio,
                "width_vs_reference": width_ratio,
                **{
                    f"{key}_vs_reference": round(feature_metrics[key] / reference_metrics[key], 4)
                    for key in STABLE_FEATURE_KEYS
                    if reference_metrics and reference_metrics.get(key) and feature_metrics.get(key)
                },
                "expected_height_vs_reference": expected_height_ratio,
                "bottom_y": bottom,
                "edge_pixels": edge,
                "chroma_adjacent_pixels": adjacent,
            }
        )
        validation = validate_frame(
            frame,
            allow_full_cell=bool(getattr(args, "allow_full_cell", False)),
        )
        if bool(getattr(args, "pixel_art", False)):
            alpha_invariant = inspect_hard_alpha(frame)
            if not alpha_invariant.ok:
                errors.append(
                    f"frame {index:02d} alpha invariant violation: "
                    f"{len(alpha_invariant.new_fractional_alpha_values)} "
                    "fractional alpha values"
                )
        if args.min_used_pixels is not None:
            if nontransparent < args.min_used_pixels:
                errors.append(
                    f"frame {index:02d} is empty or too sparse ({nontransparent} pixels)"
                )
        profile_failures = validation.failures
        errors.extend(f"frame {index:02d} {failure}" for failure in profile_failures)
        if edge > args.edge_pixel_threshold:
            warnings.append(f"frame {index:02d} has {edge} non-transparent edge pixels")
        if adjacent > args.chroma_adjacent_pixel_threshold:
            errors.append(f"frame {index:02d} has {adjacent} chroma-adjacent pixels")
        if frame_median and nontransparent < frame_median * args.small_outlier_ratio:
            warnings.append(f"frame {index:02d} is much smaller than median ({nontransparent} vs {frame_median:.0f})")
        if frame_median and nontransparent > frame_median * args.large_outlier_ratio:
            warnings.append(f"frame {index:02d} is much larger than median ({nontransparent} vs {frame_median:.0f})")
    if cell_height is not None and safe_margin_y is not None:
        pose_errors, pose_warnings = inspect_pose_geometry(
            state,
            frames,
            pose_geometry,
            reference_metrics,
            cell_height,
            safe_margin_y,
            args,
        )
        errors.extend(pose_errors)
        warnings.extend(pose_warnings)
    return errors, warnings, records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--states", default="all")
    parser.add_argument("--key-threshold", type=float, default=96.0)
    parser.add_argument("--fringe-key-threshold", type=float, default=180.0)
    parser.add_argument("--fringe-delta", type=float, default=18.0)
    parser.add_argument("--allow-slot-fallback", action="store_true")
    parser.add_argument(
        "--min-used-pixels",
        type=int,
        default=None,
        help="explicit absolute sparse-frame override; default uses scale-aware profiles",
    )
    parser.add_argument("--edge-margin", type=int, default=2)
    parser.add_argument("--edge-pixel-threshold", type=int, default=24)
    parser.add_argument("--chroma-adjacent-threshold", type=float, default=150.0)
    parser.add_argument("--chroma-adjacent-pixel-threshold", type=int, default=120)
    parser.add_argument("--small-outlier-ratio", type=float, default=0.35)
    parser.add_argument("--large-outlier-ratio", type=float, default=2.75)
    parser.add_argument("--pose-height-tolerance", type=float, default=0.08)
    parser.add_argument("--pose-width-floor-ratio", type=float, default=0.78)
    parser.add_argument("--pose-feature-tolerance", type=float, default=0.04)
    parser.add_argument("--baseline-tolerance-px", type=int, default=4)
    parser.add_argument("--background-removal", choices=["request", "none", "chroma", "matte", "rembg", "ben2", "auto"], default="request")
    parser.add_argument("--background-model", help=f"model name; rembg default {DEFAULT_REMBG_MODEL}; ben2 default {DEFAULT_BEN2_MODEL}")
    parser.add_argument("--background-device", help="model-backed background removal device: auto, cpu, cuda, cuda:0, etc.")
    parser.add_argument("--alpha-matting", dest="alpha_matting", action="store_true", default=None)
    parser.add_argument("--no-alpha-matting", dest="alpha_matting", action="store_false")
    parser.add_argument("--post-rembg-chroma-cleanup", dest="post_rembg_chroma_cleanup", action="store_true", default=None)
    parser.add_argument("--no-post-rembg-chroma-cleanup", dest="post_rembg_chroma_cleanup", action="store_false")
    parser.add_argument("--matte-threshold", type=float, default=28.0)
    parser.add_argument("--matte-max-colors", type=int, default=8)
    parser.add_argument("--edge-refine", choices=["off", "conservative"], default="conservative")
    parser.add_argument("--edge-refine-threshold", type=float, default=36.0)
    parser.add_argument("--edge-refine-feather", type=float, default=36.0)
    parser.add_argument("--edge-refine-passes", type=int, default=1)
    args = parser.parse_args()
    if args.fringe_key_threshold < args.key_threshold:
        raise SystemExit("--fringe-key-threshold must be greater than or equal to --key-threshold")

    run_dir = args.run_dir.expanduser().resolve()
    acquire_run_dir_lock(run_dir, "extract_sprite_row_frames")
    request = json.loads((run_dir / "sprite-request.json").read_text(encoding="utf-8"))
    extraction_mode = str(request.get("extraction_mode", "components"))
    if extraction_mode not in {"components", "slots"}:
        raise SystemExit("sprite-request.json extraction_mode must be components or slots")
    states = list(request["states"]) if args.states == "all" else [state.strip() for state in args.states.split(",") if state.strip()]
    cell_width, cell_height, safe_margin_x, safe_margin_y = cell_geometry(request["cell"])
    if (
        extraction_mode == "slots"
        and str(request.get("asset_kind")) in {"texture", "tileset"}
        and safe_margin_x == 0
        and safe_margin_y == 0
    ):
        args.edge_pixel_threshold = max(args.edge_pixel_threshold, 4 * (cell_width + cell_height))
    chroma_key = tuple(int(value) for value in request["chroma_key"]["rgb"])
    frames_root = run_dir / "frames"
    frames_root.mkdir(parents=True, exist_ok=True)
    asset_kind = str(request.get("asset_kind", "sprite"))
    resize_policy = resize_policy_from_sampling_policy(request.get("sampling_policy"))
    args.pixel_art = resize_policy.mode is ArtMode.PIXEL
    args.allow_full_cell = (
        extraction_mode == "slots" and asset_kind in {"texture", "tileset"}
    )
    background_removal = normalize_background_removal(request, args)
    rembg_sessions: dict[str, Any] = {}
    matte_review_entries: list[dict[str, Any]] = []
    pending_rows: list[dict[str, Any]] = []
    rows = []
    all_errors: list[str] = []
    all_warnings: list[str] = []

    for state in states:
        if state not in request["states"]:
            raise SystemExit(f"unknown state in request: {state}")
        raw_path = run_dir / "raw" / f"{state}.png"
        if not raw_path.is_file():
            all_errors.append(f"{state}: missing raw strip {raw_path}")
            continue
        frame_count = int(request["states"][state]["frames"])
        with Image.open(raw_path) as opened:
            raw_source = opened.convert("RGBA")
            try:
                strip, background_method = remove_background(
                    raw_source,
                    chroma_key,
                    background_removal,
                    args,
                    rembg_sessions,
                )
            except RuntimeError as exc:
                all_errors.append(f"{state}: {exc}")
                continue
            matte_review_entries.append(
                {
                    "state": state,
                    "method": background_method,
                    "raw": raw_source.copy(),
                    "processed": strip.copy(),
                }
            )
        if extraction_mode == "slots":
            columns, layout_rows = raw_layout_grid(request["states"][state], frame_count)
            uses_grid_layout = layout_rows > 1 or columns != frame_count
            sprites = (
                extract_grid_slot_sprites(strip, frame_count, columns, layout_rows)
                if uses_grid_layout
                else extract_slot_sprites(strip, frame_count)
            )
            method = "grid-slots" if uses_grid_layout else "slots-explicit"
            segmentation_report = {
                "layout": "grid" if uses_grid_layout else "strip",
                "columns": columns,
                "rows": layout_rows,
            }
        else:
            columns, layout_rows = raw_layout_grid(request["states"][state], frame_count)
            uses_grid_layout = layout_rows > 1 or columns != frame_count
            segmentation_report = {
                "layout": "grid" if uses_grid_layout else "strip",
                "columns": columns,
                "rows": layout_rows,
            }
            if uses_grid_layout:
                sprites = extract_grid_component_sprites(strip, frame_count, columns, layout_rows)
                method = "grid-components"
            else:
                sprites = extract_component_sprites(strip, frame_count)
                method = "components"
                if sprites is None:
                    sprites, projection_report = projection_sprites(strip, frame_count)
                    segmentation_report["projection"] = projection_report
                    if sprites is not None:
                        method = "projection-strip"
                    for warning in projection_report.get("warnings", []):
                        all_warnings.append(f"{state}: {warning}")
        if sprites is None:
            if not args.allow_slot_fallback:
                all_errors.append(f"{state}: could not extract {frame_count} sprite components")
                continue
            sprites = (
                extract_grid_slot_sprites(strip, frame_count, columns, layout_rows)
                if uses_grid_layout
                else extract_slot_sprites(strip, frame_count)
            )
            method = "grid-slots-fallback" if uses_grid_layout else "slots-explicit"
            segmentation_report["slot_fallback"] = True

        pose_geometry = None
        if asset_kind == "sprite":
            pose_geometry = state_pose_geometry(state, request["states"][state]) or side_view_locomotion_geometry(
                request,
                state,
                request["states"][state],
            )
        pending_rows.append(
            {
                "state": state,
                "frames": frame_count,
                "method": method,
                "background_method": background_method,
                "sprites": sprites,
                "pose_geometry": pose_geometry,
                "segmentation": segmentation_report,
            }
        )

    reference_metrics = reference_metrics_for_rows(request, pending_rows, cell_width, cell_height, safe_margin_x, safe_margin_y)
    if reference_metrics is None:
        reference_metrics = existing_reference_metrics(request, run_dir)

    for pending in pending_rows:
        state = pending["state"]
        frame_count = pending["frames"]
        pose_geometry = pending["pose_geometry"]
        try:
            if asset_kind == "sprite":
                frames = fit_pose_frames(
                    pending["sprites"],
                    pose_geometry,
                    reference_metrics,
                    cell_width,
                    cell_height,
                    safe_margin_x,
                    safe_margin_y,
                    resize_policy,
                )
            else:
                frames = [
                    fit_to_cell(
                        sprite,
                        cell_width,
                        cell_height,
                        safe_margin_x,
                        safe_margin_y,
                        resize_policy=resize_policy,
                    )
                    for sprite in pending["sprites"]
                ]
        except ImagePolicyError as exc:
            all_errors.append(f"{state}: {exc}")
            continue

        state_dir = frames_root / state
        state_dir.mkdir(parents=True, exist_ok=True)
        output_paths = []
        for index, frame in enumerate(frames):
            output = state_dir / f"frame-{index}.png"
            atomic_save_image(frame, output)
            output_paths.append(str(output.relative_to(run_dir)))

        errors, warnings, frame_records = inspect_frames(
            frames,
            chroma_key,
            args,
            state=state,
            pose_geometry=pose_geometry,
            reference_metrics=reference_metrics,
            cell_height=cell_height,
            safe_margin_y=safe_margin_y,
        )
        all_errors.extend(f"{state}: {error}" for error in errors)
        all_warnings.extend(f"{state}: {warning}" for warning in warnings)
        row_record = {
            "state": state,
            "frames": frame_count,
            "method": pending["method"],
            "background_method": pending["background_method"],
            "files": output_paths,
            "frame_records": frame_records,
            "ok": not errors,
        }
        if pending.get("segmentation"):
            row_record["segmentation"] = pending["segmentation"]
        if pose_geometry:
            row_record["pose_geometry"] = pose_geometry
        rows.append(row_record)

    matte_review = save_background_matte_review(matte_review_entries, run_dir)
    result = {
        "ok": not all_errors,
        "engine": "component-row",
        "run_dir": str(run_dir),
        "cell": request["cell"],
        "chroma_key": request["chroma_key"],
        "generation_background": request.get("generation_background"),
        "background_removal": background_removal,
        "background_matte_review": matte_review,
        "sprite_registration": {
            "reference_height": int(reference_metrics.get("height", 0)) if reference_metrics else None,
            "reference_width": int(reference_metrics.get("width", 0)) if reference_metrics else None,
            "reference_scale": round(float(reference_metrics["scale"]), 6) if reference_metrics and reference_metrics.get("scale") else None,
            **{
                f"reference_{key}": int(reference_metrics[key])
                for key in STABLE_FEATURE_KEYS
                if reference_metrics and reference_metrics.get(key)
            },
            "baseline_y": cell_height - safe_margin_y,
        } if asset_kind == "sprite" else None,
        "rows": rows,
        "errors": all_errors,
        "warnings": all_warnings,
    }
    atomic_write_text(frames_root / "frames-manifest.json", json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
