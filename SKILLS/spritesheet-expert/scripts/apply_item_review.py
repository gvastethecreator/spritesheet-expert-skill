#!/usr/bin/env python3
"""Apply a hash-bound review using the shared atlas and ownership writer."""
from __future__ import annotations

import argparse
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path

from PIL import Image, ImageChops
from jsonschema import Draft202012Validator
from spritecore.item_delivery import artifact, validate_delivery
from spritecore.item_ownership import source_image, source_masks, compile_masks
from spritecore.item_review import SCOPES, reconcile_review
from spritecore.item_segmentation import digest_file
from spritecore.item_sheet import ItemSheetError, PackingConfig, write_item_atlas_run


def apply_review(manifest_path, review_path, output, *, allow_pending=False, force=False):
    if Path(output).is_symlink():
        raise ItemSheetError("output directory cannot be a symbolic link")
    manifest_path, review_path, output = (Path(p).resolve() for p in (manifest_path, review_path, output))
    if output == Path(output.anchor) or any(p.is_relative_to(output) for p in (manifest_path, review_path)):
        raise ItemSheetError("output directory cannot contain an input file")
    receipt = validate_delivery(manifest_path, draft=True)
    if receipt["integrityErrors"]:
        raise ItemSheetError("invalid parent: " + "; ".join(receipt["integrityErrors"]))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    review = json.loads(review_path.read_text(encoding="utf-8"))
    schema = json.loads((Path(__file__).resolve().parents[1] / "references/schemas/item-review-v1.schema.json").read_text(encoding="utf-8"))
    classification_validator = Draft202012Validator(schema["$defs"]["classificationOverride"])
    if review.get("schemaVersion") != "item-review-v1" or review.get("kind") != "deterministic-item-review":
        raise ItemSheetError("review is not an item-review-v1 document")
    if review.get("runId") != manifest["runId"]:
        raise ItemSheetError("review runId does not match the manifest")
    if review.get("sourceManifest", {}).get("sha256") != receipt["manifestSha256"]:
        raise ItemSheetError("review sourceManifest.sha256 does not match the manifest")
    entries = review.get("items")
    if not isinstance(entries, list):
        raise ItemSheetError("review requires an items array")
    decisions = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("itemId"), str):
            raise ItemSheetError("review item requires itemId")
        if entry["itemId"] in decisions:
            raise ItemSheetError("duplicate review item")
        if entry.get("status") not in {"pending", "approved", "rejected", "replace", "regenerate"}:
            raise ItemSheetError("invalid review status")
        decisions[entry["itemId"]] = entry
    records = {item["id"]: deepcopy(item) for item in manifest["items"]}
    if set(decisions) - records.keys():
        raise ItemSheetError("review references unknown items")
    root = manifest_path.parent
    original_source = source_image(root, manifest)
    masks = source_masks(root, manifest)
    with Image.open(artifact(root, manifest["evidence"]["discardedMask"])) as opened:
        discarded = opened.copy()
    replacements, attachments = {}, {"review/item-review.json": review_path}
    rejected = []
    for item_id, record in records.items():
        decision = decisions.get(item_id, {"status": "pending"})
        status = decision["status"]
        if status == "pending" and not allow_pending:
            raise ItemSheetError(f"review has unresolved items: {item_id}")
        if status == "rejected":
            rejected.append(item_id)
            continue
        if status in {"replace", "regenerate"}:
            replacement = decision.get("replacement")
            if not isinstance(replacement, dict):
                raise ItemSheetError(f"review has unresolved items: {item_id}")
            path = artifact(review_path.parent, replacement.get("path"))
            if digest_file(path) != replacement.get("sha256"):
                raise ItemSheetError(f"{item_id}: replacement sha256 mismatch")
            if replacement.get("provenance") not in {"imagegen", "grok-imagine-image", "imported", "fixture"}:
                raise ItemSheetError(f"{item_id}: invalid replacement provenance")
            with Image.open(path) as opened:
                if opened.width * opened.height > 50_000_000 or getattr(opened, "n_frames", 1) != 1:
                    raise ItemSheetError("replacement exceeds image budget or is animated")
                image = opened.convert("RGBA")
            if image.getchannel("A").getbbox() is None:
                raise ItemSheetError(f"{item_id}: selected image is fully transparent")
            replacements[item_id] = image
            relative = f"review/replacements/{item_id}.png"
            attachments[relative] = path
            record["review"] = {"status": "pending", "notes": "Replacement requires fresh pixel, label and placement review",
                "replacement": {**replacement, "sourcePath": relative}}
            record["qaFlags"] = [*record.get("qaFlags", []), "replacement_imported"]
        else:
            record["review"] = {**record.get("review", {}), "status": status, "notes": str(decision.get("notes", "")), "replacement": None}
        classification = decision.get("classification")
        if classification is not None:
            errors = list(classification_validator.iter_errors(classification))
            if errors:
                raise ItemSheetError("invalid classification override: " + errors[0].message)
            record["classification"].update(classification)
        # Approve the view the reviewer saw, not a later repacked placement.
        record["review"] = reconcile_review(record, manifest["source"]["sha256"], record["review"],
            approve=SCOPES if status == "approved" else ())

    for item_id in [*rejected, *replacements]:
        discarded = ImageChops.lighter(discarded, masks.pop(item_id))
    for item_id in rejected:
        records.pop(item_id)
    source, source_record = original_source, deepcopy(manifest["source"])
    if replacements:
        # Append new source inputs. Preserve original coordinates and explicitly
        # discard replaced pixels; never pretend the new art came from them.
        width = max(original_source.width, max(im.width + 2 for im in replacements.values()))
        height = original_source.height + sum(im.height + 2 for im in replacements.values())
        if width * height > 50_000_000:
            raise ItemSheetError("replacement source exceeds aggregate pixel budget")
        source = Image.new("RGBA", (width, height))
        source.paste(original_source, (0, 0))
        new_discarded = Image.new("L", source.size)
        new_discarded.paste(discarded, (0, 0)); discarded = new_discarded
        for item_id, mask in list(masks.items()):
            expanded = Image.new("L", source.size); expanded.paste(mask, (0, 0)); masks[item_id] = expanded
        y = original_source.height + 1
        for item_id, image in replacements.items():
            source.paste(image, (1, y))
            mask = Image.new("L", source.size)
            mask.paste(image.getchannel("A").point(lambda a: 255 if a else 0), (1, y))
            masks[item_id] = mask
            records[item_id]["parentItemIds"] = [item_id]
            y += image.height + 2
        encoded = BytesIO(); source.save(encoded, format="PNG")
        source_record = {"path": "source.png", "sha256": sha256(encoded.getvalue()).hexdigest(),
            "width": width, "height": height, "mode": "RGBA",
            "provenance": "fixture" if manifest["source"]["provenance"] == "fixture" or any(decisions[key]["replacement"]["provenance"] == "fixture" for key in replacements) else "mixed",
            "parentSourceSha256": manifest["source"]["sha256"]}
        attachments["review/parent-source.png"] = artifact(root, manifest["evidence"]["sourceRgba"])
    items, overrides = compile_masks(source, masks, records=records)
    return write_item_atlas_run(items, output, source=source_record, source_reference=source,
        segmentation=manifest["segmentation"], packing=PackingConfig.from_metadata(manifest["packing"]),
        parent_manifest_sha256=receipt["manifestSha256"], item_overrides=overrides, discarded_mask=discarded,
        completion={"classificationComplete": manifest["completion"].get("classificationComplete", False)},
        manifest_extra={"reviewApplication": {"reviewPath": "review/item-review.json", "reviewSha256": digest_file(review_path),
            "rejectedItemIds": rejected, "replacementParentIds": list(replacements),
            "replacementCount": len(replacements),
            "parentSourceRgbaSha256": manifest["evidence"]["sourceRgbaSha256"]}},
        attachments=attachments, force=force)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--allow-pending", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    try:
        result = apply_review(args.manifest, args.review, args.output_dir, allow_pending=args.allow_pending, force=args.force)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "contract-failure", "errors": [str(exc)]}))
        return 1
    print(json.dumps({"status": "pass", "run_id": result["runId"], "item_count": len(result["items"]),
        "manifest": str(args.output_dir.resolve() / "manifest.json"), "atlas": str(args.output_dir.resolve() / "atlas.png")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
