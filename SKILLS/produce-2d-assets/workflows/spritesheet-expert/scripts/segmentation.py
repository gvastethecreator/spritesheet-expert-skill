#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Shared sprite segmentation helpers.

These helpers cover the gap between exact-grid slicing and connected-component
auto-detect. Projection cuts are useful when AI-generated poses touch, have
uneven gutters, or contain disconnected limbs that should still belong to one
frame.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PIL import Image


ALPHA_THRESHOLD = 16


@dataclass(frozen=True)
class Span:
    start: int
    end: int

    @property
    def width(self) -> int:
        return self.end - self.start


def alpha_projection(image: Image.Image, axis: str = "x", threshold: int = ALPHA_THRESHOLD) -> list[float]:
    alpha = image.convert("RGBA").getchannel("A")
    width, height = alpha.size
    pixels = alpha.load()
    if axis == "y":
        return [
            float(sum(pixels[x, y] for x in range(width) if pixels[x, y] > threshold))
            for y in range(height)
        ]
    return [
        float(sum(pixels[x, y] for y in range(height) if pixels[x, y] > threshold))
        for x in range(width)
    ]


def smooth_profile(profile: list[float], window: int) -> list[float]:
    if window <= 1 or not profile:
        return list(profile)
    half = window // 2
    out: list[float] = []
    for index in range(len(profile)):
        lo = max(0, index - half)
        hi = min(len(profile), index + half + 1)
        out.append(sum(profile[lo:hi]) / max(1, hi - lo))
    return out


def content_runs(profile: list[float], eps: float, peak_min: float, min_width: int) -> list[Span]:
    runs: list[Span] = []
    index = 0
    while index < len(profile):
        if profile[index] <= eps:
            index += 1
            continue
        start = index
        peak = 0.0
        while index < len(profile) and profile[index] > eps:
            peak = max(peak, profile[index])
            index += 1
        if index - start >= min_width and peak >= peak_min:
            runs.append(Span(start, index))
    return runs


def run_mass(profile: list[float], span: Span) -> float:
    return sum(profile[span.start : min(span.end, len(profile))])


def drop_minor_runs(profile: list[float], runs: list[Span], fraction: float) -> list[Span]:
    if len(runs) <= 1:
        return runs
    max_mass = max(run_mass(profile, run) for run in runs)
    return [run for run in runs if run_mass(profile, run) >= max_mass * fraction]


