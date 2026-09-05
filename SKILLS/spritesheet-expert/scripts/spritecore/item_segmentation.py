"""Model-neutral semantic split contracts for deterministic item atlases.

Models may propose normalized instance boxes and optional binary masks. This
module remains authoritative for source-byte validation, pixel ownership,
stable IDs, native-size crops, packing, lineage, and review flags.
"""

from __future__ import annotations

from hashlib import sha256
import json
import math
from pathlib import Path
from typing import Any

from PIL import Image

from .item_sheet import (
    PackingConfig,
    write_item_atlas_run,
)


class ItemSegmentationError(ValueError):
    """Raised when a segmentation handoff cannot be applied safely."""


def digest_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ItemSegmentationError(f"cannot read JSON {path}: {exc}") from exc


def read_json_records(path: Path) -> list[dict[str, Any]]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ItemSegmentationError(f"cannot read records {path}: {exc}") from exc
    if not raw.strip():
        return []
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        decoded = None
    if isinstance(decoded, list):
        if not all(isinstance(entry, dict) for entry in decoded):
            raise ItemSegmentationError("every record must be an object")
        return decoded
    if isinstance(decoded, dict):
        values = decoded.get("results")
        if isinstance(values, list):
            if not all(isinstance(entry, dict) for entry in values):
                raise ItemSegmentationError("every result must be an object")
            return values
        return [decoded]
    records: list[dict[str, Any]] = []
    for number, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ItemSegmentationError(f"invalid JSONL line {number}: {exc}") from exc
        if not isinstance(entry, dict):
            raise ItemSegmentationError(f"record line {number} must be an object")
        records.append(entry)
    return records


def portable_artifact(root: Path, relative: str) -> Path:
    if not relative or "\\" in relative or relative.startswith("/") or ".." in Path(relative).parts:
        raise ItemSegmentationError(f"unsafe artifact path: {relative}")
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ItemSegmentationError(f"artifact escapes run root: {relative}") from exc
    if not candidate.is_file():
        raise ItemSegmentationError(f"artifact does not exist: {relative}")
    return candidate


def prepare_segmentation_jobs(
    manifest_path: Path, output_path: Path, *, force: bool = False,
) -> list[dict[str, Any]]:
    """Ask about one alpha region at a time, with the sheet as visual context."""
    from .item_ownership import source_image
    manifest_path, output = manifest_path.resolve(), output_path.resolve()
    root = manifest_path.parent
    manifest = load_json(manifest_path)
    if manifest.get("kind") != "deterministic-item-atlas":
        raise ItemSegmentationError("manifest is not an item atlas")
    if output.suffix != ".jsonl" or (output.exists() and not force):
        raise ItemSegmentationError("use a new .jsonl output")
    source = source_image(root, manifest)
    inference = root / "inference"
    inference.mkdir(exist_ok=True)
    context = Image.new("RGB", source.size, (238, 238, 232))
    context.paste(source.convert("RGB"), mask=source.getchannel("A"))
    context.thumbnail((512, 512))
    context_path = inference / "sheet-context.png"
    context.save(context_path)
    jobs = []
    for item in manifest["items"]:
        x0, y0, x1, y1 = item["source"]["bbox"]
        margin = 32
        region = [max(0,x0-margin), max(0,y0-margin), min(source.width,x1+margin), min(source.height,y1+margin)]
        crop = source.crop(region)
        inputs = {
            "rgba": {"path":manifest["evidence"]["sourceRgba"], "sha256":digest_file(root / manifest["evidence"]["sourceRgba"])},
            "sheetContext": {"path":context_path.relative_to(root).as_posix(), "sha256":digest_file(context_path)},
        }
        for name, color in (("lightComposite",(238,238,232)),("darkComposite",(28,28,27))):
            composite = Image.new("RGB", crop.size, color)
            composite.paste(crop.convert("RGB"), mask=crop.getchannel("A"))
            path = inference / f"region-{item['id']}-{name}.png"
            composite.save(path)
            inputs[name] = {"path":path.relative_to(root).as_posix(), "sha256":digest_file(path)}
        target = [round((v-region[i%2])*1000/(crop.width if i%2==0 else crop.height))
                  for i,v in enumerate(item["source"]["bbox"])]
        jobs.append({
            "schemaVersion":"item-segmentation-job-v1", "scope":"source-region",
            "jobId":f"segment-{item['id']}", "runId":manifest["runId"], "itemId":item["id"],
            "pathBase":"manifest-directory", "sourceManifest":{"path":manifest_path.name,"sha256":digest_file(manifest_path)},
            "inputs":inputs, "regionBbox":region, "sourceSize":list(source.size),
            "candidate":{"sourceBbox":item["source"]["bbox"],"qaFlags":item["qaFlags"]},
            "prompt":(
                "Image 1 is the region to segment. Image 2 is only a miniature of the complete sheet for context. "
                f"The target alpha component lies in box {target} in IMAGE 1 (coordinates 0..1000). "
                "Return the complete visual object containing this target. Include its tools, smoke or detached accessories "
                "visible in image 1. Do NOT split cargo, flags, smoke, furniture or tools away from their parent building/person. "
                "A detailed building scene, including attached wings, towers, ground and props, is ONE game asset. "
                "Keep the target intact unless it clearly contains separate primary subjects, such as two neighboring buildings. "
                "Do not catalogue construction parts or accessories as independent sprites. "
                "Do NOT include unrelated neighboring objects. If the target component itself joins "
                "several independent objects, return one separate box for each of those objects. "
                "An unrecognizable fragment is still an object: label it unknown, do not omit it. "
                "Coordinates are normalized integers 0..1000 relative to IMAGE 1 only. "
                "Return compact JSON with confidence (0..1) then instances. Each instances entry MUST be "
                "an array [label,x0,y0,x1,y1,confidence], with a short English label. No notes, Markdown or declared count."
            ),
            "expected":{"format":"item-segmentation-result-v1","normalizedCoordinates":[0,1000],
                        "minimumInstances":1,"pixelAuthority":"deterministic-compiler"},
            "status":"prepared",
        })
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".jsonl.tmp")
    temporary.write_text("".join(json.dumps(job,ensure_ascii=False)+"\n" for job in jobs), encoding="utf-8")
    temporary.replace(output)
    return jobs


