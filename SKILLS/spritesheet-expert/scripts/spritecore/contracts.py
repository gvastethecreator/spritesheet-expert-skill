"""Load, normalize, and validate versioned spritesheet contracts.

The public functions hide schema discovery and legacy migration. Callers receive
only canonical v2 :class:`ContractDocument` values unless they explicitly call
``validate_contract`` on an already-versioned document.
"""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any, IO, Mapping

from jsonschema import Draft202012Validator

from spritecore.models import ContractDocument, ContractKind, is_state_slug


CURRENT_CONTRACT_VERSION = 2
_SCHEMA_ROOT = Path(__file__).resolve().parents[2] / "references" / "schemas"
_SCHEMA_FILES = {
    ContractKind.SPRITE_REQUEST: "sprite-request-v2.schema.json",
    ContractKind.PROVENANCE: "source-provenance-v2.schema.json",
    ContractKind.MANIFEST: "sprite-manifest-v2.schema.json",
    ContractKind.REPORT: "qa-report-v2.schema.json",
}
_ART_ENGINE_SOURCE_TYPES = {
    "imagegen": frozenset({"imagegen", "$imagegen", "openai-image"}),
    "imported": frozenset({"imported", "user-provided", "existing-sheet"}),
    "fixture": frozenset({"fixture", "synthetic", "procedural"}),
}


class ContractError(ValueError):
    """Base error for the public contract boundary."""


class ContractLoadError(ContractError):
    """The supplied source could not be read as a JSON object."""


class ContractValidationError(ContractError):
    """The contract violates its versioned schema or semantic invariants."""

    def __init__(self, kind: ContractKind, issues: list[str]):
        self.kind = kind
        self.issues = tuple(issues)
        super().__init__(f"invalid {kind.value} contract: " + "; ".join(issues))


ContractSource = Mapping[str, Any] | str | Path | IO[str]


def derive_sampling_policy(asset_kind: str, *, pixel_art: bool | None) -> dict[str, Any]:
    """Derive the canonical sampling defaults shared by requests and manifests."""

    effective_pixel_art = asset_kind != "texture" if pixel_art is None else pixel_art
    return {
        "filter": "nearest" if effective_pixel_art else "linear",
        "wrap": "repeat" if asset_kind == "texture" else "clamp-to-edge",
        "mipmaps": False,
        "pixel_snap": bool(effective_pixel_art),
    }


def load_contract(
    source: ContractSource,
    *,
    expected_kind: ContractKind | str | None = None,
) -> ContractDocument:
    """Load a mapping/path/file, migrate legacy input to v2, then validate it."""

    payload, source_path = _read_source(source)
    return normalize_contract(payload, expected_kind=expected_kind, source=source_path)


def normalize_contract(
    payload: Mapping[str, Any],
    *,
    expected_kind: ContractKind | str | None = None,
    source: Path | None = None,
) -> ContractDocument:
    """Return a detached, canonical v2 document without mutating ``payload``."""

    document = deepcopy(dict(payload))
    kind = _resolve_kind(document, expected_kind)
    version = _document_version(document)
    if version > CURRENT_CONTRACT_VERSION:
        raise ContractValidationError(kind, [f"unsupported version {version}"])
    if version < CURRENT_CONTRACT_VERSION:
        document = _migrate_v1(document, kind)
    elif kind is ContractKind.SPRITE_REQUEST:
        document = _normalize_request_defaults(document)
    return validate_contract(document, expected_kind=kind, source=source)


