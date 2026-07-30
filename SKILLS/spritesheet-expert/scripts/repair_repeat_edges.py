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
import json
from pathlib import Path
import re
import shutil
from typing import Any

from PIL import Image

from runio import atomic_save_image, atomic_write_text
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


def harmonize_repeat_edges(
    image: Image.Image,
    *,
    blend_width: int,
    edge_strip: int = 2,
) -> Image.Image:
    result = image.convert("RGBA")
    width, height = result.size
    if width < 8 or height < 8:
        raise ValueError("repeat-edge repair requires frames of at least 8x8")
    blend_width = max(edge_strip, min(blend_width, width // 3, height // 3))
    edge_strip = max(1, min(edge_strip, blend_width))
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
    max_trim = max(2, min(round(length * max_trim_ratio), length // 3))
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


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
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
        path = str(addition.get("path"))
        existing = known.get(path)
        if existing is not None:
            for field in ("sha256", "size_bytes", "states"):
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
    run_dir = args.run_dir.expanduser().resolve()
    request = load_sprite_request(run_dir / "sprite-request.json").to_dict()
    manifest = load_object(run_dir / "frames" / "frames-manifest.json")
    provenance = load_provenance(run_dir / "source-provenance.json").to_dict()
    if provenance.get("source_type") not in ALLOWED_PROVIDER_TYPES:
        raise SystemExit("repeat-edge repair requires provider-generated source provenance")
    catalog = request.get("asset_catalog", {}).get("items", {})
    states = request.get("states", {})
    rows = manifest.get("rows", [])
    explicit_labels = {
        item.strip() for item in str(args.labels or "").split(",") if item.strip()
    }
    if args.phase_source_dir and (not explicit_labels or not args.provider):
        raise SystemExit("--phase-source-dir requires --labels and --provider")
    if args.provider and not args.phase_source_dir:
        raise SystemExit("--provider requires --phase-source-dir")
    failing_labels: set[str] | None = explicit_labels or None
    if failing_labels is None and not args.all_self:
        prior_review = load_object(run_dir / "qa" / "asset-slot-review.json")
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

    # Preflight and render every selected repair before mutating the run. This
    # prevents a missing later source from leaving an earlier frame half-repaired.
    for row in rows:
        state = str(row.get("state", ""))
        entry = states.get(state, {}) if isinstance(states, dict) else {}
        labels = entry.get("asset_labels", []) if isinstance(entry, dict) else []
        for index, relative in enumerate(row.get("files", [])):
            label = str(labels[index]) if index < len(labels) else f"{state}-{index}"
            metadata = catalog.get(label, {}) if isinstance(catalog, dict) else {}
            if not isinstance(metadata, dict) or metadata.get("repeat_mode") != "self":
                continue
            if failing_labels is not None and label not in failing_labels:
                continue
            target = resolve_run_path(run_dir, str(relative))
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
            with Image.open(prior_frame) as opened:
                output_size = opened.size
            phase_report: dict[str, Any] | None = None
            provider_source: Path | None = None
            external: Path | None = None
            source_hash: str | None = None
            if phase_root is not None:
                external = resolve_run_path(phase_root, f"{label}.png")
                if not external.is_file():
                    raise SystemExit(
                        f"missing provider phase source for {label}: {external}"
                    )
                source_hash = digest(external)
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
                with Image.open(external) as opened:
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
            else:
                with Image.open(prior_frame) as opened:
                    repaired = harmonize_repeat_edges(
                        opened,
                        blend_width=args.blend_width,
                        edge_strip=args.edge_strip,
                    )
            plans.append(
                {
                    "state": state,
                    "frame": index,
                    "label": label,
                    "target": target,
                    "backup": backup,
                    "prior_frame_sha256": digest(prior_frame),
                    "external": external,
                    "provider_source": provider_source,
                    "source_sha256": source_hash,
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

    with acquire_run_lock(run_dir, "repair-repeat-edges"):
        # Recheck all inputs under the run lock before the first write.
        for plan in plans:
            prior_frame = plan["backup"] if plan["backup"].exists() else plan["target"]
            if digest(prior_frame) != plan["prior_frame_sha256"]:
                raise SystemExit(f"repair input changed during preflight: {plan['label']}")
            if plan["external"] is not None and digest(plan["external"]) != plan["source_sha256"]:
                raise SystemExit(
                    f"provider phase source changed during preflight: {plan['label']}"
                )

        # Materialize and verify every immutable input before changing a frame.
        for plan in plans:
            backup: Path = plan["backup"]
            backup.parent.mkdir(parents=True, exist_ok=True)
            if not backup.exists():
                shutil.copy2(plan["target"], backup)
            if digest(backup) != plan["prior_frame_sha256"]:
                raise SystemExit(f"repeat-edge backup hash mismatch: {plan['label']}")
            provider_source: Path | None = plan["provider_source"]
            if provider_source is not None:
                provider_source.parent.mkdir(parents=True, exist_ok=True)
                if not provider_source.exists():
                    shutil.copy2(plan["external"], provider_source)
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
            provider_art_engine = PROVIDER_ART_ENGINES[str(args.provider)]
            additions = []
            for record in records:
                source_path = resolve_run_path(run_dir, str(record["source"]))
                additions.append(
                    {
                        "path": record["source"],
                        "sha256": digest(source_path),
                        "size_bytes": source_path.stat().st_size,
                        "states": [str(record["state"])],
                        "source_type": args.provider,
                        "art_engine": provider_art_engine,
                    }
                )
            provenance, updated_request = merge_provider_provenance(
                provenance,
                request,
                additions,
                provider=str(args.provider),
            )
            atomic_write_text(
                run_dir / "source-provenance.json",
                json.dumps(provenance, indent=2, ensure_ascii=False) + "\n",
            )
            if updated_request != request:
                atomic_write_text(
                    run_dir / "sprite-request.json",
                    json.dumps(updated_request, indent=2, ensure_ascii=False) + "\n",
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
            "center_preserved": not bool(args.phase_source_dir),
            "provider_slot_retry": bool(args.phase_source_dir),
            "visual_review_required": True,
            "records": records,
        }
        report_path = run_dir / "qa" / "repeat-edge-repair-report.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(report_path, json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"ok": bool(records), "repaired": len(records), "report": "qa/repeat-edge-repair-report.json"}))
    return 0 if records else 1


if __name__ == "__main__":
    raise SystemExit(main())