def apply_segmentation_results(
    manifest_path: Path, jobs_path: Path, results_path: Path, output_dir: Path, *,
    minimum_confidence: float = 0.70, force: bool = False,
) -> dict[str, Any]:
    from PIL import ImageChops
    from jsonschema import Draft202012Validator
    from .item_ownership import compile_masks, source_image, source_masks
    if not 0 <= minimum_confidence <= 1:
        raise ItemSegmentationError("minimum confidence must be between 0 and 1")
    manifest_path, jobs_path, results_path, output_dir = (
        path.resolve() for path in (manifest_path, jobs_path, results_path, output_dir))
    if any(path.is_relative_to(output_dir) for path in (manifest_path, jobs_path, results_path)):
        raise ItemSegmentationError("output cannot contain its input")
    manifest = load_json(manifest_path)
    jobs, results = read_json_records(jobs_path), read_json_records(results_path)
    job_map = {job.get("jobId"):job for job in jobs}
    result_map = {result.get("jobId"):result for result in results}
    if not jobs or len(job_map)!=len(jobs) or len(result_map)!=len(results) or set(job_map)!=set(result_map):
        raise ItemSegmentationError("one result for every unique region job is required")
    schema = load_json(Path(__file__).resolve().parents[2] / "references/schemas/item-segmentation-v1.schema.json")
    validator = Draft202012Validator(schema)
    source = source_image(manifest_path.parent, manifest)
    parents = source_masks(manifest_path.parent, manifest)
    visible = source.getchannel("A").point(lambda a: 255 if a else 0)
    masks, flags, records = {}, {}, {}
    mask_count = 0
    for job_id, job in job_map.items():
        result = result_map[job_id]
        if job.get("scope") != "source-region" or job.get("sourceManifest", {}).get("sha256") != digest_file(manifest_path):
            raise ItemSegmentationError("source job or manifest hash mismatch")
        for key in ("runId", "itemId"):
            if result.get(key) != job.get(key):
                raise ItemSegmentationError(f"result {key} mismatch")
        if job["itemId"] not in parents:
            raise ItemSegmentationError("region target is not a source component")
        if result.get("inputHashes", {}).get("rgba") != job["inputs"]["rgba"]["sha256"]:
            raise ItemSegmentationError("result RGBA hash mismatch")
        for artifact in job["inputs"].values():
            if digest_file(portable_artifact(manifest_path.parent, artifact["path"])) != artifact["sha256"]:
                raise ItemSegmentationError("job input artifact hash mismatch")
        errors = list(validator.iter_errors(result))
        if errors:
            raise ItemSegmentationError(errors[0].message)
        decision = result["decision"]
        if decision["instanceCount"] != len(decision["instances"]):
            raise ItemSegmentationError("instance count mismatch")
        for instance in decision["instances"]:
            key = f"{job_id}/{instance['instanceId']}"
            if key in masks:
                raise ItemSegmentationError("duplicate instanceId")
            x0,y0,x1,y1 = instance["bbox"]
            if not 0 <= x0 < x1 <= 1000 or not 0 <= y0 < y1 <= 1000:
                raise ItemSegmentationError("invalid normalized box")
            artifact = instance.get("mask")
            if not artifact:
                raise ItemSegmentationError("region results require a source-coordinate mask")
            path = portable_artifact(results_path.parent, artifact["path"])
            if digest_file(path) != artifact["sha256"]:
                raise ItemSegmentationError("mask hash mismatch")
            with Image.open(path) as opened:
                mask = opened.convert("L").point(lambda a:255 if a else 0)
            if mask.size != source.size or mask.size != (artifact["width"],artifact["height"]):
                raise ItemSegmentationError("mask dimensions mismatch")
            mask_count += 1
            masks[key] = ImageChops.multiply(mask, visible)
            flags[key] = list(result.get("warnings", []))
            if min(instance["confidence"],decision["confidence"]) < minimum_confidence:
                flags[key].append("low_model_segmentation_confidence")
            target = parents[job["itemId"]]
            target_overlap = ImageChops.multiply(masks[key],target).histogram()[255]
            if target_overlap < target.histogram()[255]*.05:
                flags[key].append("target_component_missing_review")
            elif len(decision["instances"]) == 1:
                # Qwen kept the source group intact. SAM is not allowed to
                # erase its smoke, thin edges or attached props. Its mask can
                # still propose detached fragments; conflicts remain pending.
                masks[key] = ImageChops.lighter(masks[key], target)
                flags[key].append("whole_source_group_review")
            records[key] = {"parentItemIds": [], "modelEvidence": {
                "jobId":job_id, "model":result["model"],"revision":result.get("modelRevision"),
                "maskModel":result.get("maskModel"),"maskRevision":result.get("maskRevision"),
                "label":instance["label"],"normalizedBbox":instance["bbox"]}}
    # Neighbour queries can propose the same visual group. Merge only strong
    # geometric agreement, and retain a review flag: agreement is not semantics.
    keys = list(masks)
    bounds = {key:mask.getbbox() for key,mask in masks.items()}
    for i,left in enumerate(keys):
        if left not in masks or not bounds[left]:
            continue
        for right in keys[i+1:]:
            if right not in masks or not bounds[right]:
                continue
            a,b = bounds[left],bounds[right]
            if a[2]<=b[0] or b[2]<=a[0] or a[3]<=b[1] or b[3]<=a[1]:
                continue
            common = ImageChops.multiply(masks[left],masks[right]).histogram()[255]
            union = masks[left].histogram()[255]+masks[right].histogram()[255]-common
            if union and common/union >= .80:
                masks[left] = ImageChops.lighter(masks[left],masks.pop(right))
                flags[left] += flags.pop(right)+["duplicate_group_proposals_review"]
                records[left].setdefault("mergedProposals",[]).append(records.pop(right))
                bounds[left] = masks[left].getbbox()
    for parent_id, component in parents.items():
        total = component.histogram()[255]
        scores = sorted(((ImageChops.multiply(mask, component).histogram()[255], key)
                         for key,mask in masks.items()),reverse=True)
        if scores and total and scores[0][0]/total >= .60 and (len(scores)==1 or scores[1][0]/total<=.02):
            masks[scores[0][1]] = ImageChops.lighter(masks[scores[0][1]],component)
        for score,key in scores:
            if score:
                records[key]["parentItemIds"].append(parent_id)
        if len([s for s,k in scores if s>total*.10])>1:
            for score,key in scores:
                if score:
                    flags[key].append("component_split_review")
    empty_masks = [key for key,mask in masks.items() if not mask.getbbox()]
    if empty_masks:
        for item_flags in flags.values():
            item_flags.append("empty_model_mask_review")
    items, overrides = compile_masks(source,masks,records=records,flags=flags)
    pack = manifest["packing"]
    return write_item_atlas_run(
        items,output_dir,source=manifest["source"],source_reference=source,
        segmentation={**manifest["segmentation"],"method":"model-mask-import"},
        packing=PackingConfig(**{key:pack[key] for key in ("quantum","padding","max_width","outer_padding")}),
        parent_manifest_sha256=digest_file(manifest_path),item_overrides=overrides,force=force,
        manifest_extra={"segmentationApplication":{
            "jobsSha256":digest_file(jobs_path),"resultsSha256":digest_file(results_path),
            "resultCount":len(results),"splitParentCount":sum("component_split_review" in item.qa_flags for item in items),
            "maskCount":mask_count,"missingCount":0,"emptyMaskIds":empty_masks,
            "minimumConfidence":minimum_confidence,
            "models":[{"model":r["model"],"revision":r.get("modelRevision"),"maskRevision":r.get("maskRevision")} for r in results],
        }})
