"""Source-coordinate masks, exact pixel extraction, and editable successors."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from PIL import Image, ImageChops, ImageDraw

from .item_sheet import (ExtractedItem, ItemSheetError, PackingConfig, item_content_sha256,
                         unique_item_id, write_item_atlas_run)
from .item_segmentation import digest_file, load_json, portable_artifact


def source_image(root: Path, manifest: Mapping[str, Any]) -> Image.Image:
    path = portable_artifact(root, manifest["evidence"]["sourceRgba"])
    if digest_file(path) != manifest["evidence"].get("sourceRgbaSha256"):
        raise ItemSheetError("source RGBA hash mismatch")
    with Image.open(path) as opened:
        return opened.convert("RGBA")


def source_masks(root: Path, manifest: Mapping[str, Any]) -> dict[str, Image.Image]:
    size = (manifest["source"]["width"], manifest["source"]["height"])
    masks = {}
    for item in manifest["items"]:
        path = portable_artifact(root, item["artifacts"]["rgba"])
        if digest_file(path) != item["artifacts"]["sha256"]:
            raise ItemSheetError("item artifact hash mismatch")
        with Image.open(path) as opened:
            alpha = opened.convert("RGBA").getchannel("A").point(lambda a: 255 if a else 0)
        mask = Image.new("L", size, 0)
        mask.paste(alpha, tuple(item["source"]["bbox"][:2]))
        masks[item["id"]] = mask
    return masks


def compile_masks(source: Image.Image, masks: Mapping[str, Image.Image], *, alpha_high: int = 64,
                  records: Mapping[str, Mapping[str, Any]] | None = None,
                  flags: Mapping[str, list[str]] | None = None) -> tuple[list[ExtractedItem], dict[str, Any]]:
    """Keep each exclusive mask pixel exactly. Return conflicts to the pending set."""
    visible = source.getchannel("A").point(lambda a: 255 if a else 0)
    if any(mask.size != source.size for mask in masks.values()):
        raise ItemSheetError("mask dimensions must match source")
    normalized = {key: ImageChops.multiply(mask.convert("L").point(lambda a: 255 if a else 0), visible)
                  for key, mask in masks.items()}
    occupied = Image.new("L", source.size, 0)
    conflicts = Image.new("L", source.size, 0)
    for mask in normalized.values():
        if mask.size != source.size:
            raise ItemSheetError("mask dimensions must match source")
        conflicts = ImageChops.lighter(conflicts, ImageChops.multiply(occupied, mask))
        occupied = ImageChops.lighter(occupied, mask)
    items, overrides, used, prepared = [], {}, set(), []
    for key, mask in normalized.items():
        clean = ImageChops.subtract(mask, conflicts)
        bbox = clean.getbbox()
        if not bbox:
            continue
        crop = Image.composite(source.crop(bbox), Image.new("RGBA", (bbox[2]-bbox[0], bbox[3]-bbox[1])), clean.crop(bbox))
        fingerprint = item_content_sha256(crop)
        old = (records or {}).get(key, {})
        prepared.append((key, mask, bbox, crop, fingerprint, old))
        if old.get("contentSha256") == fingerprint:
            used.add(key)
    # Reserve unchanged IDs before assigning new ones. An edited sprite can
    # become pixel-identical to a later, unchanged sprite in source order.
    for key, mask, bbox, crop, fingerprint, old in prepared:
        item_id = key if old.get("contentSha256") == fingerprint else unique_item_id(fingerprint, used)
        used.add(item_id)
        histogram = crop.getchannel("A").histogram()
        assigned = sum(histogram[1:])
        strong = sum(histogram[alpha_high:])
        item_flags = list((flags or {}).get(key, old.get("qaFlags", [])))
        classification_inherited = old.get("classification") is not None and old.get("contentSha256") != fingerprint
        if classification_inherited:
            item_flags.append("changed_sprite_classification_review")
        if ImageChops.multiply(mask, conflicts).getbbox():
            item_flags.append("mask_overlap_review")
        lineage = {"parentItemIds": old.get("parentItemIds", [key]), **old.get("modelEvidence", {})}
        items.append(ExtractedItem(item_id, fingerprint, bbox, crop, strong, assigned, assigned-strong,
                                   list(dict.fromkeys(item_flags)), lineage))
        if old:
            override = deepcopy(dict(old))
            if classification_inherited:
                override["classificationInheritedFrom"] = {"itemId":key, "contentSha256":old.get("contentSha256")}
            override["qaFlags"] = list(dict.fromkeys(item_flags))
            overrides[item_id] = override
    if not items:
        raise ItemSheetError("no nonempty exclusive masks; review the source proposals")
    return items, overrides


def apply_ownership_review(manifest_path: Path, review: Mapping[str, Any], output: Path) -> dict[str, Any]:
    manifest_path = manifest_path.resolve()
    if manifest_path.is_relative_to(output.resolve()):
        raise ItemSheetError("review output cannot contain its parent")
    manifest = load_json(manifest_path)
    if review.get("parentManifestSha256") != digest_file(manifest_path):
        raise ItemSheetError("stale review: parent manifest hash mismatch")
    root = manifest_path.parent
    source = source_image(root, manifest)
    masks = source_masks(root, manifest)
    records = {item["id"]: {**deepcopy(item), "parentItemIds":[item["id"]]} for item in manifest["items"]}
    with Image.open(portable_artifact(root, manifest["evidence"]["discardedMask"])) as opened:
        discarded = opened.convert("L")
    operations = review.get("operations")
    if not isinstance(operations, list) or not operations:
        raise ItemSheetError("review requires operations")
    new_target = None
    for operation in operations:
        kind = operation.get("kind")
        selected = operation.get("itemIds", [])
        if kind in {"merge", "discard", "approve", "tags"}:
            if not selected or any(item_id not in masks for item_id in selected):
                raise ItemSheetError("review refers to an unknown item")
        if kind == "merge":
            target = selected[0]
            for item_id in selected[1:]:
                masks[target] = ImageChops.lighter(masks[target], masks.pop(item_id))
                records.pop(item_id)
            records[target]["parentItemIds"] = selected
            records[target]["review"] = {"status": "pending", "notes": "Merged mask and inherited labels need review", "replacement": None}
        elif kind == "discard":
            for item_id in selected:
                discarded = ImageChops.lighter(discarded, masks.pop(item_id))
                records.pop(item_id)
        elif kind in {"approve", "tags"}:
            for item_id in selected:
                if kind == "approve":
                    records[item_id]["review"] = {"status": "approved", "notes": "Manual review", "replacement": None}
                else:
                    classification = operation.get("classification")
                    if (not isinstance(classification, dict) or set(classification) != {"family", "canonicalType", "tags"}
                        or not all(isinstance(classification.get(k), str) and classification[k].strip() for k in ("family", "canonicalType"))
                        or not isinstance(classification.get("tags"), list)
                        or not all(isinstance(tag, str) and tag.strip() for tag in classification["tags"])):
                        raise ItemSheetError("classification requires family, canonicalType and string tags")
                    records[item_id]["classification"].update(classification)
                    records[item_id]["classification"]["source"] = "human-review"
        elif kind == "paint":
            target = operation.get("target")
            if target not in {"new", "pending", "discard"} and target not in masks:
                raise ItemSheetError("paint target is unknown")
            points = operation.get("points", [])
            radius = operation.get("radius", 3)
            if not isinstance(radius, int) or not 1 <= radius <= 128 or not 1 <= len(points) <= 100000:
                raise ItemSheetError("invalid paint stroke")
            stroke = Image.new("L", source.size, 0)
            draw = ImageDraw.Draw(stroke)
            for point in points:
                if not isinstance(point, list) or len(point) != 2 or not all(isinstance(v, int) for v in point):
                    raise ItemSheetError("paint coordinates must be integer pairs")
                x, y = point
                if not 0 <= x < source.width or not 0 <= y < source.height:
                    raise ItemSheetError("paint coordinates outside source")
                draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill=255)
            for item_id in masks:
                if ImageChops.multiply(masks[item_id], stroke).getbbox() and item_id in records:
                    records[item_id]["review"] = {"status": "pending", "notes": "Mask changed", "replacement": None}
                    records[item_id]["qaFlags"] = list(set(records[item_id].get("qaFlags", []) + ["edited_mask_review"]))
                masks[item_id] = ImageChops.subtract(masks[item_id], stroke)
            discarded = ImageChops.subtract(discarded, stroke)
            if target == "new":
                if new_target is None:
                    new_target = f"new-{len(masks)}"
                    masks[new_target] = Image.new("L", source.size, 0)
                    records[new_target] = {"parentItemIds": [], "qaFlags": ["edited_mask_review"]}
                target = new_target
            elif target in records:
                records[target]["review"] = {"status": "pending", "notes": "Mask changed", "replacement": None}
                records[target]["qaFlags"] = list(set(records[target].get("qaFlags", []) + ["edited_mask_review"]))
            if target == "discard":
                discarded = ImageChops.lighter(discarded, stroke)
            elif target != "pending":
                masks[target] = ImageChops.lighter(masks[target], stroke)
        else:
            raise ItemSheetError(f"unsupported review operation: {kind}")
    items, overrides = compile_masks(source, masks, records=records)
    pack = manifest["packing"]
    successor = write_item_atlas_run(items, output, source=manifest["source"], source_reference=source,
        segmentation=manifest["segmentation"], packing=PackingConfig(**{key: pack[key] for key in ("quantum", "padding", "max_width", "outer_padding")}),
        parent_manifest_sha256=digest_file(manifest_path), item_overrides=overrides, discarded_mask=discarded,
        completion={"classificationComplete": manifest["completion"].get("classificationComplete", False)},
        manifest_extra={"ownershipReview": dict(review)})
    return successor
