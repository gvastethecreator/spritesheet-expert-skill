#!/usr/bin/env python3
"""Apply item approvals/rejections/replacements and rebuild an immutable atlas."""

from __future__ import annotations

import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import shutil
from typing import Any, Mapping

from PIL import Image

from spritecore.item_sheet import (
    ExtractedItem,
    ItemSheetError,
    PackingConfig,
    compose_atlas,
    pack_items,
    validate_manifest_geometry,
)


class ReviewApplicationError(ValueError):
    pass


_ALLOWED_STATES = {"pending", "approved", "rejected", "replace", "regenerate"}


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReviewApplicationError(f"cannot read JSON {path}: {exc}") from exc


def _digest(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_path(root: Path, relative: str, *, label: str) -> Path:
    if not relative or "\\" in relative or relative.startswith("/") or ".." in Path(relative).parts:
        raise ReviewApplicationError(f"unsafe {label} path: {relative}")
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ReviewApplicationError(f"{label} escapes its root: {relative}") from exc
    if not candidate.is_file():
        raise ReviewApplicationError(f"{label} does not exist: {relative}")
    return candidate


def _content_fingerprint(image: Image.Image) -> str:
    rgba = image.convert("RGBA")
    return sha256(
        rgba.width.to_bytes(4, "big")
        + rgba.height.to_bytes(4, "big")
        + rgba.tobytes()
    ).hexdigest()


def _review_map(review: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    entries = review.get("items")
    if not isinstance(entries, list):
        raise ReviewApplicationError("review requires an items array")
    result: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ReviewApplicationError("review item must be an object")
        item_id = entry.get("itemId", entry.get("id"))
        status = entry.get("status")
        if not isinstance(item_id, str) or not item_id:
            raise ReviewApplicationError("review item requires itemId")
        if status not in _ALLOWED_STATES:
            raise ReviewApplicationError(f"{item_id}: invalid review status {status!r}")
        if item_id in result:
            raise ReviewApplicationError(f"duplicate review item: {item_id}")
        result[item_id] = entry
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--allow-pending", action="store_true")
    parser.add_argument("--force", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        manifest_path = args.manifest.expanduser().resolve()
        review_path = args.review.expanduser().resolve()
        output = args.output_dir.expanduser().resolve()
        if output.exists() and any(output.iterdir()) and not args.force:
            raise ReviewApplicationError("output directory is not empty; pass --force")
        manifest = _read_json(manifest_path)
        review = _read_json(review_path)
        if not isinstance(manifest, dict) or manifest.get("kind") != "deterministic-item-atlas":
            raise ReviewApplicationError("manifest is not a deterministic item atlas")
        if not isinstance(review, dict):
            raise ReviewApplicationError("review must be an object")
        expected_run = review.get("runId")
        if expected_run is not None and expected_run != manifest.get("runId"):
            raise ReviewApplicationError("review runId does not match the manifest")
        decisions = _review_map(review)
        source_items = manifest.get("items")
        if not isinstance(source_items, list):
            raise ReviewApplicationError("manifest items missing")
        source_by_id = {
            str(item.get("id")): item
            for item in source_items
            if isinstance(item, Mapping) and isinstance(item.get("id"), str)
        }
        unknown = sorted(set(decisions) - set(source_by_id))
        if unknown:
            raise ReviewApplicationError(f"review references unknown items: {unknown}")

        output.mkdir(parents=True, exist_ok=True)
        output_items = output / "items"
        output_qa = output / "qa"
        output_review = output / "review"
        output_items.mkdir(parents=True, exist_ok=True)
        output_qa.mkdir(parents=True, exist_ok=True)
        output_review.mkdir(parents=True, exist_ok=True)

        manifest_root = manifest_path.parent
        review_root = review_path.parent
        extracted: list[ExtractedItem] = []
        records: list[dict[str, Any]] = []
        unresolved: list[str] = []

        for original in source_items:
            if not isinstance(original, dict):
                continue
            item_id = str(original.get("id"))
            decision = decisions.get(item_id, {"status": "pending"})
            status = decision["status"]
            if status == "rejected":
                continue
            if status == "regenerate":
                replacement = decision.get("replacement")
                if not isinstance(replacement, Mapping) or not replacement.get("path"):
                    unresolved.append(item_id)
                    continue
                status = "replace"

            source_artifacts = original.get("artifacts")
            if not isinstance(source_artifacts, Mapping):
                raise ReviewApplicationError(f"{item_id}: source artifacts missing")
            source_path = _safe_path(
                manifest_root,
                str(source_artifacts.get("rgba", "")),
                label=f"{item_id} source",
            )
            replacement_record: dict[str, Any] | None = None
            selected_path = source_path
            if status == "replace":
                replacement = decision.get("replacement")
                if not isinstance(replacement, Mapping):
                    raise ReviewApplicationError(f"{item_id}: replacement object missing")
                selected_path = _safe_path(
                    review_root,
                    str(replacement.get("path", "")),
                    label=f"{item_id} replacement",
                )
                expected_sha = replacement.get("sha256")
                actual_sha = _digest(selected_path)
                if expected_sha is not None and expected_sha != actual_sha:
                    raise ReviewApplicationError(f"{item_id}: replacement sha256 mismatch")
                replacement_record = {
                    "sourcePath": selected_path.name,
                    "sha256": actual_sha,
                    "provenance": replacement.get("provenance", "imported"),
                    "jobId": replacement.get("jobId"),
                }
            elif status == "pending" and not args.allow_pending:
                unresolved.append(item_id)
                continue

            try:
                with Image.open(selected_path) as opened:
                    opened.load()
                    image = opened.convert("RGBA")
            except OSError as exc:
                raise ReviewApplicationError(f"{item_id}: cannot decode selected image") from exc
            if image.getbbox() is None:
                raise ReviewApplicationError(f"{item_id}: selected image is fully transparent")

            fingerprint = _content_fingerprint(image)
            out_name = f"items/{item_id}.png"
            image.save(output / out_name)
            source_meta = original.get("source") if isinstance(original.get("source"), Mapping) else {}
            extracted.append(
                ExtractedItem(
                    item_id=item_id,
                    content_sha256=fingerprint,
                    source_bbox=tuple(source_meta.get("bbox", [0, 0, image.width, image.height])),
                    image=image,
                    strong_pixels=int(source_meta.get("strongPixels", 0)),
                    assigned_pixels=int(source_meta.get("assignedPixels", 0)),
                    weak_pixels=int(source_meta.get("weakPixels", 0)),
                    qa_flags=list(original.get("qaFlags", [])),
                )
            )
            record = deepcopy(original)
            record["contentSha256"] = fingerprint
            record.setdefault("artifacts", {})["rgba"] = out_name
            record["artifacts"]["sha256"] = _digest(output / out_name)
            record["review"] = {
                "status": "approved" if status in {"approved", "replace"} else status,
                "notes": str(decision.get("notes", "")),
                "replacement": replacement_record,
            }
            if replacement_record:
                record["qaFlags"] = list(
                    dict.fromkeys([*record.get("qaFlags", []), "replacement_imported"])
                )
            overrides = decision.get("classification")
            if isinstance(overrides, Mapping):
                merged = dict(record.get("classification", {}))
                merged.update(overrides)
                record["classification"] = merged
            records.append(record)

        if unresolved:
            raise ReviewApplicationError(
                "review has unresolved items: " + ", ".join(sorted(unresolved))
            )
        if not extracted:
            raise ReviewApplicationError("review removed every item")

        packing_meta = manifest.get("packing") if isinstance(manifest.get("packing"), Mapping) else {}
        packing = PackingConfig(
            quantum=int(packing_meta.get("quantum", 32)),
            padding=int(packing_meta.get("padding", 16)),
            max_width=int(packing_meta.get("max_width", packing_meta.get("maxWidth", 4096))),
            outer_padding=int(packing_meta.get("outer_padding", packing_meta.get("outerPadding", 0))),
            extrude=int(packing_meta.get("extrude", 0)),
        )
        placements, atlas_size, _footprints = pack_items(extracted, packing)
        atlas, debug, frames = compose_atlas(extracted, placements, atlas_size, packing)
        atlas_path = output / "atlas.png"
        debug_path = output_qa / "atlas-grid.png"
        atlas.save(atlas_path)
        debug.save(debug_path)

        record_by_id = {record["id"]: record for record in records}
        for item in extracted:
            record = record_by_id[item.item_id]
            cell = placements[item.item_id]
            frame = frames[item.item_id]
            record["geometry"] = {
                "originalSize": [item.width, item.height],
                "cellRect": [cell.x, cell.y, cell.w, cell.h],
                "frame": [frame["x"], frame["y"], frame["w"], frame["h"]],
                "pivot": record.get("geometry", {}).get("pivot", [0.5, 0.5]),
                "scale": 1,
                "rotated": False,
            }

        review_sha = _digest(review_path)
        successor = deepcopy(manifest)
        successor["parentManifestSha256"] = _digest(manifest_path)
        successor["runId"] = f"{manifest.get('runId', 'item-atlas')}-review-{review_sha[:8]}"
        successor["items"] = records
        successor["atlas"] = {
            "path": "atlas.png",
            "width": atlas.width,
            "height": atlas.height,
            "sha256": _digest(atlas_path),
        }
        successor["reviewApplication"] = {
            "reviewPath": f"review/{review_path.name}",
            "reviewSha256": review_sha,
            "approvedCount": sum(record["review"]["status"] == "approved" for record in records),
            "rejectedCount": len(source_items) - len(records),
            "replacementCount": sum(record["review"]["replacement"] is not None for record in records),
        }
        successor.setdefault("evidence", {})["atlasGrid"] = "qa/atlas-grid.png"
        successor.setdefault("completion", {})["reviewComplete"] = all(
            record["review"]["status"] == "approved" for record in records
        )
        shutil.copy2(review_path, output_review / review_path.name)

        errors = validate_manifest_geometry(successor)
        if errors:
            raise ReviewApplicationError("rebuilt geometry failed: " + "; ".join(errors))
        manifest_out = output / "manifest.json"
        manifest_out.write_text(
            json.dumps(successor, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except (ReviewApplicationError, ItemSheetError) as exc:
        print(json.dumps({"status": "contract-failure", "errors": [str(exc)]}, ensure_ascii=False))
        return 1

    print(
        json.dumps(
            {
                "status": "pass",
                "run_id": successor["runId"],
                "item_count": len(successor["items"]),
                "manifest": str(manifest_out),
                "atlas": str(atlas_path),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
