#!/usr/bin/env python3
"""Prepare one model-neutral classification job per extracted item."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping


class ClassificationPreparationError(ValueError):
    pass


def _digest(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ClassificationPreparationError(f"cannot read JSON {path}: {exc}") from exc


def _taxonomy(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {
            "id": "open-taxonomy-review-v1",
            "families": {"unknown": ["unknown"]},
            "materials": [],
            "conditions": [],
            "orientations": ["horizontal", "vertical", "square", "unknown"],
            "sizeClasses": ["XS", "S", "M", "L", "XL", "XXL", "unknown"],
        }
    value = _load_json(path)
    if not isinstance(value, dict) or not isinstance(value.get("families"), dict):
        raise ClassificationPreparationError("taxonomy must contain a families object")
    for family, canonical_types in value["families"].items():
        if not isinstance(family, str) or not family or not isinstance(canonical_types, list):
            raise ClassificationPreparationError("taxonomy families must map strings to arrays")
        if not canonical_types or not all(isinstance(entry, str) and entry for entry in canonical_types):
            raise ClassificationPreparationError("taxonomy canonical types must be non-empty strings")
    for field in ("materials", "conditions", "orientations", "sizeClasses"):
        entries = value.get(field, [])
        if not isinstance(entries, list) or not all(isinstance(entry, str) and entry for entry in entries):
            raise ClassificationPreparationError(f"taxonomy {field} must be an array of non-empty strings")
    return value


def _portable_asset(root: Path, relative: str) -> Path:
    if "\\" in relative or relative.startswith("/") or ".." in Path(relative).parts:
        raise ClassificationPreparationError(f"unsafe artifact path: {relative}")
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ClassificationPreparationError(f"artifact escapes run root: {relative}") from exc
    if not candidate.is_file():
        raise ClassificationPreparationError(f"artifact does not exist: {relative}")
    return candidate


def _job(
    *,
    manifest: Mapping[str, Any],
    manifest_path: Path,
    item: Mapping[str, Any],
    taxonomy: Mapping[str, Any],
) -> dict[str, Any]:
    run_root = manifest_path.parent.resolve()
    artifacts = item.get("artifacts")
    if not isinstance(artifacts, Mapping):
        raise ClassificationPreparationError(f"{item.get('id')}: artifacts missing")
    rgba = _portable_asset(run_root, str(artifacts.get("rgba", "")))
    light = _portable_asset(run_root, str(artifacts.get("lightComposite", "")))
    dark = _portable_asset(run_root, str(artifacts.get("darkComposite", "")))
    item_id = str(item.get("id", ""))
    if not item_id:
        raise ClassificationPreparationError("item id missing")
    rgba_sha = _digest(rgba)
    if artifacts.get("sha256") != rgba_sha:
        raise ClassificationPreparationError(f"{item_id}: RGBA artifact sha256 mismatch")

    allowed_taxonomy = {
        "families": taxonomy.get("families", {}),
        "materials": taxonomy.get("materials", []),
        "conditions": taxonomy.get("conditions", []),
        "orientations": taxonomy.get("orientations", []),
        "sizeClasses": taxonomy.get("sizeClasses", []),
    }
    prompt = (
        "Classify exactly one isolated game-art item. Use only the supplied closed taxonomy. "
        "Do not infer another item from the source sheet and do not invent a category. "
        "Return unknown when evidence is insufficient. Return JSON only with family, "
        "canonicalType, subtype, materials, condition, orientation, sizeClass, tags, "
        "confidence, and notes. materials, condition and tags MUST be arrays of strings, "
        "including for one value. Use [] when none apply. subtype is a string or null. "
        "confidence is a number from 0 to 1. Example shape: "
        '{"family":"unknown","canonicalType":"unknown","subtype":null,'
        '"materials":[],"condition":[],"orientation":"unknown","sizeClass":"unknown",'
        '"tags":[],"confidence":0.1,"notes":"insufficient evidence"}. Allowed taxonomy: '
        + json.dumps(allowed_taxonomy, ensure_ascii=False, separators=(",", ":"))
    )
    return {
        "schemaVersion": "item-classification-job-v1",
        "jobId": f"classify-{item_id}",
        "runId": manifest.get("runId"),
        "itemId": item_id,
        "pathBase": "manifest-directory",
        "sourceManifest": {
            "path": manifest_path.name,
            "sha256": _digest(manifest_path),
        },
        "inputs": {
            "rgba": {
                "path": rgba.relative_to(run_root).as_posix(),
                "sha256": rgba_sha,
            },
            "lightComposite": {
                "path": light.relative_to(run_root).as_posix(),
                "sha256": _digest(light),
            },
            "darkComposite": {
                "path": dark.relative_to(run_root).as_posix(),
                "sha256": _digest(dark),
            },
        },
        "taxonomyId": taxonomy.get("id", "unnamed-taxonomy"),
        "taxonomy": allowed_taxonomy,
        "prompt": prompt,
        "expected": {
            "count": 1,
            "format": "item-classification-result-v1",
            "closedTaxonomy": True,
            "unknownAllowed": True,
        },
        "status": "prepared",
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--taxonomy", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--force", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        manifest_path = args.manifest.expanduser().resolve()
        manifest = _load_json(manifest_path)
        taxonomy_path = args.taxonomy.expanduser().resolve() if args.taxonomy else None
        taxonomy = _taxonomy(taxonomy_path)
        if not isinstance(manifest, dict) or manifest.get("kind") != "deterministic-item-atlas":
            raise ClassificationPreparationError("manifest is not a deterministic item atlas")
        items = manifest.get("items")
        if not isinstance(items, list) or not items:
            raise ClassificationPreparationError("manifest contains no items")
        seen_ids: set[str] = set()
        for item in items:
            if not isinstance(item, Mapping) or not isinstance(item.get("id"), str):
                raise ClassificationPreparationError("every manifest item requires an id")
            if item["id"] in seen_ids:
                raise ClassificationPreparationError(f"duplicate manifest item: {item['id']}")
            seen_ids.add(item["id"])
        output = args.out.expanduser().resolve()
        if output.suffix.lower() != ".jsonl":
            raise ClassificationPreparationError("classification jobs output must use a .jsonl filename")
        if output == manifest_path or (taxonomy_path is not None and output == taxonomy_path):
            raise ClassificationPreparationError("classification jobs cannot replace an input file")
        if output.exists() and not args.force:
            raise ClassificationPreparationError("output exists; pass --force to replace it")
        jobs = [
            _job(
                manifest=manifest,
                manifest_path=manifest_path,
                item=item,
                taxonomy=taxonomy,
            )
            for item in items
        ]
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(output.suffix + ".tmp")
        temporary.write_text(
            "".join(json.dumps(job, ensure_ascii=False) + "\n" for job in jobs),
            encoding="utf-8",
        )
        temporary.replace(output)
    except (ClassificationPreparationError, OSError) as exc:
        print(json.dumps({"status": "operational-error", "errors": [str(exc)]}, ensure_ascii=False))
        return 3

    print(
        json.dumps(
            {
                "status": "pass",
                "job_count": len(jobs),
                "output": str(output),
                "taxonomy_id": taxonomy.get("id"),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