def median_run_width(runs: list[Span]) -> float:
    if not runs:
        return 0.0
    widths = sorted(run.width for run in runs)
    return float(widths[len(widths) // 2])


def pose_peaks(profile: list[float], start: int, end: int) -> list[int]:
    if end - start < 3:
        return [(start + end) // 2]
    run_max = max(profile[start:end] or [0.0])
    if run_max <= 0:
        return [(start + end) // 2]
    candidates = [
        x
        for x in range(start + 1, end - 1)
        if profile[x] >= profile[x - 1] and profile[x] > profile[x + 1] and profile[x] >= 0.45 * run_max
    ]
    if not candidates:
        return [(start + end) // 2]
    keep: list[int] = []
    for candidate in candidates:
        prominent = True
        for other in candidates:
            if other == candidate or profile[other] < profile[candidate]:
                continue
            lo, hi = sorted((candidate, other))
            valley = min(profile[lo : hi + 1] or [profile[candidate]])
            if valley > 0.62 * profile[candidate]:
                prominent = False
                break
        if prominent:
            keep.append(candidate)
    return keep or [(start + end) // 2]


def dp_n_cut(profile: list[float], start: int, end: int, count: int) -> list[int]:
    if count <= 1 or end - start < count:
        return []
    width = end - start
    ideal = width / count
    min_width = max(2, int(ideal * 0.45))
    cut_count = count - 1
    inf = 1e18
    dp = [[(inf, -1) for _ in range(end + 1)] for _ in range(cut_count + 1)]
    dp[0][start] = (0.0, -1)
    for cut_index in range(1, cut_count + 1):
        low_prev = start + (cut_index - 1) * min_width
        max_x = end - (cut_count - cut_index + 1) * min_width
        for x in range(start + cut_index * min_width, max_x + 1):
            best = (inf, -1)
            for prev in range(low_prev, x - min_width + 1):
                prev_cost = dp[cut_index - 1][prev][0]
                if prev_cost >= inf / 2:
                    continue
                delta = (x - prev) - ideal
                cost = prev_cost + profile[min(x, len(profile) - 1)] + 0.0015 * delta * delta
                if cost < best[0]:
                    best = (cost, prev)
            dp[cut_index][x] = best
    best_end = -1
    best_cost = inf
    for x in range(start + cut_count * min_width, end - min_width + 1):
        delta = (end - x) - ideal
        cost = dp[cut_count][x][0] + 0.0015 * delta * delta
        if cost < best_cost:
            best_cost = cost
            best_end = x
    if best_end < 0:
        return []
    cuts = [0] * cut_count
    x = best_end
    for cut_index in range(cut_count, 0, -1):
        cuts[cut_index - 1] = x
        x = dp[cut_index][x][1]
        if x < 0:
            return []
    return cuts


def split_range(profile: list[float], start: int, end: int, count: int) -> list[Span]:
    cuts = dp_n_cut(profile, start, end, count)
    if not cuts:
        cuts = [round(start + (end - start) * i / count) for i in range(1, count)]
    points = [start, *cuts, end]
    return [Span(points[i], points[i + 1]) for i in range(len(points) - 1) if points[i + 1] > points[i]]


def projection_spans(image: Image.Image, expected: int, axis: str = "x") -> tuple[list[Span], dict[str, Any]]:
    if expected < 1:
        return [], {"ok": False, "natural": 0, "warnings": ["expected frame count must be positive"]}
    size = image.height if axis == "y" else image.width
    if size <= 0:
        return [], {"ok": False, "natural": 0, "warnings": ["empty image"]}
    raw = alpha_projection(image, axis)
    window = max(3, size // 220)
    profile = smooth_profile(raw, window)
    peak = max(profile or [0.0])
    if peak <= 0:
        return [], {"ok": False, "natural": 0, "warnings": ["no alpha content found"]}
    runs = content_runs(profile, 0.045 * peak, 0.18 * peak, max(4, size // 100))
    runs = drop_minor_runs(profile, runs, 0.20)
    if not runs:
        return [], {"ok": False, "natural": 0, "warnings": ["no usable alpha runs found"]}

    spans: list[Span] = []
    median_width = median_run_width(runs)
    total_width = sum(run.width for run in runs)
    for run in runs:
        peak_count = len(pose_peaks(profile, run.start, run.end))
        if len(runs) > 1 and median_width > 0:
            peak_count = min(peak_count, max(1, int(run.width / median_width + 0.5)))
            if peak_count == 1 and run.width > median_width * 1.45:
                peak_count = 2
        spans.extend(split_range(profile, run.start, run.end, peak_count) if peak_count > 1 else [run])

    natural = len(spans)
    repair_used = False
    if natural != expected and total_width / expected >= 16 and size / expected >= 16:
        left = min(run.start for run in runs)
        right = max(run.end for run in runs)
        spans = split_range(profile, left, right, expected)
        repair_used = True
    warnings: list[str] = []
    if natural != expected:
        warnings.append(f"projection detected {natural} natural poses but expected {expected}; DP repair used={repair_used}")
    return spans, {
        "ok": len(spans) == expected,
        "axis": axis,
        "natural": natural,
        "expected": expected,
        "repair_used": repair_used,
        "spans": [{"start": span.start, "end": span.end, "width": span.width} for span in spans],
        "warnings": warnings,
    }


def crop_alpha_content(image: Image.Image, padding: int = 4, threshold: int = ALPHA_THRESHOLD) -> Image.Image:
    rgba = image.convert("RGBA")
    alpha = rgba.getchannel("A").point(lambda value: 255 if value > threshold else 0)
    bbox = alpha.getbbox()
    if not bbox:
        return Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    left = max(0, bbox[0] - padding)
    top = max(0, bbox[1] - padding)
    right = min(rgba.width, bbox[2] + padding)
    bottom = min(rgba.height, bbox[3] + padding)
    return rgba.crop((left, top, right, bottom))


def projection_sprites(strip: Image.Image, expected: int, padding: int = 4) -> tuple[list[Image.Image] | None, dict[str, Any]]:
    spans, report = projection_spans(strip, expected, "x")
    if len(spans) != expected:
        return None, report
    sprites = [
        crop_alpha_content(strip.crop((span.start, 0, span.end, strip.height)), padding)
        for span in spans
    ]
    return sprites, report


def alpha_mass_extent_80(image: Image.Image) -> tuple[int, int]:
    rgba = image.convert("RGBA")
    alpha = rgba.getchannel("A")
    bbox = alpha.getbbox()
    if not bbox:
        return 0, 0
    cropped = alpha.crop(bbox)
    width, height = cropped.size
    pixels = cropped.load()
    mass_x = [0.0] * width
    mass_y = [0.0] * height
    for y in range(height):
        for x in range(width):
            value = pixels[x, y]
            mass_x[x] += value
            mass_y[y] += value
    return _mass_extent(mass_x, 0.80), _mass_extent(mass_y, 0.80)


def _mass_extent(mass: list[float], fraction: float) -> int:
    total = sum(mass)
    if total <= 0:
        return 0
    target = total * fraction
    best = len(mass)
    left = 0
    current = 0.0
    for right, value in enumerate(mass):
        current += value
        while left <= right and current >= target:
            best = min(best, right - left + 1)
            current -= mass[left]
            left += 1
    return max(1, best)
