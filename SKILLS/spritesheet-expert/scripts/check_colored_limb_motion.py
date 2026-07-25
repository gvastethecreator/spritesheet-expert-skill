#!/usr/bin/env python3
"""Check color-coded mannequin motion without mistaking recoloring for animation.

The checker tracks permanent red/blue arm and orange/green leg identities over
time, measures their trajectories relative to the torso, and separately
measures the color-independent subject silhouette. It is a mechanical guardrail
for review candidates, not a replacement for biomechanical visual review.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Iterable

from PIL import Image, ImageChops, ImageStat


LIMBS = ("red_arm", "blue_arm", "orange_leg", "green_leg")


@dataclass(frozen=True)
class RegionStats:
    count: int
    bbox: tuple[int, int, int, int]
    centroid: tuple[float, float]
    angle_degrees: float

    def to_dict(self) -> dict[str, object]:
        return {
            "count": self.count,
            "bbox": list(self.bbox),
            "centroid": [round(value, 3) for value in self.centroid],
            "angle_degrees": round(self.angle_degrees, 3),
        }


def baseline_row(image: Image.Image) -> int:
    rgb = image.convert("RGB")
    width, height = rgb.size
    candidates: list[tuple[float, int]] = []
    for y in range(int(height * 0.70), int(height * 0.96)):
        row = rgb.crop((0, y, width, y + 1))
        candidates.append((sum(ImageStat.Stat(row).mean), y))
    if not candidates:
        raise ValueError("image is too small for baseline detection")
    return min(candidates)[1]


def classify_limb(hue: int, saturation: int, value: int) -> str | None:
    if saturation < 70 or value < 65:
        return None
    if hue <= 14 or hue >= 244:
        return "red_arm"
    if 15 <= hue <= 43:
        return "orange_leg"
    if 44 <= hue <= 112:
        return "green_leg"
    if 113 <= hue <= 190:
        return "blue_arm"
    return None


def region_stats(points: list[tuple[int, int]]) -> RegionStats | None:
    if not points:
        return None
    count = len(points)
    sum_x = sum(point[0] for point in points)
    sum_y = sum(point[1] for point in points)
    center_x = sum_x / count
    center_y = sum_y / count
    min_x = min(point[0] for point in points)
    min_y = min(point[1] for point in points)
    max_x = max(point[0] for point in points)
    max_y = max(point[1] for point in points)
    covariance_xx = sum((x - center_x) ** 2 for x, _ in points) / count
    covariance_yy = sum((y - center_y) ** 2 for _, y in points) / count
    covariance_xy = sum((x - center_x) * (y - center_y) for x, y in points) / count
    angle = 0.5 * math.degrees(math.atan2(2 * covariance_xy, covariance_xx - covariance_yy))
    return RegionStats(
        count=count,
        bbox=(min_x, min_y, max_x + 1, max_y + 1),
        centroid=(center_x, center_y),
        angle_degrees=angle,
    )


def connected_regions(points: list[tuple[int, int]]) -> list[RegionStats]:
    remaining = set(points)
    regions: list[RegionStats] = []
    while remaining:
        seed = remaining.pop()
        stack = [seed]
        component = [seed]
        while stack:
            x, y = stack.pop()
            for neighbor in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    stack.append(neighbor)
                    component.append(neighbor)
        stats = region_stats(component)
        if stats:
            regions.append(stats)
    return regions


def select_head(points: list[tuple[int, int]], torso: RegionStats | None, height: int) -> RegionStats | None:
    if torso is None:
        return None
    roi = [
        (x, y)
        for x, y in points
        if abs(x - torso.centroid[0]) <= height * 0.18
        and y <= torso.centroid[1] - height * 0.045
    ]
    candidates: list[RegionStats] = []
    for region in connected_regions(roi):
        width = region.bbox[2] - region.bbox[0]
        region_height = region.bbox[3] - region.bbox[1]
        if (
            region.count >= 150
            and height * 0.035 <= width <= height * 0.20
            and height * 0.055 <= region_height <= height * 0.30
        ):
            candidates.append(region)
    return max(candidates, key=lambda region: region.count, default=None)


def analyze_frame(path: Path) -> dict[str, object]:
    image = Image.open(path).convert("RGB")
    hsv = image.convert("HSV")
    width, height = image.size
    baseline = baseline_row(image)
    limb_points: dict[str, list[tuple[int, int]]] = {limb: [] for limb in LIMBS}
    torso_points: list[tuple[int, int]] = []
    head_points: list[tuple[int, int]] = []

    rgb_pixels = image.load()
    hsv_pixels = hsv.load()
    for y in range(0, max(0, baseline - 3)):
        for x in range(width):
            hue, saturation, value = hsv_pixels[x, y]
            limb = classify_limb(hue, saturation, value)
            if limb:
                limb_points[limb].append((x, y))
            red, green, blue = rgb_pixels[x, y]
            channel_spread = max(red, green, blue) - min(red, green, blue)
            if saturation < 55 and 45 <= value <= 140 and channel_spread < 35:
                torso_points.append((x, y))
            if saturation < 42 and 170 <= value <= 238 and channel_spread < 28 and y < int(height * 0.42):
                head_points.append((x, y))

    torso = region_stats(torso_points)
    head = select_head(head_points, torso, height)
    limbs = {limb: region_stats(points) for limb, points in limb_points.items()}

    corner = image.getpixel((0, 0))
    background = Image.new("RGB", image.size, corner)
    difference = ImageChops.difference(image, background).convert("L")
    silhouette = difference.point(lambda value: 255 if value >= 28 else 0)
    pixels = silhouette.load()
    for y in range(max(0, baseline - 3), min(height, baseline + 4)):
        for x in range(width):
            pixels[x, y] = 0

    return {
        "path": str(path.resolve()),
        "width": width,
        "height": height,
        "baseline_y": baseline,
        "torso": torso,
        "head": head,
        "limbs": limbs,
        "silhouette": silhouette,
    }


def shifted_mask(mask: Image.Image, dx: int, dy: int) -> Image.Image:
    result = Image.new("L", mask.size, 0)
    result.paste(mask, (dx, dy))
    return result


def mask_delta(first: Image.Image, second: Image.Image) -> float:
    union = ImageChops.lighter(first, second)
    xor = ImageChops.difference(first, second)
    union_count = sum(union.histogram()[1:])
    xor_count = sum(xor.histogram()[1:])
    return xor_count / union_count if union_count else 0.0


def normalized_position(frame: dict[str, object], region: RegionStats) -> tuple[float, float]:
    torso = frame["torso"]
    assert isinstance(torso, RegionStats)
    height = int(frame["height"])
    return (
        (region.centroid[0] - torso.centroid[0]) / height,
        (region.centroid[1] - torso.centroid[1]) / height,
    )


def distances(points: list[tuple[float, float]]) -> list[float]:
    closed = points[1:] + points[:1]
    return [math.dist(first, second) for first, second in zip(points, closed, strict=True)]


def angle_span(values: Iterable[float]) -> float:
    normalized = sorted((value + 180.0) % 180.0 for value in values)
    if len(normalized) < 2:
        return 0.0
    gaps = [second - first for first, second in zip(normalized, normalized[1:], strict=False)]
    gaps.append(180.0 - normalized[-1] + normalized[0])
    return 180.0 - max(gaps)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frame", action="append", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--profile", choices=("trajectory", "sideview-walk-6"), default="trajectory")
    parser.add_argument("--min-limb-x-range", type=float, default=0.055)
    parser.add_argument("--min-active-transitions", type=int, default=4)
    parser.add_argument("--min-transition-distance", type=float, default=0.012)
    parser.add_argument("--max-step-ratio", type=float, default=4.5)
    parser.add_argument("--min-silhouette-delta", type=float, default=0.035)
    args = parser.parse_args()

    paths = [path.expanduser().resolve() for path in args.frame]
    if len(paths) < 2:
        raise SystemExit("at least two --frame inputs are required")
    if args.profile == "sideview-walk-6" and len(paths) != 6:
        raise SystemExit("sideview-walk-6 requires exactly six frames")

    frames = [analyze_frame(path) for path in paths]
    dimensions = {(int(frame["width"]), int(frame["height"])) for frame in frames}
    errors: list[str] = []
    warnings: list[str] = []
    if len(dimensions) != 1:
        errors.append(f"all frames must share dimensions, got {sorted(dimensions)}")

    for index, frame in enumerate(frames, start=1):
        if frame["torso"] is None:
            errors.append(f"frame {index}: neutral torso/root proxy is missing")
        if frame["head"] is None:
            errors.append(f"frame {index}: neutral head proxy is missing")
        limbs = frame["limbs"]
        assert isinstance(limbs, dict)
        for limb in LIMBS:
            if limbs[limb] is None:
                errors.append(f"frame {index}: permanent {limb} color region is missing")

    trajectories: dict[str, dict[str, object]] = {}
    if not errors:
        for limb in LIMBS:
            regions = [frame["limbs"][limb] for frame in frames]  # type: ignore[index]
            assert all(isinstance(region, RegionStats) for region in regions)
            typed_regions = [region for region in regions if isinstance(region, RegionStats)]
            points = [normalized_position(frame, region) for frame, region in zip(frames, typed_regions, strict=True)]
            steps = distances(points)
            active = sum(step >= args.min_transition_distance for step in steps)
            positive = [step for step in steps if step > 1e-6]
            step_ratio = max(positive) / median(positive) if positive else float("inf")
            x_range = max(point[0] for point in points) - min(point[0] for point in points)
            orientation_span = angle_span(region.angle_degrees for region in typed_regions)
            trajectories[limb] = {
                "relative_centroids": [[round(x, 5), round(y, 5)] for x, y in points],
                "closed_loop_steps": [round(step, 5) for step in steps],
                "total_travel": round(sum(steps), 5),
                "x_range": round(x_range, 5),
                "active_transitions": active,
                "max_to_median_step_ratio": round(step_ratio, 5),
                "orientation_span_degrees": round(orientation_span, 3),
            }
            if x_range < args.min_limb_x_range:
                errors.append(
                    f"{limb}: horizontal range {x_range:.3f} is below {args.min_limb_x_range:.3f}; limb reads frozen"
                )
            if active < args.min_active_transitions:
                errors.append(
                    f"{limb}: only {active} active transitions; expected at least {args.min_active_transitions}"
                )
            if step_ratio > args.max_step_ratio:
                errors.append(
                    f"{limb}: max/median step ratio {step_ratio:.2f} suggests a teleport or recolor jump"
                )

    silhouette_deltas: list[float] = []
    if not errors or all(frame["torso"] is not None for frame in frames):
        reference_torso = frames[0]["torso"]
        if isinstance(reference_torso, RegionStats):
            aligned: list[Image.Image] = []
            for frame in frames:
                torso = frame["torso"]
                if not isinstance(torso, RegionStats):
                    continue
                dx = round(reference_torso.centroid[0] - torso.centroid[0])
                dy = round(reference_torso.centroid[1] - torso.centroid[1])
                aligned.append(shifted_mask(frame["silhouette"], dx, dy))  # type: ignore[arg-type]
            if len(aligned) == len(frames):
                for first, second in zip(aligned, aligned[1:] + aligned[:1], strict=True):
                    silhouette_deltas.append(mask_delta(first, second))
                active_silhouettes = sum(delta >= args.min_silhouette_delta for delta in silhouette_deltas)
                if active_silhouettes < max(2, len(frames) - 2):
                    errors.append(
                        f"only {active_silhouettes}/{len(frames)} silhouette transitions exceed "
                        f"{args.min_silhouette_delta:.3f}; sequence is too visually static"
                    )

    phase_checks: list[dict[str, object]] = []
    if args.profile == "sideview-walk-6" and not any("missing" in error for error in errors):
        height = int(frames[0]["height"])
        contact_tolerance = max(4, round(height * 0.012))
        swing_clearance = max(12, round(height * 0.035))
        expected_contacts = {
            1: {"orange_leg", "green_leg"},
            2: {"orange_leg", "green_leg"},
            3: {"orange_leg"},
            4: {"orange_leg", "green_leg"},
            5: {"orange_leg", "green_leg"},
            6: {"green_leg"},
        }
        for index, frame in enumerate(frames, start=1):
            contacts: set[str] = set()
            clearances: dict[str, int] = {}
            limbs = frame["limbs"]
            assert isinstance(limbs, dict)
            for leg in ("orange_leg", "green_leg"):
                region = limbs[leg]
                assert isinstance(region, RegionStats)
                clearance = int(frame["baseline_y"]) - (region.bbox[3] - 1)
                clearances[leg] = clearance
                if clearance <= contact_tolerance:
                    contacts.add(leg)
            required = expected_contacts[index]
            missing_contacts = required - contacts
            unexpected_contacts = contacts - required
            swing_leg = ({"orange_leg", "green_leg"} - required).pop() if len(required) == 1 else None
            phase_errors: list[str] = []
            if missing_contacts:
                phase_errors.append(f"missing contacts: {sorted(missing_contacts)}")
            if swing_leg and swing_leg in unexpected_contacts:
                phase_errors.append(f"{swing_leg} should be airborne")
            if swing_leg and clearances[swing_leg] < swing_clearance:
                phase_errors.append(
                    f"{swing_leg} clearance {clearances[swing_leg]}px is below {swing_clearance}px"
                )
            for message in phase_errors:
                errors.append(f"frame {index}: {message}")
            phase_checks.append(
                {
                    "frame": index,
                    "expected_contacts": sorted(required),
                    "observed_contacts": sorted(contacts),
                    "clearance_px": clearances,
                    "errors": phase_errors,
                }
            )

        order_requirements = (
            (1, "orange_leg", "green_leg", "orange leg must lead green leg"),
            (4, "green_leg", "orange_leg", "green leg must lead orange leg"),
            (1, "blue_arm", "red_arm", "blue arm must lead red arm"),
            (4, "red_arm", "blue_arm", "red arm must lead blue arm"),
        )
        for frame_number, leading, trailing, message in order_requirements:
            limbs = frames[frame_number - 1]["limbs"]
            assert isinstance(limbs, dict)
            lead_region = limbs[leading]
            trail_region = limbs[trailing]
            assert isinstance(lead_region, RegionStats) and isinstance(trail_region, RegionStats)
            if lead_region.centroid[0] <= trail_region.centroid[0]:
                errors.append(f"frame {frame_number}: {message}")

    torso_centers = [
        frame["torso"].centroid if isinstance(frame["torso"], RegionStats) else (0.0, 0.0)
        for frame in frames
    ]
    height = int(frames[0]["height"])
    torso_x_range = (max(point[0] for point in torso_centers) - min(point[0] for point in torso_centers)) / height
    if torso_x_range > 0.04:
        errors.append(f"torso/root x drift {torso_x_range:.3f} exceeds 0.040 of frame height")

    head_regions = [frame["head"] for frame in frames if isinstance(frame["head"], RegionStats)]
    head_width_drift = 0.0
    head_height_drift = 0.0
    if len(head_regions) == len(frames):
        head_widths = [region.bbox[2] - region.bbox[0] for region in head_regions]
        head_heights = [region.bbox[3] - region.bbox[1] for region in head_regions]
        head_width_drift = max(head_widths) / min(head_widths) - 1.0
        head_height_drift = max(head_heights) / min(head_heights) - 1.0
        if head_width_drift > 0.15:
            errors.append(f"head width drift {head_width_drift:.3f} exceeds 0.150")
        if head_height_drift > 0.15:
            errors.append(f"head height drift {head_height_drift:.3f} exceeds 0.150")

    serializable_frames: list[dict[str, object]] = []
    for index, frame in enumerate(frames, start=1):
        limbs = frame["limbs"]
        assert isinstance(limbs, dict)
        serializable_frames.append(
            {
                "frame": index,
                "path": frame["path"],
                "size": [frame["width"], frame["height"]],
                "baseline_y": frame["baseline_y"],
                "torso": frame["torso"].to_dict() if isinstance(frame["torso"], RegionStats) else None,
                "head": frame["head"].to_dict() if isinstance(frame["head"], RegionStats) else None,
                "limbs": {
                    limb: region.to_dict() if isinstance(region, RegionStats) else None
                    for limb, region in limbs.items()
                },
            }
        )

    report = {
        "ok": not errors,
        "kind": "colored-limb-motion-report",
        "profile": args.profile,
        "frame_count": len(frames),
        "thresholds": {
            "min_limb_x_range": args.min_limb_x_range,
            "min_active_transitions": args.min_active_transitions,
            "min_transition_distance": args.min_transition_distance,
            "max_step_ratio": args.max_step_ratio,
            "min_silhouette_delta": args.min_silhouette_delta,
        },
        "torso_x_range": round(torso_x_range, 5),
        "head_width_drift": round(head_width_drift, 5),
        "head_height_drift": round(head_height_drift, 5),
        "silhouette_deltas": [round(delta, 5) for delta in silhouette_deltas],
        "trajectories": trajectories,
        "phase_checks": phase_checks,
        "frames": serializable_frames,
        "errors": errors,
        "warnings": warnings,
        "visual_review_required": True,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
