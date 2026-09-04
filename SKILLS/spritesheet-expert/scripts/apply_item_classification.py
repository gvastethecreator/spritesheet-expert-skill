#!/usr/bin/env python3
"""Validate classification results and write an immutable successor manifest."""

from __future__ import annotations

import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Iterable, Mapping


class ClassificationApplicationError(ValueError):
    pass


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ClassificationApplicationError(f"cannot read JSON {path}: {exc}") from exc


def _read_results(path: Path) -> list[dict[str, Any]]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ClassificationApplicationError(f"cannot read results: {exc}") from exc
    stripped = raw.strip()
    if not stripped:
        return []
    try:
        decoded = json.loads(stripped)
    except json.JSONDecodeError:
        decoded = None
    if isinstance(decoded, list):
        return [entry for entry in decoded if isinstance(entry, dict)]
    if isinstance(decoded, dict):
        values = decoded.get("results")
        if isinstance(values, list):
            return [entry for entry in values if isinstance(entry, dict)]
        return [decoded]

    results: list[dict[str, Any]] = []
    for number, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ClassificationApplicationError(f"invalid JSONL line {number}: {exc}") from exc
        if not isinstance(entry, dict):
            raise ClassificationApplicationError(f"result line {number} must be an object")
        results.append(entry)
    return results


def _digest(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _allowed_taxonomy(taxonomy: Mapping[str, Any]) -> tuple[dict[str, set[str]], set[str], set[str], set[str], set[str]]:
    families_raw = taxonomy.get("families")
    if not isinstance(families_raw, Mapping):
        raise ClassificationApplicationError("taxonomy requires a families object")
    families: dict[str, set[str]] = {}
    for family, values in families_raw.items():
        if not isinstance(family, str) or not isinstance(values, list):
            raise ClassificationApplicationError("taxonomy families must map strings to arrays")
        families[family] = {str(value) for value in values}
    families.setdefault("unknown", set()).add("unknown")
    return (
        families,
        {str(value) for value in taxonomy.get("materials", [])},
        {str(value) for value in taxonomy.get("conditions", [])},
        {str(value) for value in taxonomy.get("orientations", [])} | {"unknown"},
        {str(value) for value in taxonomy.get("sizeClasses", [])} | {"unknown"},
    )


def _string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(entry, str) for entry in value):
        raise ClassificationApplicationError(f"{field} must be an array of strings")
    return list(dict.fromkeys(value))


