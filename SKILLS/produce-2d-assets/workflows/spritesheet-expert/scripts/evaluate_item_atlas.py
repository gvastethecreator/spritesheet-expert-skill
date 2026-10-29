#!/usr/bin/env python3
"""Measure grouped pixels and labels against explicit, hash-bound annotations.

Annotations are external data, not model confidence or an approval shortcut.
Rectangles use source-coordinate [left, top, right, bottom] bounds. A group may
instead supply a binary source-size mask and its SHA-256 for irregular ownership.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw
from spritecore.item_delivery import artifact, digest_file, validate_delivery
from spritecore.item_ownership import source_image, source_masks
from runio import atomic_write_text


def evaluate(annotation_path: Path, manifest_path: Path, *, sample: str | None = None):
    annotations = json.loads(annotation_path.read_text(encoding="utf-8"))
    if sample is not None:
        if annotations.get("schemaVersion") != "item-group-sample-set-v1":
            raise ValueError("--sample requires an item-group sample set")
        matches = [entry for entry in annotations.get("samples", []) if entry.get("id") == sample]
        if len(matches) != 1:
            raise ValueError("unknown or duplicate sample ID")
        annotations = matches[0]
    if annotations.get("schemaVersion") != "item-group-annotations-v1":
        raise ValueError("unsupported annotation contract")
    reviewer = annotations.get("reviewer", {})
    if reviewer.get("kind") not in {"human", "agent"} or not reviewer.get("name"):
        raise ValueError("annotations must identify their reviewer and review kind")
    receipt = validate_delivery(manifest_path, draft=True)
    if receipt["status"] != "pass":
        raise ValueError("invalid run artifacts: " + "; ".join(receipt["integrityErrors"]))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if annotations.get("sourceSha256") != manifest["source"]["sha256"]:
        raise ValueError("annotation source hash mismatch")
    source = source_image(manifest_path.parent, manifest)
    threshold = annotations.get("alphaThreshold", 1)
    if type(threshold) is not int or not 1 <= threshold <= 255:
        raise ValueError("alphaThreshold must be an integer from 1 to 255")
    visible = source.getchannel("A").point(lambda value: 255 if value >= threshold else 0)
    weak = source.getchannel("A").point(lambda value: 255 if 0 < value < 64 else 0)
    all_predictions = source_masks(manifest_path.parent, manifest)
    predictions = {key: ImageChops.multiply(mask, visible) for key, mask in all_predictions.items()}
    records = {item["id"]: item for item in manifest["items"]}
    groups = annotations.get("groups")
    if not isinstance(groups, list) or not 1 <= len(groups) <= 1000:
        raise ValueError("annotations require 1..1000 groups")
    covered, ids, rows, matched_by_prediction = Image.new("L", source.size), set(), [], {}
    for group in groups:
        group_id = group["id"]
        if not isinstance(group_id, str) or not group_id or group_id in ids:
            raise ValueError("duplicate or missing annotation group ID")
        ids.add(group_id)
        if "mask" in group:
            path = artifact(annotation_path.parent, group["mask"]["path"])
            if digest_file(path) != group["mask"]["sha256"]:
                raise ValueError("annotation mask hash mismatch")
            with Image.open(path) as opened:
                if opened.size != source.size or opened.mode != "L" or sum(opened.histogram()[1:255]):
                    raise ValueError("annotation mask must be binary and source-sized")
                mask = opened.copy()
        else:
            mask = Image.new("L", source.size)
            rectangles = group.get("rects", [])
            if not rectangles:
                raise ValueError("annotation group requires rects or a mask")
            for bounds in rectangles:
                if not isinstance(bounds, list) or len(bounds) != 4 or any(type(v) is not int for v in bounds):
                    raise ValueError("annotation rectangles require four integers")
                x, y, right, bottom = bounds
                if not 0 <= x < right <= source.width or not 0 <= y < bottom <= source.height:
                    raise ValueError("annotation rectangle outside source")
                ImageDraw.Draw(mask).rectangle((x, y, right-1, bottom-1), fill=255)
        weak_mask = ImageChops.multiply(mask, weak)
        mask = ImageChops.multiply(mask, visible)
        count = mask.histogram()[255]
        if not count or ImageChops.multiply(mask, covered).getbbox():
            raise ValueError("empty or overlapping annotation groups")
        covered = ImageChops.lighter(covered, mask)
        overlaps = {key: ImageChops.multiply(mask, predicted).histogram()[255] for key, predicted in predictions.items()}
        owners = [key for key, pixels in overlaps.items() if pixels]
        for key in owners:
            matched_by_prediction.setdefault(key, []).append(group_id)
        best = max(owners, key=lambda key: (overlaps[key], key)) if owners else None
        intersection = overlaps.get(best, 0)
        predicted_pixels = predictions[best].histogram()[255] if best else 0
        iou = intersection / (count + predicted_pixels - intersection)
        classification = records[best].get("classification", {}) if best else {}
        expected_label = group.get("classification")
        label_match = (classification.get("family") == expected_label.get("family") and
            classification.get("canonicalType") in expected_label.get("canonicalTypes", [])) if expected_label else None
        weak_count = weak_mask.histogram()[255]
        weak_owned = sum(ImageChops.multiply(weak_mask, prediction).histogram()[255] for prediction in all_predictions.values())
        rows.append({"groupId": group_id, "bestItemId": best, "owners": owners, "iou": round(iou, 6),
            "expectedPixels": count, "assignedPixels": sum(overlaps.values()), "foreignPixels": predicted_pixels-intersection,
            "weakPixels": weak_count, "weakAssignedPixels": weak_owned, "split": len(owners) > 1,
            "labelMatch": label_match, "predictedLabel": classification.get("canonicalType", "unknown"),
            "exactGroup": iou == 1 and len(owners) == 1})
    correction = annotations.get("correctionSeconds")
    if correction is not None and (type(correction) not in {int, float} or not math.isfinite(correction) or correction < 0):
        raise ValueError("correctionSeconds must be measured nonnegative time or null")
    return {"schemaVersion": "item-group-evaluation-v1", "status": "measured", "productionApproval": False,
        "annotationSha256": digest_file(annotation_path), "manifestSha256": receipt["manifestSha256"],
        "sourceSha256": annotations["sourceSha256"], "reviewer": reviewer, "coverage": "annotated-groups-only",
        "sampleId": sample or annotations.get("id"), "alphaThreshold": threshold,
        "pixelPolicy": "IoU uses the declared alpha threshold. Weak-alpha ownership and all pending pixels are reported separately; no production pixels are removed.",
        "correctionSeconds": correction, "metrics": {"groups": len(rows),
            "exactGroups": sum(row["exactGroup"] for row in rows), "splitGroups": sum(row["split"] for row in rows),
            "crossGroupMerges": sum(len(values) > 1 for values in matched_by_prediction.values()),
            "labeledGroups": sum(row["labelMatch"] is not None for row in rows),
            "matchingLabels": sum(row["labelMatch"] is True for row in rows),
            "unknownLabels": sum(row["predictedLabel"] == "unknown" for row in rows),
            "annotatedPixels": covered.histogram()[255], "sourcePixels": visible.histogram()[255],
            "pendingPixels": receipt["metrics"]["pendingPixels"],
            "meanGroupIoU": round(sum(row["iou"] for row in rows)/len(rows), 6)}, "groups": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--annotations", required=True, type=Path)
    parser.add_argument("--sample", help="sample ID when --annotations points to a sample set")
    parser.add_argument("--manifest", required=True, type=Path, action="append")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.out.exists():
            raise ValueError("evaluation output exists; choose a successor filename")
        results = [evaluate(args.annotations.resolve(), path.resolve(), sample=args.sample) for path in args.manifest]
        atomic_write_text(args.out.resolve(), json.dumps({"results": results}, indent=2) + "\n")
        print(json.dumps({"status": "measured", "output": str(args.out.resolve()), "metrics": [r["metrics"] for r in results]}))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(json.dumps({"status": "blocked", "error": str(error)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
