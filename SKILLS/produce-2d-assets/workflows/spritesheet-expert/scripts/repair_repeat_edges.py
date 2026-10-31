#!/usr/bin/env python3
"""Harmonize opposite edges of provider-generated self-repeat assets.

Without ``--phase-source-dir`` this is an edge-only repair whose center stays
byte-identical. With a phase source it normalizes an independently generated
provider retry into the runtime cell, then applies only a narrow seam blend.
The report distinguishes both modes and binds every input by hash.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import json
import math
from pathlib import Path
import re
import sys
from typing import Any

from PIL import Image

from runio import atomic_save_image, atomic_write_bytes, atomic_write_text
from check_asset_slots import row_labels
from check_animation_contracts import frame_rows_by_state
from spritecore.contracts import load_provenance, load_sprite_request
from spritecore.locks import acquire_run_lock
from spritecore.paths import resolve_run_path


ALLOWED_PROVIDER_TYPES = {
    "imagegen",
    "grok-imagine-image",
    "grok-imagine-video",
    "mixed",
}
PROVIDER_ART_ENGINES = {
    "imagegen": "imagegen",
    "grok-imagine-image": "grok-imagine",
}
PROVENANCE_NOTE = "provider slot retries normalized by periodic phase crop"


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def repair_widths(size: tuple[int, int], blend_width: int, edge_strip: int) -> tuple[int, int]:
    if min(size) < 8:
        raise ValueError("repeat-edge repair requires frames of at least 8x8")
    if any(type(value) is not int or value <= 0 for value in (blend_width, edge_strip)):
        raise ValueError("blend width and edge strip must be positive integers")
    maximum = min(size) // 3
    if edge_strip > maximum:
        raise ValueError("edge strip cannot exceed one third of either frame dimension")
    return max(edge_strip, min(blend_width, maximum)), edge_strip


def harmonize_repeat_edges(
    image: Image.Image,
    *,
    blend_width: int,
    edge_strip: int = 2,
) -> Image.Image:
    result = image.convert("RGBA")
    width, height = result.size
    blend_width, edge_strip = repair_widths(result.size, blend_width, edge_strip)
    strengths = [
        255
        if distance < edge_strip
        else round(
            255
            * (
                1.0
                - ((distance - edge_strip + 1) / (blend_width - edge_strip + 1))
            )
        )
        for distance in range(blend_width)
    ]

    edge_stack = Image.new("RGBA", (edge_strip * 2, height))
    edge_stack.paste(result.crop((0, 0, edge_strip, height)), (0, 0))
    edge_stack.paste(
        result.crop((width - edge_strip, 0, width, height)), (edge_strip, 0)
    )
    horizontal_boundary = edge_stack.resize((1, height), Image.Resampling.BOX).resize(
        (blend_width, height), Image.Resampling.NEAREST
    )
    left_mask = Image.new("L", (blend_width, 1))
    left_mask.putdata(strengths)
    left_mask = left_mask.resize((blend_width, height), Image.Resampling.NEAREST)
    right_mask = left_mask.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    result.paste(
        Image.composite(
            horizontal_boundary,
            result.crop((0, 0, blend_width, height)),
            left_mask,
        ),
        (0, 0),
    )
    result.paste(
        Image.composite(
            horizontal_boundary,
            result.crop((width - blend_width, 0, width, height)),
            right_mask,
        ),
        (width - blend_width, 0),
    )

    edge_stack = Image.new("RGBA", (width, edge_strip * 2))
    edge_stack.paste(result.crop((0, 0, width, edge_strip)), (0, 0))
    edge_stack.paste(
        result.crop((0, height - edge_strip, width, height)), (0, edge_strip)
    )
    vertical_boundary = edge_stack.resize((width, 1), Image.Resampling.BOX).resize(
        (width, blend_width), Image.Resampling.NEAREST
    )
    top_mask = Image.new("L", (1, blend_width))
    top_mask.putdata(strengths)
    top_mask = top_mask.resize((width, blend_width), Image.Resampling.NEAREST)
    bottom_mask = top_mask.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    result.paste(
        Image.composite(
            vertical_boundary,
            result.crop((0, 0, width, blend_width)),
            top_mask,
        ),
        (0, 0),
    )
    result.paste(
        Image.composite(
            vertical_boundary,
            result.crop((0, height - blend_width, width, height)),
            bottom_mask,
        ),
        (0, height - blend_width),
    )
    return result


def _boundary_feature(
    image: Image.Image,
    *,
    axis: str,
    position: int,
    band: int,
    sample_length: int,
) -> bytes:
    width, height = image.size
    if axis == "x":
        x0, x1 = position - band, position + band
        strip = image.crop((x0, 0, x1, height)).convert("RGB")
        return strip.resize((band * 2, sample_length), Image.Resampling.BOX).tobytes()
    y0, y1 = position - band, position + band
    strip = image.crop((0, y0, width, y1)).convert("RGB")
    return strip.resize((sample_length, band * 2), Image.Resampling.BOX).tobytes()


def _feature_error(left: bytes, right: bytes) -> float:
    if len(left) != len(right) or not left:
        return 1.0
    return sum(abs(a - b) for a, b in zip(left, right)) / (len(left) * 255)


def _best_repeat_bounds(
    image: Image.Image,
    *,
    axis: str,
    max_trim_ratio: float,
    band: int = 3,
    sample_length: int = 96,
    prefer_dark: bool = False,
) -> dict[str, float | int]:
    length = image.width if axis == "x" else image.height
    max_trim = min(math.floor(length * max_trim_ratio), length // 3)
    if max_trim == 0:
        start = image.crop((0, 0, 1, image.height) if axis == "x" else (0, 0, image.width, 1)).convert("RGB").tobytes()
        end = image.crop((image.width - 1, 0, image.width, image.height) if axis == "x" else (0, image.height - 1, image.width, image.height)).convert("RGB").tobytes()
        error = _feature_error(start, end)
        mean = (sum(start) + sum(end)) / (2 * len(start) * 255)
        return {"start": 0, "end": length, "span": length, "boundary_error": round(error, 6),
                "boundary_mean": round(mean, 6), "trim_ratio": 0.0,
                "score": round(error + (mean * 0.04 if prefer_dark else 0.0), 6)}
    band = min(band, max_trim)
    step = max(1, length // 640)
    starts = list(range(band, max_trim + 1, step))
    ends = list(range(length - max_trim, length - band + 1, step))
    start_features = {
        value: _boundary_feature(
            image,
            axis=axis,
            position=value,
            band=band,
            sample_length=sample_length,
        )
        for value in starts
    }
    end_features = {
        value: _boundary_feature(
            image,
            axis=axis,
            position=value,
            band=band,
            sample_length=sample_length,
        )
        for value in ends
    }
    best: tuple[float, int, int, float, float] | None = None
    minimum_span = round(length * (1.0 - 2 * max_trim_ratio))
    for start in starts:
        for end in ends:
            if end - start < minimum_span:
                continue
            error = _feature_error(start_features[start], end_features[end])
            trim_ratio = (start + length - end) / length
            boundary_mean = (
                sum(start_features[start]) + sum(end_features[end])
            ) / (2 * len(start_features[start]) * 255)
            dark_penalty = boundary_mean * 0.04 if prefer_dark else 0.0
            score = error + trim_ratio * 0.035 + dark_penalty
            candidate = (score, start, end, error, boundary_mean)
            if best is None or candidate < best:
                best = candidate
    if best is None:
        raise ValueError(f"could not find repeat bounds on axis {axis}")
    score, start, end, error, boundary_mean = best
    return {
        "start": start,
        "end": end,
        "span": end - start,
        "boundary_error": round(error, 6),
        "boundary_mean": round(boundary_mean, 6),
        "trim_ratio": round((start + length - end) / length, 6),
        "score": round(score, 6),
    }


def periodic_phase_crop(
    image: Image.Image,
    *,
    output_size: tuple[int, int],
    max_trim_ratio: float = 0.16,
    prefer_dark_boundaries: bool = False,
) -> tuple[Image.Image, dict[str, Any]]:
    if not 0.0 <= max_trim_ratio <= 0.3:
        raise ValueError("phase-crop max trim ratio must be between 0 and 0.3")
    rgba = image.convert("RGBA")
    x_bounds = _best_repeat_bounds(
        rgba,
        axis="x",
        max_trim_ratio=max_trim_ratio,
        prefer_dark=prefer_dark_boundaries,
    )
    y_bounds = _best_repeat_bounds(
        rgba,
        axis="y",
        max_trim_ratio=max_trim_ratio,
        prefer_dark=prefer_dark_boundaries,
    )
    crop = rgba.crop(
        (
            int(x_bounds["start"]),
            int(y_bounds["start"]),
            int(x_bounds["end"]),
            int(y_bounds["end"]),
        )
    )
    normalized = crop.resize(output_size, Image.Resampling.LANCZOS)
    return normalized, {
        "source_size": [rgba.width, rgba.height],
        "output_size": list(output_size),
        "boundary_preference": "dark" if prefer_dark_boundaries else "neutral",
        "x": x_bounds,
        "y": y_bounds,
    }


def load_object(path: Path, content: bytes | None = None) -> dict[str, Any]:
    value = json.loads((path.read_bytes() if content is None else content).decode("utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _portable_label(label: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", label.lower()).strip("-") or "asset"


def merge_provider_provenance(
    provenance: dict[str, Any],
    request: dict[str, Any],
    additions: list[dict[str, Any]],
    *,
    provider: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Merge concrete provider sources without emitting invalid mixed entries."""

    if provider not in PROVIDER_ART_ENGINES:
        raise ValueError(f"unsupported provider source type: {provider}")
    load_provenance(provenance)
    load_sprite_request(request)
    merged = deepcopy(provenance)
    updated_request = deepcopy(request)
    prior_type = str(merged.get("source_type"))
    prior_engine = str(merged.get("art_engine"))
    if prior_type not in ALLOWED_PROVIDER_TYPES:
        raise ValueError("repeat-edge repair requires provider-generated provenance")
    accepted = merged.get("accepted_sources")
    if not isinstance(accepted, list):
        raise ValueError("source provenance accepted_sources must be a list")

    # A concrete root can safely supply missing per-item metadata. A mixed root
    # cannot: inventing ``mixed`` per item violates the v2 source schema.
    if prior_type != "mixed":
        for item in accepted:
            if isinstance(item, dict):
                item.setdefault("source_type", prior_type)
                item.setdefault("art_engine", prior_engine)

    known = {
        str(item.get("path")): item for item in accepted if isinstance(item, dict)
    }
    for addition in additions:
        if addition.get("source_type") != provider or addition.get("art_engine") != PROVIDER_ART_ENGINES[provider]:
            raise ValueError("provider source metadata does not match the selected provider")
        path = str(addition.get("path"))
        existing = known.get(path)
        if existing is not None:
            for field in ("sha256", "size_bytes", "states", "source_type", "art_engine"):
                if existing.get(field) != addition.get(field):
                    raise ValueError(
                        f"accepted provider source {path!r} changed {field}"
                    )
            continue
        accepted.append(deepcopy(addition))
        known[path] = accepted[-1]

    provider_engine = PROVIDER_ART_ENGINES[provider]
    mixed = (
        prior_type == "mixed"
        or prior_engine == "mixed"
        or prior_type != provider
        or prior_engine != provider_engine
    )
    final_type = "mixed" if mixed else provider
    final_engine = "mixed" if mixed else provider_engine
    merged["source_type"] = final_type
    merged["art_engine"] = final_engine
    merged["fixture"] = False
    merged["accepted_sources"] = accepted
    merged["state_coverage"] = sorted(
        {
            str(state)
            for item in accepted
            if isinstance(item, dict)
            for state in item.get("states", [])
        }
    )
    note_parts = list(
        dict.fromkeys(
            part.strip()
            for part in str(merged.get("notes", "")).split(";")
            if part.strip()
        )
    )
    if PROVENANCE_NOTE not in note_parts:
        note_parts.append(PROVENANCE_NOTE)
    merged["notes"] = "; ".join(note_parts)
    if "source_type" in updated_request:
        updated_request["source_type"] = final_type

    # Validate the exact documents before any caller persists them.
    load_provenance(merged)
    load_sprite_request(updated_request)
    return merged, updated_request


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--blend-width", type=int, default=20)
    parser.add_argument("--edge-strip", type=int, default=2)
    parser.add_argument("--all-self", action="store_true")
    parser.add_argument(
        "--labels",
        help="explicit comma-separated self-repeat labels to repair",
    )
    parser.add_argument(
        "--phase-source-dir",
        type=Path,
        help="directory of provider-generated <label>.png sources for phase-crop replacement",
    )
    parser.add_argument(
        "--provider",
        choices=("imagegen", "grok-imagine-image"),
        help="provider provenance for --phase-source-dir",
    )
    parser.add_argument("--phase-max-trim-ratio", type=float, default=0.16)
    parser.add_argument("--phase-blend-width", type=int, default=2)
    parser.add_argument(
        "--phase-boundary-preference",
        choices=("auto", "neutral", "dark"),
        default="auto",
        help="prefer dark grout boundaries for regular grid materials; auto uses label semantics",
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if any(value <= 0 for value in (args.blend_width, args.edge_strip, args.phase_blend_width)):
        parser.error("blend widths and edge strip must be positive integers")
    if not math.isfinite(args.phase_max_trim_ratio) or not 0 <= args.phase_max_trim_ratio <= 0.3:
        parser.error("--phase-max-trim-ratio must be finite and between 0 and 0.3")
    run_dir = args.run_dir.expanduser().resolve()
    request_path = resolve_run_path(run_dir, "sprite-request.json")
    provenance_path = resolve_run_path(run_dir, "source-provenance.json")
    manifest_path = resolve_run_path(run_dir, "frames/frames-manifest.json")
    snapshots = {path: path.read_bytes() for path in (request_path, provenance_path, manifest_path)}
    request = load_sprite_request(load_object(request_path, snapshots[request_path])).to_dict()
    manifest = load_object(manifest_path, snapshots[manifest_path])
    provenance = load_provenance(load_object(provenance_path, snapshots[provenance_path])).to_dict()
    if provenance.get("source_type") not in ALLOWED_PROVIDER_TYPES:
        raise SystemExit("repeat-edge repair requires provider-generated source provenance")
    catalog = request.get("asset_catalog", {}).get("items", {})
    states = request.get("states", {})
    rows = list(frame_rows_by_state(manifest).values())
    protected = set(snapshots) | {resolve_run_path(run_dir, source["path"]) for source in provenance["accepted_sources"]}
    report_path = resolve_run_path(run_dir, "qa/repeat-edge-repair-report.json")
    if report_path in protected or (report_path.exists() and not report_path.is_file()):
        raise ValueError("repeat-edge report output cannot overwrite a source or directory")
    if report_path.is_file():
        snapshots[report_path] = report_path.read_bytes()
        if load_object(report_path, snapshots[report_path]).get("kind") != "repeat-edge-repair":
            raise ValueError("repeat-edge report output cannot overwrite an unrelated file")
    explicit_labels = {
        item.strip() for item in str(args.labels or "").split(",") if item.strip()
    }
    if args.labels is not None and not explicit_labels:
        parser.error("--labels must contain at least one self-repeat label")
    if args.phase_source_dir and (not explicit_labels or not args.provider):
        raise SystemExit("--phase-source-dir requires --labels and --provider")
    if args.provider and not args.phase_source_dir:
        raise SystemExit("--provider requires --phase-source-dir")
    failing_labels: set[str] | None = explicit_labels or None
    if failing_labels is None and not args.all_self:
        review_path = resolve_run_path(run_dir, "qa/asset-slot-review.json")
        snapshots[review_path] = review_path.read_bytes()
        protected.add(review_path)
        prior_review = load_object(review_path, snapshots[review_path])
        repeat = prior_review.get("repeat_validation", {})
        maximum = float(repeat.get("max_edge_error", 0.12))
        minimum_coverage = float(repeat.get("min_edge_coverage", 0.98))
        failing_labels = {
            str(record.get("label"))
            for record in repeat.get("records", [])
            if isinstance(record, dict)
            and (
                float(record.get("edge_coverage", 0.0)) < minimum_coverage
                or float(record.get("horizontal_edge_error", 1.0)) > maximum
                or float(record.get("vertical_edge_error", 1.0)) > maximum
            )
        }
        if not failing_labels:
            raise SystemExit("prior asset-slot review has no failing self-repeat labels")
    records: list[dict[str, Any]] = []
    plans: list[dict[str, Any]] = []
    matched_labels: set[str] = set()
    phase_root = args.phase_source_dir.expanduser().resolve() if args.phase_source_dir else None
    claimed = {report_path}

    # Preflight and render every selected repair before mutating the run. This
    # prevents a missing later source from leaving an earlier frame half-repaired.
    for row in rows:
        state = row["state"]
        if state not in states:
            raise ValueError(f"unknown extracted state: {state}")
        entry = states[state]
        files = row.get("files", [])
        if not isinstance(files, list) or any(not isinstance(relative, str) for relative in files) or len(files) != entry["frames"]:
            raise ValueError(f"{state}: extracted files do not match the requested frame count")
        labels = row_labels(request, row)
        if labels and len(labels) != len(files):
            raise ValueError(f"{state}: label count does not match extracted frames")
        for index, relative in enumerate(files):
            label = str(labels[index]) if index < len(labels) else f"{state}-{index}"
            metadata = catalog.get(label, {}) if isinstance(catalog, dict) else {}
            if not isinstance(metadata, dict) or metadata.get("repeat_mode") != "self":
                continue
            if failing_labels is not None and label not in failing_labels:
                continue
            if label in matched_labels:
                raise ValueError(f"duplicate selected repeat label: {label}")
            target = resolve_run_path(run_dir, str(relative))
            if target in protected:
                raise ValueError(f"repair target cannot overwrite a source: {relative}")
            if not target.is_file():
                raise SystemExit(f"missing frame for repeat-edge repair: {relative}")
            backup_relative = (
                Path("provider")
                / "repeat-edge-repair"
                / "originals"
                / state
                / target.name
            ).as_posix()
            backup = resolve_run_path(run_dir, backup_relative)
            if backup.exists() and not args.force:
                raise SystemExit(
                    f"repeat-edge backup already exists for {label}; pass --force to reproduce"
                )
            prior_frame = backup if backup.exists() else target
            snapshots[target] = target.read_bytes()
            snapshots[prior_frame] = prior_frame.read_bytes()
            prior_bytes = snapshots[prior_frame]
            with Image.open(BytesIO(prior_bytes)) as opened:
                output_size = opened.size
                original = opened.convert("RGBA")
            if output_size != (request["cell"]["width"], request["cell"]["height"]):
                raise ValueError(f"{label}: frame dimensions do not match request.cell")
            phase_report: dict[str, Any] | None = None
            provider_source: Path | None = None
            external: Path | None = None
            source_hash: str | None = None
            source_bytes: bytes | None = None
            if phase_root is not None:
                external = resolve_run_path(phase_root, f"{label}.png")
                if not external.is_file():
                    raise SystemExit(
                        f"missing provider phase source for {label}: {external}"
                    )
                source_bytes = external.read_bytes()
                snapshots[external] = source_bytes
                source_hash = sha256(source_bytes).hexdigest()
                provider_relative = (
                    Path("provider")
                    / "repeat-edge-repair"
                    / "sources"
                    / state
                    / f"{_portable_label(label)}-{source_hash[:12]}.png"
                ).as_posix()
                provider_source = resolve_run_path(run_dir, provider_relative)
                if provider_source.exists() and digest(provider_source) != source_hash:
                    raise SystemExit(
                        f"stored provider source hash changed for {label}: {provider_source}"
                    )
                with Image.open(BytesIO(source_bytes)) as opened:
                    normalized, phase_report = periodic_phase_crop(
                        opened,
                        output_size=output_size,
                        max_trim_ratio=args.phase_max_trim_ratio,
                        prefer_dark_boundaries=(
                            args.phase_boundary_preference == "dark"
                            or (
                                args.phase_boundary_preference == "auto"
                                and "grid" in label
                            )
                        ),
                    )
                repaired = harmonize_repeat_edges(
                    normalized,
                    blend_width=args.phase_blend_width,
                    edge_strip=2,
                )
                applied_blend, applied_strip = repair_widths(output_size, args.phase_blend_width, 2)
            else:
                repaired = harmonize_repeat_edges(original, blend_width=args.blend_width, edge_strip=args.edge_strip)
                applied_blend, applied_strip = repair_widths(output_size, args.blend_width, args.edge_strip)
            for output in (target, backup, *([provider_source] if provider_source else [])):
                if output in claimed or (output in protected and not output.is_file()):
                    raise ValueError(f"repair outputs alias another output or protected source: {output}")
                claimed.add(output)
            center = (applied_blend, applied_blend, output_size[0] - applied_blend, output_size[1] - applied_blend)
            plans.append(
                {
                    "state": state,
                    "frame": index,
                    "label": label,
                    "target": target,
                    "backup": backup,
                    "prior_frame_sha256": sha256(prior_bytes).hexdigest(),
                    "prior_bytes": prior_bytes,
                    "external": external,
                    "provider_source": provider_source,
                    "source_sha256": source_hash,
                    "source_bytes": source_bytes,
                    "effective_blend_width": applied_blend,
                    "effective_edge_strip": applied_strip,
                    "center_preserved": phase_root is None and original.crop(center).tobytes() == repaired.crop(center).tobytes(),
                    "phase_report": phase_report,
                    "repaired": repaired,
                }
            )
            matched_labels.add(label)

    if failing_labels is not None:
        missing = sorted(failing_labels - matched_labels)
        if missing:
            raise SystemExit(
                "selected labels are not self-repeat frames: " + ", ".join(missing)
            )
    if not plans:
        raise SystemExit("no self-repeat frames selected for repair")
    immutable_inputs = {plan["external"] for plan in plans if plan["external"] is not None}
    if immutable_inputs & claimed or any(plan["target"] in {other["backup"], other["provider_source"]} for plan in plans for other in plans):
        raise ValueError("repair outputs cannot overwrite immutable repair inputs")
    updated_request = request
    if phase_root is not None:
        additions = [{
            "path": plan["provider_source"].relative_to(run_dir).as_posix(),
            "sha256": plan["source_sha256"], "size_bytes": len(plan["source_bytes"]),
            "states": [plan["state"]], "source_type": args.provider,
            "art_engine": PROVIDER_ART_ENGINES[args.provider],
        } for plan in plans]
        provenance, updated_request = merge_provider_provenance(provenance, request, additions, provider=args.provider)

    with acquire_run_lock(run_dir, "repair-repeat-edges"):
        # Recheck all inputs under the run lock before the first write.
        for path, expected_bytes in snapshots.items():
            if path.read_bytes() != expected_bytes:
                raise ValueError(f"repair input changed during preflight: {path}")

        # Materialize and verify every immutable input before changing a frame.
        for plan in plans:
            backup: Path = plan["backup"]
            backup.parent.mkdir(parents=True, exist_ok=True)
            if not backup.exists():
                atomic_write_bytes(backup, plan["prior_bytes"])
            if digest(backup) != plan["prior_frame_sha256"]:
                raise SystemExit(f"repeat-edge backup hash mismatch: {plan['label']}")
            provider_source: Path | None = plan["provider_source"]
            if provider_source is not None:
                provider_source.parent.mkdir(parents=True, exist_ok=True)
                if not provider_source.exists():
                    atomic_write_bytes(provider_source, plan["source_bytes"])
                if digest(provider_source) != plan["source_sha256"]:
                    raise SystemExit(f"provider source hash mismatch: {plan['label']}")

        for plan in plans:
            target: Path = plan["target"]
            backup: Path = plan["backup"]
            provider_source: Path | None = plan["provider_source"]
            before = digest(backup)
            prior_output = digest(target)
            atomic_save_image(plan["repaired"], target)
            source_path = provider_source or backup
            record = {
                "state": plan["state"],
                "frame": plan["frame"],
                "label": plan["label"],
                "source": source_path.relative_to(run_dir).as_posix(),
                "source_sha256": digest(source_path),
                "prior_frame_source": backup.relative_to(run_dir).as_posix(),
                "prior_frame_source_sha256": before,
                "prior_output_sha256": prior_output,
                "output": target.relative_to(run_dir).as_posix(),
                "output_sha256": digest(target),
                "effective_blend_width": plan["effective_blend_width"],
                "effective_edge_strip": plan["effective_edge_strip"],
                "center_preserved": plan["center_preserved"],
                "normalization": (
                    "provider-phase-crop+narrow-edge-harmonization"
                    if provider_source
                    else "edge-harmonization"
                ),
            }
            if plan["phase_report"]:
                record["phase_crop"] = plan["phase_report"]
            records.append(record)

        if phase_root is not None and records:
            atomic_write_text(
                provenance_path,
                json.dumps(provenance, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
            )
            if updated_request != request:
                atomic_write_text(
                    request_path,
                    json.dumps(updated_request, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
                )
                request = updated_request
        report = {
            "version": 1,
            "kind": "repeat-edge-repair",
            "ok": bool(records),
            "provider_source_type": provenance.get("source_type"),
            "blend_width": args.blend_width,
            "phase_blend_width": args.phase_blend_width,
            "edge_strip": args.edge_strip,
            "semantic_generation": False,
            "semantic_source_replaced": bool(args.phase_source_dir),
            "center_preserved": all(record["center_preserved"] for record in records),
            "provider_slot_retry": bool(args.phase_source_dir),
            "visual_review_required": True,
            "records": records,
        }
        report_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(report_path, json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    print(json.dumps({"ok": bool(records), "repaired": len(records), "report": "qa/repeat-edge-repair-report.json"}))
    return 0 if records else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        print(json.dumps({"ok": False, "status": "operational-error", "errors": [str(exc)]}))
        raise SystemExit(3)
