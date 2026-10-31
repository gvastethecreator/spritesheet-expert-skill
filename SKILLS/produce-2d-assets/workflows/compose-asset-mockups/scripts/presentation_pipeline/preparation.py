from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from .contracts import validate_prepared_presentation, validate_presentation


_PRODUCTION_SOURCE_TYPES = frozenset(
    {"imagegen", "grok-imagine-image", "grok-imagine-video", "imported", "mixed"}
)


def canonical_json_bytes(document: Mapping[str, Any]) -> bytes:
    """Return the stable JSON encoding used by every pipeline fingerprint."""

    return json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def document_fingerprint(document: Mapping[str, Any]) -> str:
    return "sha256:" + sha256(canonical_json_bytes(document)).hexdigest()


def prepare_presentation(document: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and seal a presentation request without touching source assets."""

    validate_presentation(document)
    presentation = deepcopy(dict(document))
    prepared = {
        "schema_version": 1,
        "kind": "prepared-presentation",
        "presentation_sha256": document_fingerprint(presentation),
        "presentation": presentation,
    }
    validate_prepared_presentation(prepared)
    return prepared


def _verified_pin(root: Path, pin: Mapping[str, Any], label: str) -> tuple[Path, bytes]:
    candidate = (root / pin["path"]).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise ValueError(f"{label} escapes the presentation root") from error
    if not candidate.is_file():
        raise FileNotFoundError(f"{label} is missing: {pin['path']}")
    content = candidate.read_bytes()
    actual = sha256(content).hexdigest()
    if actual != pin["sha256"]:
        raise ValueError(
            f"{label} hash mismatch: expected {pin['sha256']}, got {actual}"
        )
    return candidate, content


def _verified_production_media(content: bytes, label: str) -> dict[str, Any]:
    try:
        report = json.loads(content.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as error:
        raise ValueError(f"{label} is not valid JSON") from error
    evidence = report.get("evidence") if isinstance(report, Mapping) else None
    production_media = evidence.get("production_media") if isinstance(evidence, Mapping) else None
    if not isinstance(production_media, Mapping):
        raise ValueError(f"{label} is missing evidence.production_media")
    source_types = production_media.get("source_types")
    if production_media.get("representative") is not True:
        raise ValueError(f"{label} is not representative production media")
    if production_media.get("provenance_verified") is not True:
        raise ValueError(f"{label} has unverified production provenance")
    if (
        not isinstance(source_types, list)
        or not source_types
        or len(source_types) != len(set(source_types))
        or any(source_type not in _PRODUCTION_SOURCE_TYPES for source_type in source_types)
    ):
        raise ValueError(f"{label} has missing or invalid production source_types")
    return {
        "representative": True,
        "provenance_verified": True,
        "source_types": list(source_types),
    }


def resolve_presentation(
    prepared: Mapping[str, Any], root: str | Path
) -> dict[str, Any]:
    """Verify and copy imported assets into a content-addressed presentation store."""

    validate_prepared_presentation(prepared)
    root_path = Path(root).resolve()
    presentation = prepared["presentation"]
    sources = [
        *(('asset', item) for item in presentation["inventory"]["assets"]),
        *(('font', item) for item in presentation["brand_kit"]["fonts"]),
    ]
    imports: list[dict[str, Any]] = []

    for kind, item in sources:
        source = item["source"]
        _verified_pin(root_path, source["manifest"], f"{kind} '{item['id']}' manifest")
        _, validation_content = _verified_pin(
            root_path,
            source["validation_report"],
            f"{kind} '{item['id']}' validation_report",
        )
        production_media = (
            _verified_production_media(
                validation_content, f"{kind} '{item['id']}' validation_report"
            )
            if kind == "asset"
            else None
        )
        source_path, content = _verified_pin(
            root_path, source["artifact"], f"{kind} '{item['id']}' artifact"
        )
        digest = source["artifact"]["sha256"]
        relative_destination = Path(
            "presentation", "content-addressed", "sha256", digest[:2], f"{digest}{source_path.suffix.lower()}"
        )
        destination = (root_path / relative_destination).resolve()
        try:
            destination.relative_to(root_path)
        except ValueError as error:
            raise ValueError(f"{kind} '{item['id']}' destination escapes the presentation root") from error
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            existing = destination.read_bytes()
            if sha256(existing).hexdigest() != digest:
                raise ValueError(f"content-addressed destination is corrupt: {relative_destination.as_posix()}")
        else:
            destination.write_bytes(content)
        imports.append(
            {
                "id": f"{kind}:{item['id']}",
                "source_path": source["artifact"]["path"],
                "content_path": relative_destination.as_posix(),
                "sha256": digest,
                **({"production_media": production_media} if production_media else {}),
            }
        )

    return {
        "schema_version": 1,
        "kind": "resolved-presentation",
        "presentation_sha256": prepared["presentation_sha256"],
        "presentation": deepcopy(presentation),
        "imports": imports,
    }