def validate_contract(
    payload: Mapping[str, Any],
    *,
    expected_kind: ContractKind | str | None = None,
    source: Path | None = None,
) -> ContractDocument:
    """Validate an already-versioned document and return a detached value."""

    document = deepcopy(dict(payload))
    kind = _resolve_kind(document, expected_kind)
    version = _document_version(document)
    if version != CURRENT_CONTRACT_VERSION:
        raise ContractValidationError(kind, [f"expected version {CURRENT_CONTRACT_VERSION}, got {version}"])
    schema = json.loads((_SCHEMA_ROOT / _SCHEMA_FILES[kind]).read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    issues = [_format_schema_error(error) for error in sorted(validator.iter_errors(document), key=lambda error: list(error.absolute_path))]
    issues.extend(_semantic_issues(document, kind))
    if issues:
        raise ContractValidationError(kind, issues)
    return ContractDocument(kind=kind, version=version, data=document, source=source)


def load_sprite_request(source: ContractSource) -> ContractDocument:
    return load_contract(source, expected_kind=ContractKind.SPRITE_REQUEST)


def load_provenance(source: ContractSource) -> ContractDocument:
    return load_contract(source, expected_kind=ContractKind.PROVENANCE)


def load_manifest(source: ContractSource) -> ContractDocument:
    return load_contract(source, expected_kind=ContractKind.MANIFEST)


def load_report(source: ContractSource) -> ContractDocument:
    return load_contract(source, expected_kind=ContractKind.REPORT)


def _read_source(source: ContractSource) -> tuple[dict[str, Any], Path | None]:
    if isinstance(source, Mapping):
        return deepcopy(dict(source)), None
    source_path: Path | None = None
    try:
        if hasattr(source, "read"):
            raw = source.read()
        else:
            source_path = Path(source).expanduser().resolve()
            raw = source_path.read_text(encoding="utf-8-sig")
        payload = json.loads(raw)
    except (OSError, TypeError, ValueError) as exc:
        raise ContractLoadError(f"could not load contract: {exc}") from exc
    if not isinstance(payload, dict):
        raise ContractLoadError("contract root must be a JSON object")
    return payload, source_path


def _coerce_kind(value: ContractKind | str) -> ContractKind:
    if isinstance(value, ContractKind):
        return value
    aliases = {
        "sprite-gen-request": ContractKind.SPRITE_REQUEST,
        "sprite-request": ContractKind.SPRITE_REQUEST,
        "sprite-source-provenance": ContractKind.PROVENANCE,
        "source-provenance": ContractKind.PROVENANCE,
        "sprite-atlas-manifest": ContractKind.MANIFEST,
        "sprite-qa-report": ContractKind.REPORT,
    }
    if value in aliases:
        return aliases[value]
    try:
        return ContractKind(value)
    except ValueError as exc:
        raise ContractLoadError(f"unknown contract kind: {value!r}") from exc


def _detect_kind(document: Mapping[str, Any]) -> ContractKind:
    raw_kind = document.get("kind")
    if isinstance(raw_kind, str):
        try:
            return _coerce_kind(raw_kind)
        except ContractLoadError:
            pass
    if "frame_layout" in document:
        return ContractKind.MANIFEST
    if "ok" in document and ("errors" in document or "warnings" in document):
        return ContractKind.REPORT
    raise ContractLoadError("contract kind is missing or cannot be inferred")


def _resolve_kind(
    document: Mapping[str, Any], expected_kind: ContractKind | str | None
) -> ContractKind:
    if expected_kind is None:
        return _detect_kind(document)
    expected = _coerce_kind(expected_kind)
    declared_raw = document.get("kind")
    if declared_raw is None:
        return expected
    if not isinstance(declared_raw, str):
        raise ContractValidationError(expected, ["declared kind must be a string"])
    try:
        declared = _coerce_kind(declared_raw)
    except ContractLoadError as exc:
        raise ContractValidationError(expected, [f"unknown declared kind {declared_raw!r}"]) from exc
    if declared is not expected:
        raise ContractValidationError(
            expected,
            [f"declared kind {declared.value!r} does not match expected {expected.value!r}"],
        )
    return expected


def _document_version(document: Mapping[str, Any]) -> int:
    raw = document.get("version", 1)
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
        raise ContractLoadError("contract version must be a positive integer")
    return raw


def _migrate_v1(document: dict[str, Any], kind: ContractKind) -> dict[str, Any]:
    if kind is ContractKind.SPRITE_REQUEST:
        return _normalize_request_defaults(document | {"version": CURRENT_CONTRACT_VERSION})
    if kind is ContractKind.PROVENANCE:
        normalized = deepcopy(document)
        explicit_source_type = normalized.get("source_type")
        art_engine = normalized.get("art_engine")
        if not explicit_source_type:
            explicit_source_type = _source_type_from_art_engine(art_engine)
        if not explicit_source_type:
            raise ContractValidationError(
                kind,
                ["v1 provenance has no explicit source_type or recognized art_engine; refusing to invent provenance"],
            )
        normalized["version"] = CURRENT_CONTRACT_VERSION
        normalized["kind"] = "sprite-source-provenance"
        normalized["source_type"] = explicit_source_type
        normalized["art_engine"] = explicit_source_type
        normalized["fixture"] = explicit_source_type == "fixture"
        normalized["verification_status"] = "legacy-unverified"
        normalized["accepted_sources"] = [
            {
                "path": path,
                "sha256": None,
                "size_bytes": None,
                "states": [],
            }
            for path in normalized.pop("source_images", [])
        ]
        normalized["state_coverage"] = []
        return normalized
    if kind is ContractKind.MANIFEST:
        normalized = deepcopy(document)
        layout = normalized.get("frame_layout") if isinstance(normalized.get("frame_layout"), dict) else {}
        cell = normalized.get("cell") if isinstance(normalized.get("cell"), dict) else {}
        asset_kind = str(normalized.get("asset_kind") or "sprite")
        if asset_kind == "props":
            asset_kind = "prop"
        output = normalized.get("output") if isinstance(normalized.get("output"), dict) else {}
        normalized.update(
            {
                "version": CURRENT_CONTRACT_VERSION,
                "kind": "sprite-atlas-manifest",
                "asset_kind": asset_kind,
                "frame_semantics": output.get("frame_semantics")
                or ("animation" if asset_kind == "sprite" else "seamless-textures" if asset_kind == "texture" else "tiles" if asset_kind == "tileset" else "still-assets"),
                "cell": {
                    **cell,
                    "width": cell.get("width", layout.get("cellWidth")),
                    "height": cell.get("height", layout.get("cellHeight")),
                },
                "atlas": {
                    "path": normalized.get("sprite_sheet_alpha") or normalized.get("game_input"),
                    "width": layout.get("sheetWidth"),
                    "height": layout.get("sheetHeight"),
                },
            }
        )
        normalized.setdefault(
            "sampling_policy",
            derive_sampling_policy(asset_kind, pixel_art=_pixel_art_hint(normalized)),
        )
        return normalized
    if kind is ContractKind.REPORT:
        normalized = deepcopy(document)
        normalized["version"] = CURRENT_CONTRACT_VERSION
        normalized["kind"] = "sprite-qa-report"
        normalized["report_type"] = normalized.get("report_type") or normalized.get("engine")
        normalized.setdefault("errors", [])
        normalized.setdefault("warnings", [])
        normalized.setdefault("metrics", {})
        return normalized
    raise ContractValidationError(kind, ["v1 migration is not yet defined for this contract kind"])


def _normalize_request_defaults(document: dict[str, Any]) -> dict[str, Any]:
    normalized = deepcopy(document)
    normalized["version"] = CURRENT_CONTRACT_VERSION
    normalized["kind"] = "sprite-gen-request"
    asset_kind = str(normalized.get("asset_kind") or "sprite")
    if asset_kind == "props":
        asset_kind = "prop"
    normalized["asset_kind"] = asset_kind
    output = normalized.get("output") if isinstance(normalized.get("output"), dict) else {}
    semantics_by_kind = {
        "sprite": "animation",
        "tileset": "tiles",
        "texture": "seamless-textures",
        "vfx": "effects",
    }
    normalized.setdefault("frame_semantics", output.get("frame_semantics") or semantics_by_kind.get(asset_kind, "still-assets"))
    normalized.setdefault("extraction_mode", "components" if asset_kind == "sprite" else "slots")
    raw_layout_policy = str(normalized.get("raw_layout_policy", "compact-body-grids"))
    normalized["raw_layout_policy"] = raw_layout_policy
    cell = normalized.get("cell")
    if isinstance(cell, dict) and "size" in cell:
        cell.setdefault("width", cell["size"])
        cell.setdefault("height", cell["size"])
    states = normalized.get("states")
    if isinstance(states, dict):
        for entry in states.values():
            if not isinstance(entry, dict):
                continue
            frames = entry.get("frames")
            if (
                raw_layout_policy != "off"
                and isinstance(frames, int)
                and not isinstance(frames, bool)
                and frames > 0
            ):
                entry["raw_layout"] = _complete_raw_layout(entry.get("raw_layout"), frames)
    normalized.setdefault(
        "sampling_policy",
        derive_sampling_policy(asset_kind, pixel_art=_pixel_art_hint(normalized)),
    )
    return normalized


def _pixel_art_hint(document: Mapping[str, Any]) -> bool | None:
    if "style_preset" in document:
        return document.get("style_preset") == "pixel-art"
    art_direction = document.get("art_direction")
    if isinstance(art_direction, Mapping) and "mode" in art_direction:
        return art_direction.get("mode") == "pixel-art"
    return None


def _complete_raw_layout(value: Any, frames: int) -> dict[str, Any]:
    raw = deepcopy(value) if isinstance(value, dict) else {}
    columns = raw.get("columns", raw.get("cols"))
    rows = raw.get("rows")
    if not isinstance(columns, int) or isinstance(columns, bool) or columns < 1:
        columns = (frames + rows - 1) // rows if isinstance(rows, int) and rows > 0 else frames
    if not isinstance(rows, int) or isinstance(rows, bool) or rows < 1:
        rows = (frames + columns - 1) // columns
    kind = raw.get("kind") or ("compact-grid" if rows > 1 or columns != frames else "strip")
    completed = {
        "kind": kind,
        "columns": columns,
        "rows": rows,
        "order": raw.get("order") or ("row-major" if kind == "compact-grid" else "left-to-right"),
        "delivery": raw.get("delivery") or "compose-runtime-row",
    }
    if "reason" in raw:
        completed["reason"] = raw["reason"]
    return completed


def _format_schema_error(error: Any) -> str:
    path = ".".join(str(part) for part in error.absolute_path)
    return f"{path}: {error.message}" if path else error.message


def _source_type_from_art_engine(art_engine: Any) -> str | None:
    if not isinstance(art_engine, str):
        return None
    marker = art_engine.strip().lower()
    return next(
        (source_type for source_type, markers in _ART_ENGINE_SOURCE_TYPES.items() if marker in markers),
        None,
    )


def _semantic_issues(document: Mapping[str, Any], kind: ContractKind) -> list[str]:
    issues: list[str] = []
    if kind is ContractKind.PROVENANCE:
        source_type = document.get("source_type")
        engine_source_type = _source_type_from_art_engine(document.get("art_engine"))
        if engine_source_type is not None and engine_source_type != source_type:
            issues.append(
                "art_engine identifies "
                f"{engine_source_type} provenance but source_type is {source_type}"
            )
        accepted_sources = document.get("accepted_sources")
        state_coverage = document.get("state_coverage")
        if isinstance(accepted_sources, list):
            paths = [
                entry.get("path")
                for entry in accepted_sources
                if isinstance(entry, Mapping)
            ]
            if len(paths) != len(set(paths)):
                issues.append("accepted_sources paths must be unique")
            covered = {
                state
                for entry in accepted_sources
                if isinstance(entry, Mapping)
                for state in entry.get("states", [])
                if isinstance(state, str)
            }
            if isinstance(state_coverage, list) and covered != set(state_coverage):
                issues.append("state_coverage must exactly match accepted_sources states")
        return issues
    if kind is ContractKind.MANIFEST:
        atlas = document.get("atlas", {})
        layout = document.get("frame_layout", {})
        if isinstance(atlas, Mapping) and isinstance(layout, Mapping):
            width, height = atlas.get("width"), atlas.get("height")
            rows = layout.get("rows", {})
            if isinstance(width, int) and isinstance(height, int) and isinstance(rows, Mapping):
                for state, rects in rows.items():
                    if not is_state_slug(state):
                        issues.append(f"frame_layout.rows.{state!r}: invalid state id")
                    if not isinstance(rects, list):
                        continue
                    for index, rect in enumerate(rects):
                        if not isinstance(rect, Mapping):
                            continue
                        x, y, w, h = (rect.get(key) for key in ("x", "y", "w", "h"))
                        if all(isinstance(value, int) for value in (x, y, w, h)) and (x + w > width or y + h > height):
                            issues.append(f"frame_layout.rows.{state}.{index}: rectangle exceeds atlas bounds")
        return issues
    if kind is not ContractKind.SPRITE_REQUEST:
        return issues
    states = document.get("states", {})
    raw_layout_policy = document.get("raw_layout_policy")
    is_vfx_request = document.get("asset_kind") == "vfx"
    if isinstance(states, Mapping):
        for state, entry in states.items():
            if not is_state_slug(state):
                issues.append(f"states.{state!r}: invalid state id")
            if not isinstance(entry, Mapping):
                continue
            frames = entry.get("frames")
            durations = entry.get("durations_ms")
            layout = entry.get("raw_layout")
            vfx = entry.get("vfx")
            if (
                isinstance(frames, int)
                and not isinstance(frames, bool)
                and isinstance(durations, list)
                and len(durations) != frames
            ):
                issues.append(
                    f"states.{state}.durations_ms: expected {frames} entries for {frames} frames, got {len(durations)}"
                )
            if raw_layout_policy == "off" and layout is not None:
                issues.append(f"states.{state}.raw_layout: must be absent when raw_layout_policy is off")
            elif raw_layout_policy != "off" and not isinstance(layout, Mapping):
                issues.append(f"states.{state}.raw_layout: is required unless raw_layout_policy is off")
            if isinstance(frames, int) and isinstance(layout, Mapping):
                columns = layout.get("columns")
                rows = layout.get("rows")
                if isinstance(columns, int) and isinstance(rows, int) and columns * rows < frames:
                    issues.append(f"states.{state}.raw_layout: capacity {columns * rows} is smaller than {frames} frames")
            if is_vfx_request and isinstance(frames, int) and isinstance(vfx, Mapping):
                phases = vfx.get("phase_sequence")
                if isinstance(phases, list) and len(phases) != frames:
                    issues.append(
                        f"states.{state}.vfx.phase_sequence: expected {frames} entries "
                        f"for {frames} frames, got {len(phases)}"
                    )
                loop = entry.get("loop")
                loop_behavior = vfx.get("loop_behavior")
                if isinstance(loop, bool) and isinstance(loop_behavior, str):
                    if loop and loop_behavior != "loop":
                        issues.append(
                            f"states.{state}.vfx.loop_behavior: loop:true requires 'loop', "
                            f"got {loop_behavior!r}"
                        )
                    elif not loop and loop_behavior == "loop":
                        issues.append(
                            f"states.{state}.vfx.loop_behavior: loop:false cannot use 'loop'"
                        )
    return issues
