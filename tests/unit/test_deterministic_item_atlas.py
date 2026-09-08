from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator
from PIL import Image, ImageDraw
import pytest

from spritecore.item_sheet import (
    ExtractedItem,
    ItemSheetError,
    PackingConfig,
    SegmentationConfig,
    build_item_atlas,
    pack_items,
    segment_items,
    validate_manifest_geometry,
    build_pixel_ownership_report,
    item_content_sha256,
    write_item_atlas_run,
)
from spritecore.item_ownership import compile_masks, apply_ownership_review
from spritecore.item_segmentation import digest_file


REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_ROOT = REPO_ROOT / "SKILLS" / "spritesheet-expert" / "references" / "schemas"


def _sheet() -> Image.Image:
    image = Image.new("RGBA", (128, 96), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 10, 34, 42), fill=(190, 55, 40, 255))
    draw.rectangle((82, 8, 118, 28), fill=(70, 135, 200, 255))
    draw.rectangle((50, 58, 72, 86), fill=(205, 170, 70, 255))
    # Low-alpha antialias-like pixels close to the first object.
    draw.line((35, 17, 38, 17), fill=(190, 55, 40, 14), width=1)
    draw.point((7, 18), fill=(190, 55, 40, 8))
    return image


def _intersects(left: tuple[int, int, int, int], right: tuple[int, int, int, int]) -> bool:
    lx, ly, lw, lh = left
    rx, ry, rw, rh = right
    return not (
        lx + lw <= rx
        or rx + rw <= lx
        or ly + lh <= ry
        or ry + rh <= ly
    )


def test_alpha_hysteresis_extracts_independent_native_size_items() -> None:
    items = segment_items(
        _sheet(),
        SegmentationConfig(
            alpha_high=64,
            alpha_low=2,
            halo_radius=6,
            min_strong_pixels=8,
        ),
    )

    assert len(items) == 3
    assert all(item.image.mode == "RGBA" for item in items)
    assert all(item.image.getbbox() is not None for item in items)
    assert max(item.width for item in items) < _sheet().width
    assert any(item.weak_pixels > 0 for item in items)


