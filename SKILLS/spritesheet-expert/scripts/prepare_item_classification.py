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

    families = taxonomy.get("families", {})
    prompt = (
        "Classify exactly one isolated game-art item. Use only the supplied closed taxonomy. "
        "Do not infer another item from the source sheet and do not invent a category. "
        "Return unknown when evidence is insufficient. Return JSON only with family, "
        "canonicalType, subtype, materials, condition, orientation, sizeClass, tags, "
        "confidence, and notes. Allowed families and canonical types: "
        + json.dumps(families, ensure_ascii=False, separators=(",", ":"))
    )
    return {
        "schemaVersion": "item-classification-job-v1",
        "jobId": f"classify-{item_id}",
        "runId": manifest.get("runId"),
        "itemId": item_id,
        "inputs": {
            "rgba": {
                "path": rgba.relative_to(run_root).as_posix(),
                "sha256": _digest(rgba),
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
        taxonomy = _taxonomy(args.taxonomy.expanduser().resolve() if args.taxonomy else None)
        if not isinstance(manifest, dict) or manifest.get("kind") != "deterministic-item-atlas":
            raise ClassificationPreparationError("manifest is not a deterministic item atlas")
        items = manifest.get("items")
        if not isinstance(items, list) or not items:
            raise ClassificationPreparationError("manifest contains no items")
        output = args.out.expanduser().resolve()
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
            if isinstance(item, Mapping)
        ]
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(output.suffix + ".tmp")
        temporary.write_text(
            "".join(json.dumps(job, ensure_ascii=False) + "\n" for job in jobs),
            encoding="utf-8",
        )
        temporary.replace(output)
    except ClassificationPreparationError as exc:
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