def _normalize_result(
    result: Mapping[str, Any],
    taxonomy: Mapping[str, Any],
    *,
    minimum_confidence: float,
) -> tuple[str, dict[str, Any], list[str]]:
    item_id = result.get("itemId") or result.get("item_id")
    if not isinstance(item_id, str) or not item_id:
        raise ClassificationApplicationError("every result requires itemId")
    payload = result.get("classification", result)
    if not isinstance(payload, Mapping):
        raise ClassificationApplicationError(f"{item_id}: classification must be an object")

    families, materials_allowed, conditions_allowed, orientations_allowed, sizes_allowed = _allowed_taxonomy(taxonomy)
    family = str(payload.get("family", "unknown"))
    canonical = str(payload.get("canonicalType", payload.get("canonical_type", "unknown")))
    confidence = payload.get("confidence", 0.0)
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise ClassificationApplicationError(f"{item_id}: confidence must be numeric")
    confidence = max(0.0, min(1.0, float(confidence)))
    flags: list[str] = []

    if confidence < minimum_confidence:
        family = "unknown"
        canonical = "unknown"
        flags.append("low_classification_confidence")
    elif family not in families or canonical not in families[family]:
        raise ClassificationApplicationError(
            f"{item_id}: {family}/{canonical} is outside the closed taxonomy"
        )

    materials = _string_list(payload.get("materials", []), f"{item_id}.materials")
    conditions = _string_list(payload.get("condition", []), f"{item_id}.condition")
    tags = _string_list(payload.get("tags", []), f"{item_id}.tags")
    if materials_allowed:
        unknown_materials = sorted(set(materials) - materials_allowed)
        if unknown_materials:
            raise ClassificationApplicationError(
                f"{item_id}: materials outside taxonomy: {unknown_materials}"
            )
    if conditions_allowed:
        unknown_conditions = sorted(set(conditions) - conditions_allowed)
        if unknown_conditions:
            raise ClassificationApplicationError(
                f"{item_id}: conditions outside taxonomy: {unknown_conditions}"
            )

    orientation = str(payload.get("orientation", "unknown"))
    size_class = str(payload.get("sizeClass", payload.get("size_class", "unknown")))
    if orientation not in orientations_allowed:
        raise ClassificationApplicationError(f"{item_id}: invalid orientation {orientation}")
    if size_class not in sizes_allowed:
        raise ClassificationApplicationError(f"{item_id}: invalid sizeClass {size_class}")

    normalized = {
        "family": family,
        "canonicalType": canonical,
        "subtype": payload.get("subtype") if isinstance(payload.get("subtype"), str) else None,
        "materials": materials,
        "condition": conditions,
        "orientation": orientation,
        "sizeClass": size_class,
        "tags": tags,
        "confidence": confidence,
        "source": str(payload.get("source", result.get("model", "classification-result"))),
        "notes": str(payload.get("notes", "")),
    }
    return item_id, normalized, flags


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--taxonomy", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--minimum-confidence", type=float, default=0.60)
    parser.add_argument("--require-complete", action="store_true")
    parser.add_argument("--force", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        manifest_path = args.manifest.expanduser().resolve()
        results_path = args.results.expanduser().resolve()
        taxonomy_path = args.taxonomy.expanduser().resolve()
        output = args.out.expanduser().resolve()
        if output.exists() and not args.force:
            raise ClassificationApplicationError("output exists; pass --force to replace it")
        manifest = _read_json(manifest_path)
        taxonomy = _read_json(taxonomy_path)
        if not isinstance(manifest, dict) or manifest.get("kind") != "deterministic-item-atlas":
            raise ClassificationApplicationError("manifest is not a deterministic item atlas")
        if not isinstance(taxonomy, dict):
            raise ClassificationApplicationError("taxonomy must be an object")
        items = manifest.get("items")
        if not isinstance(items, list):
            raise ClassificationApplicationError("manifest items missing")
        by_id = {
            str(item.get("id")): item
            for item in items
            if isinstance(item, Mapping) and isinstance(item.get("id"), str)
        }
        normalized: dict[str, tuple[dict[str, Any], list[str]]] = {}
        for result in _read_results(results_path):
            item_id, payload, flags = _normalize_result(
                result,
                taxonomy,
                minimum_confidence=args.minimum_confidence,
            )
            if item_id not in by_id:
                raise ClassificationApplicationError(f"result references unknown item: {item_id}")
            if item_id in normalized:
                raise ClassificationApplicationError(f"duplicate result for item: {item_id}")
            normalized[item_id] = (payload, flags)
        missing = sorted(set(by_id) - set(normalized))
        if args.require_complete and missing:
            raise ClassificationApplicationError(
                f"classification is incomplete; missing {len(missing)} item(s)"
            )

        successor = deepcopy(manifest)
        successor["parentManifestSha256"] = _digest(manifest_path)
        result_sha = _digest(results_path)
        successor["runId"] = f"{manifest.get('runId', 'item-atlas')}-classified-{result_sha[:8]}"
        successor["classification"] = {
            "taxonomyId": taxonomy.get("id", taxonomy_path.stem),
            "taxonomySha256": _digest(taxonomy_path),
            "resultsSha256": result_sha,
            "minimumConfidence": args.minimum_confidence,
            "appliedCount": len(normalized),
            "missingCount": len(missing),
        }
        for item in successor["items"]:
            item_id = item.get("id")
            if item_id not in normalized:
                continue
            classification, flags = normalized[item_id]
            item["classification"] = classification
            current_flags = item.get("qaFlags") if isinstance(item.get("qaFlags"), list) else []
            item["qaFlags"] = list(dict.fromkeys([*current_flags, *flags]))
        completion = successor.setdefault("completion", {})
        completion["classificationComplete"] = not missing
        completion["reviewComplete"] = False

        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(output.suffix + ".tmp")
        temporary.write_text(
            json.dumps(successor, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(output)
    except ClassificationApplicationError as exc:
        print(json.dumps({"status": "contract-failure", "errors": [str(exc)]}, ensure_ascii=False))
        return 1

    print(
        json.dumps(
            {
                "status": "pass",
                "output": str(output),
                "applied_count": len(normalized),
                "missing_count": len(missing),
                "run_id": successor["runId"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