def test_faint_bridge_beyond_halo_does_not_merge_two_objects() -> None:
    image = Image.new("RGBA", (96, 40), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((5, 8, 20, 30), fill=(255, 100, 50, 255))
    draw.rectangle((75, 8, 90, 30), fill=(50, 120, 255, 255))
    draw.line((21, 19, 74, 19), fill=(255, 255, 255, 3), width=1)

    items = segment_items(
        image,
        SegmentationConfig(alpha_high=64, alpha_low=2, halo_radius=5, min_strong_pixels=8),
    )

    assert len(items) == 2
    assert all(item.width < 32 for item in items)


def test_segmentation_rejects_fully_transparent_pixels_as_weak_alpha() -> None:
    with pytest.raises(ItemSheetError, match="alpha_low must be between 1"):
        SegmentationConfig(alpha_low=0).validate()


def test_item_ids_are_stable_for_identical_source_bytes() -> None:
    first = segment_items(_sheet())
    second = segment_items(_sheet())

    assert [item.item_id for item in first] == [item.item_id for item in second]
    assert [item.content_sha256 for item in first] == [item.content_sha256 for item in second]


def test_duplicate_content_gets_a_deterministic_occurrence_suffix() -> None:
    image = Image.new("RGBA", (70, 30), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((5, 5, 19, 19), fill=(210, 80, 40, 255))
    draw.rectangle((45, 5, 59, 19), fill=(210, 80, 40, 255))

    items = segment_items(image, SegmentationConfig(min_strong_pixels=4))

    assert len(items) == 2
    assert items[0].content_sha256 == items[1].content_sha256
    assert items[1].item_id == f"{items[0].item_id}_02"


def test_rectangular_packing_is_quantized_non_overlapping_and_repeatable() -> None:
    items = segment_items(_sheet())
    config = PackingConfig(quantum=16, padding=8, max_width=256)

    first, first_size, footprints = pack_items(items, config)
    second, second_size, _ = pack_items(items, config)

    assert first == second
    assert first_size == second_size
    assert first_size[0] % 16 == 0
    assert first_size[1] % 16 == 0

    rectangles = []
    for item in items:
        rect = first[item.item_id]
        footprint = footprints[item.item_id]
        assert rect.w == footprint[0]
        assert rect.h == footprint[1]
        assert rect.w % 16 == 0
        assert rect.h % 16 == 0
        assert rect.w >= item.width + 16
        assert rect.h >= item.height + 16
        rectangles.append((rect.x, rect.y, rect.w, rect.h))

    for index, left in enumerate(rectangles):
        for right in rectangles[index + 1 :]:
            assert not _intersects(left, right)


def test_packing_respects_max_width_after_outer_padding() -> None:
    items = segment_items(_sheet())

    _placements, atlas_size, _footprints = pack_items(
        items,
        PackingConfig(quantum=16, padding=8, max_width=127, outer_padding=7),
    )

    assert atlas_size[0] <= 127


def test_build_item_atlas_preserves_native_dimensions_and_writes_evidence(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    output = tmp_path / "run"
    _sheet().save(source)

    manifest = build_item_atlas(
        source,
        output,
        segmentation=SegmentationConfig(alpha_high=64, alpha_low=2, halo_radius=6),
        packing=PackingConfig(quantum=16, padding=8, max_width=256),
        provenance="fixture",
    )

    assert manifest["kind"] == "deterministic-item-atlas"
    assert manifest["segmentation"]["itemCount"] == 3
    assert manifest["packing"]["rotation"] is False
    assert manifest["packing"]["rescale"] is False
    assert manifest["source"]["provenance"] == "fixture"
    manifest_schema = json.loads(
        (SCHEMA_ROOT / "deterministic-item-sheet-v1.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator(manifest_schema).validate(manifest)
    assert validate_manifest_geometry(manifest) == []
    assert (output / "manifest.json").is_file()
    assert (output / "atlas.png").is_file()
    assert (output / "qa/source-components.png").is_file()
    assert (output / "qa/atlas-grid.png").is_file()

    for record in manifest["items"]:
        item_path = output / record["artifacts"]["rgba"]
        assert item_path.is_file()
        with Image.open(item_path) as item_image:
            assert list(item_image.size) == record["geometry"]["originalSize"]
        assert record["geometry"]["scale"] == 1
        assert record["geometry"]["rotated"] is False
        cell_x, cell_y, cell_w, cell_h = record["geometry"]["cellRect"]
        frame_x, frame_y, frame_w, frame_h = record["geometry"]["frame"]
        assert cell_x <= frame_x
        assert cell_y <= frame_y
        assert frame_x + frame_w <= cell_x + cell_w
        assert frame_y + frame_h <= cell_y + cell_h
        with Image.open(output / "atlas.png") as atlas_image, Image.open(item_path) as native_image:
            assert atlas_image.crop((frame_x,frame_y,frame_x+frame_w,frame_y+frame_h)).tobytes() == native_image.tobytes()


def test_build_item_atlas_force_replaces_the_complete_output(tmp_path: Path) -> None:
    first_source = tmp_path / "first.png"
    second_source = tmp_path / "second.png"
    output = tmp_path / "run"
    _sheet().save(first_source)
    second = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
    ImageDraw.Draw(second).rectangle((8, 9, 30, 32), fill=(90, 150, 210, 255))
    second.save(second_source)

    build_item_atlas(first_source, output, provenance="fixture")
    (output / "stale.txt").write_text("obsolete", encoding="utf-8")
    manifest = build_item_atlas(second_source, output, provenance="fixture", force=True)

    assert len(manifest["items"]) == 1
    assert not (output / "stale.txt").exists()
    assert {path.name for path in (output / "items").glob("*.png")} == {
        Path(manifest["items"][0]["artifacts"]["rgba"]).name
    }


def test_build_item_atlas_rejects_an_output_that_contains_its_source(tmp_path: Path) -> None:
    output = tmp_path / "run"
    output.mkdir()
    source = output / "source.png"
    _sheet().save(source)

    with pytest.raises(ItemSheetError, match="cannot contain the source image"):
        build_item_atlas(source, output, provenance="fixture", force=True)

    assert source.is_file()


def test_geometry_validator_rejects_scale_rotation_and_overlap() -> None:
    manifest = {
        "atlas": {"width": 64, "height": 64},
        "items": [
            {
                "id": "item_a",
                "geometry": {
                    "cellRect": [0, 0, 32, 32],
                    "frame": [2, 2, 20, 20],
                    "scale": 2,
                    "rotated": False,
                },
            },
            {
                "id": "item_b",
                "geometry": {
                    "cellRect": [16, 16, 32, 32],
                    "frame": [20, 20, 20, 20],
                    "scale": 1,
                    "rotated": True,
                },
            },
        ],
    }

    errors = validate_manifest_geometry(manifest)

    assert any("scale must remain 1" in error for error in errors)
    assert any("rotation must remain disabled" in error for error in errors)
    assert any("overlaps" in error for error in errors)


def test_new_studio_schemas_and_registry_validate() -> None:
    schema_names = [
        "deterministic-item-sheet-v1.schema.json",
        "item-classification-v1.schema.json",
        "item-review-v1.schema.json",
        "studio-workflow-v1.schema.json",
        "studio-session-v1.schema.json",
    ]
    schemas = {
        name: json.loads((SCHEMA_ROOT / name).read_text(encoding="utf-8"))
        for name in schema_names
    }
    for schema in schemas.values():
        Draft202012Validator.check_schema(schema)

    registry = json.loads((REPO_ROOT / "SKILLS" / "spritesheet-expert" / "studio" / "workflows.json").read_text(encoding="utf-8"))
    Draft202012Validator(schemas["studio-workflow-v1.schema.json"]).validate(registry)


def test_masks_split_touching_pixels_join_fragments_and_preserve_exact_rgba() -> None:
    source = Image.new("RGBA", (12, 4))
    draw = ImageDraw.Draw(source)
    draw.rectangle((0, 0, 6, 1), fill=(123, 17, 63, 127))
    draw.point((10, 3), fill=(11, 22, 33, 1))
    left, right = Image.new("L", source.size), Image.new("L", source.size)
    ImageDraw.Draw(left).rectangle((0, 0, 2, 1), fill=255)
    ImageDraw.Draw(left).point((10, 3), fill=255)  # Detached accessory belongs to left group.
    ImageDraw.Draw(right).rectangle((3, 0, 6, 1), fill=255)
    items, _ = compile_masks(source, {"left": left, "right": right})
    assert len(items) == 2
    report = build_pixel_ownership_report(source, items)
    assert report["ownedPixels"] == 15
    assert report["rgbaMismatchPixels"] == report["duplicateOwnershipPixels"] == report["unownedSourceAlphaPixels"] == 0
    assert items[0].image.getpixel((10, 3)) == (11, 22, 33, 1)

    ImageDraw.Draw(right).point((2, 0), fill=255)
    conflicts, _ = compile_masks(source, {"left": left, "right": right})
    audit = build_pixel_ownership_report(source, conflicts)
    assert audit["duplicateOwnershipPixels"] == 0
    assert audit["unownedSourceAlphaPixels"] == 1
    assert all("mask_overlap_review" in item.qa_flags for item in conflicts)
    with pytest.raises(ItemSheetError, match="dimensions"):
        compile_masks(source, {"wrong": Image.new("L", (1, 1))})


def test_shelves_keep_visual_size_order_and_native_padding() -> None:
    items = segment_items(_sheet())
    config = PackingConfig(quantum=16, padding=8)
    placed, _size, footprints = pack_items(items, config)
    expected = sorted(items, key=lambda item: (
        -footprints[item.item_id][0]*footprints[item.item_id][1],
        -max(footprints[item.item_id]), -footprints[item.item_id][1], item.item_id))
    visual = sorted(items, key=lambda item: (placed[item.item_id].y, placed[item.item_id].x))
    assert [item.item_id for item in visual] == [item.item_id for item in expected]
    for item in items:
        w,h = footprints[item.item_id]
        assert w-item.width >= 16 and h-item.height >= 16


def test_edited_mask_cannot_steal_an_unchanged_sprites_id() -> None:
    source = Image.new("RGBA", (3,1), (1,2,3,255))
    changed, kept = Image.new("L", source.size), Image.new("L", source.size)
    changed.putpixel((0,0),255)
    kept.putpixel((2,0),255)
    fingerprint = item_content_sha256(source.crop((0,0,1,1)))
    stable = "item_" + fingerprint[:12]
    items, _ = compile_masks(source, {"changed":changed, stable:kept},
                             records={stable:{"contentSha256":fingerprint}})
    assert len({item.item_id for item in items}) == 2
    assert items[1].item_id == stable


def test_mask_review_preserves_parent_tags_and_records_successor(tmp_path: Path) -> None:
    source, root = tmp_path / "source.png", tmp_path / "parent"
    _sheet().save(source)
    parent = build_item_atlas(source, root, provenance="fixture")
    ids = [item["id"] for item in parent["items"]]
    parent["items"][2]["parentItemIds"] = ["older-source-group"]
    parent["items"][2]["modelEvidence"] = {"model":"fixture-model", "revision":"pinned-revision"}
    (root / "manifest.json").write_text(json.dumps(parent))
    parent_bytes = (root / "manifest.json").read_bytes()
    successor = apply_ownership_review(root / "manifest.json", {
        "parentManifestSha256": digest_file(root / "manifest.json"),
        "operations": [
            {"kind":"tags", "itemIds":[ids[2]], "classification":{"family":"object", "canonicalType":"token", "tags":["keep"]}},
            {"kind":"merge", "itemIds":ids[:2]},
        ]}, tmp_path / "successor")
    assert (root / "manifest.json").read_bytes() == parent_bytes
    assert len(successor["items"]) == 2
    unchanged = next(item for item in successor["items"] if item["id"] == ids[2])
    assert unchanged["classification"]["tags"] == ["keep"]
    assert unchanged["source"]["lineage"]["parentItemIds"] == [ids[2]]
    assert unchanged["source"]["lineage"]["revision"] == "pinned-revision"
    merged = next(item for item in successor["items"] if item["id"] != ids[2])
    assert merged["source"]["lineage"]["parentItemIds"] == ids[:2]
    assert merged["id"] not in ids
    assert merged["review"]["status"] == "pending"
    assert merged["classificationInheritedFrom"]["itemId"] == ids[0]
    assert "changed_sprite_classification_review" in merged["qaFlags"]
    with pytest.raises(ItemSheetError, match="hash mismatch"):
        apply_ownership_review(root / "manifest.json", {"parentManifestSha256":"0"*64,"operations":[]}, tmp_path / "bad")


def test_tag_correction_invalidates_only_semantic_approval(tmp_path: Path) -> None:
    source, root = tmp_path / "source.png", tmp_path / "parent"
    _sheet().save(source)
    manifest = build_item_atlas(source, root, provenance="fixture")
    approved = tmp_path / "approved"
    first = apply_ownership_review(root / "manifest.json", {"parentManifestSha256": digest_file(root / "manifest.json"),
        "operations": [{"kind": "approve", "itemIds": [i["id"] for i in manifest["items"]]}]}, approved)
    original = (approved / "manifest.json").read_bytes()
    target = first["items"][0]["id"]
    corrected = apply_ownership_review(approved / "manifest.json", {"parentManifestSha256": digest_file(approved / "manifest.json"),
        "operations": [{"kind": "tags", "itemIds": [target], "classification": {"family": "object", "canonicalType": "token", "tags": ["corrected"]}}]}, tmp_path / "corrected")
    changed = next(i for i in corrected["items"] if i["id"] == target)
    assert changed["review"]["status"] == "pending"
    assert {scope: record["status"] for scope, record in changed["review"]["scopes"].items()} == {"pixels": "approved", "semantics": "pending", "placement": "approved"}
    assert (approved / "manifest.json").read_bytes() == original


def test_failed_directory_publication_restores_prior_bytes(tmp_path: Path, monkeypatch) -> None:
    from spritecore.publication import publish_directory
    old, stage = tmp_path / "published", tmp_path / "staged"
    old.mkdir(); stage.mkdir()
    (old / "receipt").write_bytes(b"prior-success")
    (stage / "receipt").write_bytes(b"successor")
    replace = Path.replace
    def fail_publish(path, target):
        if path == stage:
            raise OSError("injected publication failure")
        return replace(path, target)
    with monkeypatch.context() as patch:
        patch.setattr(Path, "replace", fail_publish)
        with pytest.raises(OSError, match="injected"):
            publish_directory(stage, old, replace=True)
    assert (old / "receipt").read_bytes() == b"prior-success"
    assert (stage / "receipt").read_bytes() == b"successor"
    publish_directory(stage, old, replace=True)
    assert (old / "receipt").read_bytes() == b"successor"
    assert [p.read_bytes() for p in (tmp_path / ".published.revisions").glob("*/receipt")] == [b"prior-success"]


def test_review_does_not_follow_output_symlink(tmp_path: Path) -> None:
    from apply_item_review import apply_review
    source, parent, target, link = (tmp_path / name for name in ("source.png", "parent", "published", "linked"))
    _sheet().save(source)
    manifest = build_item_atlas(source, parent, provenance="fixture")
    review = tmp_path / "review.json"
    review.write_text(json.dumps({"schemaVersion": "item-review-v1", "kind": "deterministic-item-review",
        "runId": manifest["runId"], "sourceManifest": {"sha256": digest_file(parent / "manifest.json")}, "items": []}))
    target.mkdir()
    (target / "receipt").write_bytes(b"prior-success")
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unavailable on this host")
    with pytest.raises(ItemSheetError, match="symbolic link"):
        apply_review(parent / "manifest.json", review, link, allow_pending=True, force=True)
    assert link.is_symlink() and (target / "receipt").read_bytes() == b"prior-success"


def test_bounded_pages_keep_native_pixels_and_export_every_page(tmp_path: Path, monkeypatch) -> None:
    from spritecore.item_delivery import validate_delivery
    from export_item_atlas import export_atlas
    source = tmp_path / "source.png"
    _sheet().save(source)
    root = tmp_path / "pages"
    packing = PackingConfig(quantum=16, padding=8, max_width=64, max_height=64)
    manifest = build_item_atlas(source, root, provenance="fixture", packing=packing)
    assert len(manifest["pages"]) == 3
    assert [item["geometry"]["pageId"] for item in manifest["items"]] == [p["id"] for p in manifest["pages"]]
    assert validate_delivery(root / "manifest.json", draft=True)["status"] == "pass"
    receipt = export_atlas(root / "manifest.json", tmp_path / "export", draft=True)
    index = json.loads((tmp_path / "export/atlas-index.json").read_text())
    assert [page["id"] for page in index["pages"]] == [page["id"] for page in manifest["pages"]]
    for page, exported in zip(manifest["pages"], index["pages"]):
        assert digest_file(tmp_path / "export" / exported["image"]) == page["sha256"]
        assert exported["data"] in receipt["files"]
    reference = _sheet()
    items = segment_items(reference)
    def reject_allocation(*args, **kwargs):
        raise AssertionError("atlas allocation must follow budget checks")
    monkeypatch.setattr(Image, "new", reject_allocation)
    with pytest.raises(ItemSheetError, match="page"):
        write_item_atlas_run(items, tmp_path / "over-budget", source=manifest["source"],
            source_reference=reference,
            segmentation=manifest["segmentation"], packing=PackingConfig(quantum=16, padding=8, max_width=64, max_height=64, max_pages=1))


def test_group_evaluation_reports_merge_and_rejects_unbound_annotations(tmp_path: Path) -> None:
    from evaluate_item_atlas import evaluate
    image = Image.new("RGBA", (20, 10))
    ImageDraw.Draw(image).rectangle((2, 2, 4, 5), fill=(1, 2, 3, 255))
    ImageDraw.Draw(image).rectangle((12, 2, 14, 5), fill=(4, 5, 6, 255))
    path, root = tmp_path / "source.png", tmp_path / "run"
    image.save(path)
    manifest = build_item_atlas(path, root, provenance="fixture", segmentation=SegmentationConfig(min_strong_pixels=1))
    annotations = {"schemaVersion": "item-group-annotations-v1", "reviewer": {"kind": "agent", "name": "fixture"},
        "sourceSha256": manifest["source"]["sha256"], "groups": [{"id": "left", "rects": [[1, 1, 6, 7]]}, {"id": "right", "rects": [[11, 1, 16, 7]]}]}
    annotation_path = tmp_path / "annotations.json"
    annotation_path.write_text(json.dumps(annotations))
    assert evaluate(annotation_path, root / "manifest.json")["metrics"]["exactGroups"] == 2
    merged = tmp_path / "merged"
    apply_ownership_review(root / "manifest.json", {"parentManifestSha256": digest_file(root / "manifest.json"),
        "operations": [{"kind": "merge", "itemIds": [i["id"] for i in manifest["items"]]}]}, merged)
    measured = evaluate(annotation_path, merged / "manifest.json")
    assert measured["metrics"]["crossGroupMerges"] == 1 and measured["metrics"]["meanGroupIoU"] == .5
    assert measured["productionApproval"] is False
    annotations["sourceSha256"] = "0" * 64
    annotation_path.write_text(json.dumps(annotations))
    with pytest.raises(ValueError, match="source hash"):
        evaluate(annotation_path, merged / "manifest.json")


def test_model_result_rejects_invalid_types_and_out_of_taxonomy_values() -> None:
    from run_item_model_worker import _classification_result, _segmentation_result, classification_schema, ItemModelWorkerError
    job = {"jobId":"fixture", "runId":"fixture", "itemId":"item_000000000000",
           "inputs":{"rgba":{"sha256":"0"*64}},
           "taxonomy":{"families":{"object":["token"]}, "materials":[], "conditions":[],
                       "orientations":["unknown"], "sizeClasses":["unknown"]}}
    result = {"family":"object", "canonicalType":"token", "materials":"stone", "condition":[],
              "orientation":"unknown", "sizeClass":"unknown", "tags":[], "confidence":.9}
    with pytest.raises(ItemModelWorkerError, match="array"):
        _classification_result(job, result, "fixture-model")
    result.update(materials=[], canonicalType="invented")
    with pytest.raises(ItemModelWorkerError, match="taxonomy"):
        _classification_result(job, result, "fixture-model")
    with pytest.raises(ItemModelWorkerError, match="bbox"):
        _segmentation_result(job, {"instances":[["x",10,0,5,20,.9]],"confidence":.9}, "fixture-model")
    job["taxonomy"]["families"]["character"] = ["villager"]
    result.update(family="character",canonicalType="token",subtype=None,notes="fixture")
    assert not Draft202012Validator(classification_schema(job)).is_valid(result)
    result["canonicalType"] = "villager"
    assert Draft202012Validator(classification_schema(job)).is_valid(result)


def test_checkpoint_preparation_rejects_missing_shards(tmp_path: Path) -> None:
    from spritecore.model_checkpoints import verified_snapshot
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    (snapshot / "config.json").write_text("{}")
    (snapshot / "one.safetensors").write_bytes(b"fixture")
    (snapshot / "model.safetensors.index.json").write_text(json.dumps({"weight_map": {"a": "one.safetensors", "b": "missing.safetensors"}}))
    entry = {"id": "fixture/model", "revision": "a"*40, "snapshot": "snapshot"}
    with pytest.raises(ValueError, match="shard"):
        verified_snapshot(entry, tmp_path)
    with pytest.raises(ValueError, match="revision"):
        verified_snapshot(entry, tmp_path, revision="b"*40)


def test_segmentation_handoff_rejects_changed_mask_bytes(tmp_path: Path) -> None:
    from spritecore.item_segmentation import prepare_segmentation_jobs, apply_segmentation_results, ItemSegmentationError
    source, root = tmp_path / "source.png", tmp_path / "parent"
    _sheet().save(source)
    build_item_atlas(source, root, provenance="fixture")
    jobs = tmp_path / "jobs.jsonl"
    job = prepare_segmentation_jobs(root / "manifest.json", jobs)[0]
    jobs.write_text(json.dumps(job))
    mask = tmp_path / "mask.png"
    Image.new("L", (128,96), 255).save(mask)
    artifact = {"path":"mask.png", "sha256":digest_file(mask), "width":128, "height":96}
    Image.new("L", (128,96), 0).save(mask)
    results = tmp_path / "results.jsonl"
    results.write_text(json.dumps({
        "schemaVersion":"item-segmentation-result-v1", "jobId":job["jobId"], "runId":job["runId"], "itemId":job["itemId"],
        "model":"fixture", "inputHashes":{"rgba":job["inputs"]["rgba"]["sha256"]},
        "decision":{"instanceCount":1, "confidence":.9, "notes":"fixture", "instances":[
            {"instanceId":"one", "label":"group", "bbox":[0,0,1000,1000], "confidence":.9, "mask":artifact}]}}))
    with pytest.raises(ItemSegmentationError, match="mask hash mismatch"):
        apply_segmentation_results(root / "manifest.json", jobs, results, tmp_path / "rejected")
    assert not (tmp_path / "rejected").exists()

    # A valid single-group proposal may cover only a small part of the target.
    # Keep its complete original alpha instead of accepting SAM edge loss.
    from spritecore.item_ownership import source_masks
    parent = json.loads((root / "manifest.json").read_text())
    target = source_masks(root, parent)[job["itemId"]]
    x0,y0,x1,y1 = target.getbbox()
    partial = Image.new("L", target.size)
    partial.paste(target.crop((x0,y0,x1,y0+max(1,(y1-y0)//3))), (x0,y0))
    partial.save(mask)
    record = json.loads(results.read_text())
    record["decision"]["instances"][0]["mask"]["sha256"] = digest_file(mask)
    results.write_text(json.dumps(record))
    accepted = apply_segmentation_results(root / "manifest.json", jobs, results, tmp_path / "accepted")
    assert len(accepted["items"]) == 1
    item = accepted["items"][0]
    assert item["source"]["assignedPixels"] == target.histogram()[255]
    assert "whole_source_group_review" in item["qaFlags"]
    assert accepted["completion"]["pendingPixels"] > 0  # Other objects stay pending.
