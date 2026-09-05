#!/usr/bin/env python3
"""Run local Qwen3-VL jobs and optionally refine split boxes with SAM2 masks."""

from __future__ import annotations

import argparse
import gc
from hashlib import sha256
import json
import math
import os
import re
from pathlib import Path
import shutil
import tempfile
import time
from typing import Any, Mapping, Sequence

from PIL import Image

from spritecore.item_segmentation import (
    ItemSegmentationError,
    digest_file,
    portable_artifact,
    read_json_records,
)


SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = "Qwen/Qwen3-VL-4B-Instruct"
DEFAULT_MASK_MODEL = "facebook/sam2.1-hiera-small"


class ItemModelWorkerError(RuntimeError):
    pass


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", choices=("classify", "segment"), required=True)
    parser.add_argument("--jobs", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--run-root", type=Path)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--mask-model",
        default="none",
        help=f"SAM2 checkpoint for segmentation, or none (recommended starter: {DEFAULT_MASK_MODEL})",
    )
    parser.add_argument("--device", choices=("auto", "cuda", "cpu"), default="auto")
    parser.add_argument("--max-new-tokens", type=int, default=8192)
    parser.add_argument("--revision")
    parser.add_argument("--mask-revision")
    parser.add_argument("--local-files-only", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def _find_run_root(job: Mapping[str, Any], jobs_path: Path, explicit: Path | None) -> Path:
    source_manifest = job.get("sourceManifest")
    if not isinstance(source_manifest, Mapping):
        raise ItemModelWorkerError(f"{job.get('jobId')}: sourceManifest missing")
    relative = source_manifest.get("path")
    expected_sha = source_manifest.get("sha256")
    if not isinstance(relative, str) or not isinstance(expected_sha, str):
        raise ItemModelWorkerError(f"{job.get('jobId')}: sourceManifest is incomplete")
    candidates = [explicit.expanduser().resolve()] if explicit else [jobs_path.parent, *jobs_path.parents]
    for candidate in candidates:
        if not (candidate / relative).is_file():
            continue
        manifest = portable_artifact(candidate, relative)
        if manifest.is_file() and digest_file(manifest) == expected_sha:
            return candidate.resolve()
    raise ItemModelWorkerError(
        f"{job.get('jobId')}: cannot locate the hash-matching manifest directory; pass --run-root"
    )


def _verified_input(root: Path, job: Mapping[str, Any], name: str) -> Path:
    inputs = job.get("inputs")
    if not isinstance(inputs, Mapping) or not isinstance(inputs.get(name), Mapping):
        raise ItemModelWorkerError(f"{job.get('jobId')}: input {name} missing")
    artifact = inputs[name]
    path = portable_artifact(root, str(artifact.get("path", "")))
    if digest_file(path) != artifact.get("sha256"):
        raise ItemModelWorkerError(f"{job.get('jobId')}: input {name} sha256 mismatch")
    return path


def _extract_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end <= start:
            raise ItemModelWorkerError("model response contains no JSON object")
        try:
            value = json.loads(stripped[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ItemModelWorkerError(f"model response is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ItemModelWorkerError("model response must be one JSON object")
    return value


def _load_qwen(model_id: str, device: str, local_files_only: bool, revision: str | None = None) -> tuple[Any, Any]:
    try:
        import torch
        from transformers import AutoProcessor, Qwen3VLForConditionalGeneration
    except ImportError as exc:
        raise ItemModelWorkerError(
            "local-model dependencies are missing; run setup_item_model_runtime.py and use its Python"
        ) from exc
    if device == "cuda" and not torch.cuda.is_available():
        raise ItemModelWorkerError("--device cuda was requested but CUDA is unavailable")
    device_map = "cpu" if device == "cpu" else "auto"
    try:
        processor = AutoProcessor.from_pretrained(model_id, local_files_only=local_files_only, revision=revision,
            size={"shortest_edge":65536, "longest_edge":1048576})
        model = Qwen3VLForConditionalGeneration.from_pretrained(
            model_id,
            device_map=device_map,
            torch_dtype="auto",
            attn_implementation="sdpa",
            local_files_only=local_files_only,
            revision=revision,
        )
    except Exception as exc:
        mode = "local cache" if local_files_only else "checkpoint download or local cache"
        raise ItemModelWorkerError(f"cannot load Qwen model {model_id} from {mode}: {exc}") from exc
    model.eval()
    return model, processor


def _generate_json(
    model: Any,
    processor: Any,
    images: Sequence[Image.Image],
    prompt: str,
    max_new_tokens: int,
    raw_path: Path | None = None,
    output_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    content = [{"type": "image", "image": image.convert("RGB")} for image in images]
    content.append({"type": "text", "text": prompt})
    messages = [{"role": "user", "content": content}]
    try:
        inputs = processor.apply_chat_template(
            messages,
            tokenize=True,
            add_generation_prompt=True,
            return_dict=True,
            return_tensors="pt",
        )
        inputs = inputs.to(model.device)
        import torch
        from transformers import StoppingCriteria, StoppingCriteriaList
        from lmformatenforcer import JsonSchemaParser, RegexParser
        from lmformatenforcer.integrations.transformers import (
            build_token_enforcer_tokenizer_data, build_transformers_prefix_allowed_tokens_fn)
        if not hasattr(processor, "item_tokenizer_data"):
            processor.item_tokenizer_data = build_token_enforcer_tokenizer_data(processor.tokenizer)
        if output_schema is not None:
            format_parser = JsonSchemaParser(output_schema)
        else:
            confidence = r"(?:0(?:\.[0-9]{1,3})?|1(?:\.0{1,3})?)"
            coordinate = r"(?:0|[1-9][0-9]{0,2}|1000)"
            row = (r'\["[A-Za-z][A-Za-z0-9 _-]{0,47}",' +
                   (coordinate + ",")*4 + confidence + r"\]")
            format_parser = RegexParser(r'\{"confidence":' + confidence + r',"instances":\[' + row + r'(?:,' + row + r')*\]\}')
        prefix = build_transformers_prefix_allowed_tokens_fn(processor.item_tokenizer_data, format_parser)
        prompt_tokens = inputs.input_ids.shape[-1]
        started = time.monotonic()

        class Progress(StoppingCriteria):
            reported = 0

            def __call__(self, input_ids, scores, **kwargs):
                count = input_ids.shape[-1] - prompt_tokens
                if count - self.reported >= 128:
                    self.reported = count
                    print(json.dumps({"status":"generating", "generatedTokens":count,
                        "seconds":round(time.monotonic()-started,1)}), file=os.sys.stderr, flush=True)
                return False

        with torch.inference_mode():
            generated = model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False,
                                       stopping_criteria=StoppingCriteriaList([Progress()]),
                                       prefix_allowed_tokens_fn=prefix)
        trimmed = [output[len(input_ids) :] for input_ids, output in zip(inputs.input_ids, generated)]
        response = processor.batch_decode(
            trimmed,
            skip_special_tokens=True,
            clean_up_tokenization_spaces=False,
        )[0]
    except Exception as exc:
        raise ItemModelWorkerError(f"Qwen inference failed: {exc}") from exc
    if raw_path is not None:
        raw_path.write_text(response, encoding="utf-8")
    return _extract_json(response)


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ItemModelWorkerError(f"{field} must be numeric")
    result = float(value)
    if not math.isfinite(result) or not 0 <= result <= 1:
        raise ItemModelWorkerError(f"{field} must be between 0 and 1")
    return result


def classification_schema(job: Mapping[str, Any]) -> dict[str, Any]:
    taxonomy = job["taxonomy"]
    def strings(values=None, limit=8):
        item = {"type":"string", "minLength":1,"maxLength":48}
        if values:
            item["enum"] = values
        return {"type":"array","items":item,"maxItems":limit}
    properties = {
        "family":{"enum":list(taxonomy["families"])},
        "canonicalType":{"enum":sorted({v for values in taxonomy["families"].values() for v in values})},
        "subtype":{"anyOf":[{"type":"string","maxLength":48},{"type":"null"}]},
        "materials":strings(taxonomy["materials"]),"condition":strings(taxonomy["conditions"]),
        "orientation":{"enum":taxonomy["orientations"]}, "sizeClass":{"enum":taxonomy["sizeClasses"]},
        "tags":strings(),"confidence":{"type":"number","minimum":0,"maximum":1},
        "notes":{"type":"string","maxLength":160},
    }
    return {"anyOf":[{
        "type":"object", "properties":{**properties,
            "family":{"const":family}, "canonicalType":{"enum":canonical_types}},
        "required":list(properties), "additionalProperties":False,
    } for family, canonical_types in taxonomy["families"].items()]}


def _string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(entry, str) and entry for entry in value):
        raise ItemModelWorkerError(f"{field} must be an array of non-empty strings")
    return list(dict.fromkeys(value))


def _classification_result(
    job: Mapping[str, Any],
    raw: Mapping[str, Any],
    model_id: str,
) -> dict[str, Any]:
    payload = raw.get("classification", raw)
    if not isinstance(payload, Mapping):
        raise ItemModelWorkerError(f"{job.get('jobId')}: classification must be an object")
    taxonomy = job.get("taxonomy")
    if not isinstance(taxonomy, Mapping) or not isinstance(taxonomy.get("families"), Mapping):
        raise ItemModelWorkerError(f"{job.get('jobId')}: closed taxonomy missing")
    family = payload.get("family")
    canonical = payload.get("canonicalType")
    if not isinstance(family, str) or not isinstance(canonical, str):
        raise ItemModelWorkerError(f"{job.get('jobId')}: family and canonicalType are required")
    families = taxonomy["families"]
    allowed_types = families.get(family)
    if family == "unknown" and canonical == "unknown":
        pass
    elif not isinstance(allowed_types, list) or canonical not in allowed_types:
        raise ItemModelWorkerError(
            f"{job.get('jobId')}: model returned taxonomy value outside {family}/{canonical}"
        )
    materials = _string_list(payload.get("materials"), "materials")
    conditions = _string_list(payload.get("condition"), "condition")
    tags = _string_list(payload.get("tags"), "tags")
    if set(materials) - set(taxonomy.get("materials", [])):
        raise ItemModelWorkerError(f"{job.get('jobId')}: model returned material outside taxonomy")
    if set(conditions) - set(taxonomy.get("conditions", [])):
        raise ItemModelWorkerError(f"{job.get('jobId')}: model returned condition outside taxonomy")
    orientation = payload.get("orientation")
    size_class = payload.get("sizeClass")
    if orientation not in taxonomy.get("orientations", []):
        raise ItemModelWorkerError(f"{job.get('jobId')}: model returned orientation outside taxonomy")
    if size_class not in taxonomy.get("sizeClasses", []):
        raise ItemModelWorkerError(f"{job.get('jobId')}: model returned sizeClass outside taxonomy")
    subtype = payload.get("subtype")
    notes = payload.get("notes", "")
    if subtype is not None and not isinstance(subtype, str):
        raise ItemModelWorkerError(f"{job.get('jobId')}: subtype must be a string or null")
    if not isinstance(notes, str):
        raise ItemModelWorkerError(f"{job.get('jobId')}: notes must be a string")
    return {
        "schemaVersion": "item-classification-result-v1",
        "jobId": job["jobId"],
        "runId": job["runId"],
        "itemId": job["itemId"],
        "model": model_id,
        "inputHashes": {
            name: artifact["sha256"]
            for name, artifact in job["inputs"].items()
            if isinstance(artifact, Mapping) and isinstance(artifact.get("sha256"), str)
        },
        "classification": {
            "family": family,
            "canonicalType": canonical,
            "subtype": subtype,
            "materials": materials,
            "condition": conditions,
            "orientation": orientation,
            "sizeClass": size_class,
            "tags": tags,
            "confidence": _number(payload.get("confidence"), "confidence"),
            "source": model_id,
            "notes": notes,
        },
    }


def _segmentation_result(
    job: Mapping[str, Any],
    raw: Mapping[str, Any],
    model_id: str,
) -> dict[str, Any]:
    payload = raw.get("decision", raw)
    if not isinstance(payload, Mapping):
        raise ItemModelWorkerError(f"{job.get('jobId')}: decision must be an object")
    instances = payload.get("instances")
    if not isinstance(instances, list) or not instances:
        raise ItemModelWorkerError(f"{job.get('jobId')}: instances must be a nonempty array")
    count = payload.get("instanceCount", len(instances))
    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        raise ItemModelWorkerError(f"{job.get('jobId')}: instanceCount must be positive")
    count_mismatch = count != len(instances)
    reported_count = count
    count = len(instances)
    normalized: list[dict[str, Any]] = []
    for index, instance in enumerate(instances):
        if not isinstance(instance, list) or len(instance) != 6:
            raise ItemModelWorkerError(f"{job.get('jobId')}: instance {index + 1} must be [label,x0,y0,x1,y1,confidence]")
        label = instance[0]
        bbox = instance[1:5]
        if not isinstance(label, str) or not label.strip():
            raise ItemModelWorkerError(f"{job.get('jobId')}: instance {index + 1} label missing")
        if not (
            isinstance(bbox, list)
            and len(bbox) == 4
            and all(isinstance(value, int) and not isinstance(value, bool) for value in bbox)
        ):
            raise ItemModelWorkerError(f"{job.get('jobId')}: instance {index + 1} bbox must use integers")
        x0, y0, x1, y1 = bbox
        if not (0 <= x0 < x1 <= 1000 and 0 <= y0 < y1 <= 1000):
            raise ItemModelWorkerError(f"{job.get('jobId')}: instance {index + 1} bbox is invalid")
        normalized.append(
            {
                "instanceId": f"instance-{index + 1:02d}",
                "label": label.strip(),
                "bbox": list(bbox),
                "confidence": _number(instance[5], f"instances[{index}].confidence"),
            }
        )
        if job.get("scope") == "source-region":
            rx0, ry0, rx1, ry1 = job["regionBbox"]
            width, height = job["sourceSize"]
            normalized[-1]["regionBbox"] = list(bbox)
            normalized[-1]["bbox"] = [
                math.floor((rx0+x0*(rx1-rx0)/1000)*1000/width),
                math.floor((ry0+y0*(ry1-ry0)/1000)*1000/height),
                math.ceil((rx0+x1*(rx1-rx0)/1000)*1000/width),
                math.ceil((ry0+y1*(ry1-ry0)/1000)*1000/height),
            ]
    notes = payload.get("notes", "")
    if not isinstance(notes, str):
        raise ItemModelWorkerError(f"{job.get('jobId')}: notes must be a string")
    return {
        "schemaVersion": "item-segmentation-result-v1",
        "jobId": job["jobId"],
        "runId": job["runId"],
        "itemId": job["itemId"],
        "model": model_id,
        "maskModel": None,
        "warnings": ["model_count_mismatch"] if count_mismatch else [],
        "reportedInstanceCount": reported_count,
        "inputHashes": {"rgba": job["inputs"]["rgba"]["sha256"]},
        "decision": {
            "instanceCount": count,
            "confidence": _number(payload.get("confidence"), "confidence"),
            "instances": normalized,
            "notes": notes,
        },
    }


def _pixel_box(box: Sequence[int], width: int, height: int) -> list[float]:
    x0, y0, x1, y1 = box
    return [
        max(0.0, min(float(width - 1), x0 * width / 1000)),
        max(0.0, min(float(height - 1), y0 * height / 1000)),
        max(1.0, min(float(width), x1 * width / 1000)),
        max(1.0, min(float(height), y1 * height / 1000)),
    ]


def _load_sam2(model_id: str, device: str, local_files_only: bool, revision: str | None = None) -> tuple[Any, Any, Any]:
    try:
        import torch
        from transformers import Sam2Model, Sam2Processor
    except ImportError as exc:
        raise ItemModelWorkerError(
            "SAM2 dependencies are missing; run setup_item_model_runtime.py and use its Python"
        ) from exc
    if device == "cuda" and not torch.cuda.is_available():
        raise ItemModelWorkerError("--device cuda was requested but CUDA is unavailable")
    target = torch.device("cpu" if device == "cpu" or not torch.cuda.is_available() else "cuda")
    try:
        processor = Sam2Processor.from_pretrained(model_id, local_files_only=local_files_only, revision=revision)
        model = Sam2Model.from_pretrained(
            model_id,
            torch_dtype=torch.float32,
            local_files_only=local_files_only,
            revision=revision,
        ).to(target)
    except Exception as exc:
        mode = "local cache" if local_files_only else "checkpoint download or local cache"
        raise ItemModelWorkerError(f"cannot load SAM2 model {model_id} from {mode}: {exc}") from exc
    model.eval()
    return model, processor, target


def _refine_masks(
    results: list[dict[str, Any]],
    jobs_by_id: Mapping[str, Mapping[str, Any]],
    run_roots: Mapping[str, Path],
    *,
    output_path: Path,
    mask_model_id: str,
    device: str,
    local_files_only: bool,
    revision: str | None = None,
) -> None:
    targets = list(results)
    if not targets:
        return
    model, processor, target_device = _load_sam2(mask_model_id, device, local_files_only, revision)
    staging = Path(tempfile.mkdtemp(prefix=f".{output_path.stem}-masks-", dir=output_path.parent))
    generated: list[tuple[dict[str, Any], Path, str]] = []
    try:
        import torch

        for result in targets:
            started = time.monotonic()
            if torch.cuda.is_available():
                torch.cuda.reset_peak_memory_stats()
            job = jobs_by_id[result["jobId"]]
            source_path = _verified_input(run_roots[result["jobId"]], job, "lightComposite")
            with Image.open(source_path) as opened:
                opened.load()
                image = opened.convert("RGB")
            boxes = [
                _pixel_box(instance.get("regionBbox", instance["bbox"]), image.width, image.height)
                for instance in result["decision"]["instances"]
            ]
            try:
                processed = []
                for offset in range(0, len(boxes), 8):
                    inputs = processor(images=image, input_boxes=[boxes[offset:offset+8]], return_tensors="pt").to(target_device)
                    with torch.inference_mode():
                        outputs = model(**inputs, multimask_output=False)
                    processed.extend(processor.post_process_masks(
                        outputs.pred_masks.cpu(), inputs["original_sizes"].cpu())[0])
                    del outputs, inputs
            except Exception as exc:
                raise ItemModelWorkerError(f"SAM2 inference failed for {result['jobId']}: {exc}") from exc
            if len(processed) != len(boxes):
                raise ItemModelWorkerError(f"SAM2 returned the wrong mask count for {result['jobId']}")
            for index, mask_tensor in enumerate(processed):
                mask = mask_tensor.squeeze().detach().cpu()
                mask_bytes = (mask > 0).to(torch.uint8).mul(255).numpy().tobytes()
                mask_image = Image.frombytes("L", image.size, mask_bytes)
                if job.get("scope") == "source-region":
                    full = Image.new("L", tuple(job["sourceSize"]), 0)
                    full.paste(mask_image, tuple(job["regionBbox"][:2]))
                    mask_image = full
                filename = f"{result['jobId']}-instance-{index + 1:02d}.png"
                path = staging / filename
                mask_image.save(path)
                generated.append((result["decision"]["instances"][index], path, filename))
            result["maskModel"] = mask_model_id
            result["maskInference"] = {"seconds": round(time.monotonic()-started,3),
                "peakAllocatedMiB": round(torch.cuda.max_memory_allocated()/1048576,1) if torch.cuda.is_available() else None}

        digest = sha256()
        for _instance, path, filename in sorted(generated, key=lambda entry: entry[2]):
            digest.update(filename.encode("utf-8"))
            digest.update(bytes.fromhex(digest_file(path)))
        final_dir = output_path.parent / f"{output_path.stem}-masks-{digest.hexdigest()[:12]}"
        if final_dir.exists():
            for _instance, path, filename in generated:
                existing = final_dir / filename
                if not existing.is_file() or digest_file(existing) != digest_file(path):
                    raise ItemModelWorkerError(f"existing mask evidence conflicts with {final_dir}")
            shutil.rmtree(staging)
        else:
            staging.replace(final_dir)
        for instance, path, filename in generated:
            final = final_dir / filename
            with Image.open(final) as opened:
                mask_width, mask_height = opened.size
            instance["mask"] = {
                "path": final.relative_to(output_path.parent).as_posix(),
                "sha256": digest_file(final),
                "width": mask_width,
                "height": mask_height,
            }
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def main() -> int:
    args = _parser().parse_args()
    output = args.out.expanduser().resolve()
    jobs_path = args.jobs.expanduser().resolve()
    try:
        if args.max_new_tokens < 64:
            raise ItemModelWorkerError("max-new-tokens must be at least 64")
        if output.suffix.lower() != ".jsonl":
            raise ItemModelWorkerError("model results output must use a .jsonl filename")
        if output == jobs_path:
            raise ItemModelWorkerError("results cannot replace the jobs file")
        if output.exists() and not args.force:
            raise ItemModelWorkerError("output exists; pass --force to replace it")
        jobs = read_json_records(jobs_path)
        expected_schema = (
            "item-classification-job-v1" if args.task == "classify" else "item-segmentation-job-v1"
        )
        if not jobs:
            raise ItemModelWorkerError("jobs file contains no work")
        jobs_by_id: dict[str, Mapping[str, Any]] = {}
        run_roots: dict[str, Path] = {}
        explicit_root = args.run_root.expanduser().resolve() if args.run_root else None
        for job in jobs:
            job_id = job.get("jobId")
            if job.get("schemaVersion") != expected_schema:
                raise ItemModelWorkerError(f"every job must use {expected_schema}")
            if not isinstance(job_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", job_id) or job_id in jobs_by_id:
                raise ItemModelWorkerError("job IDs must be non-empty and unique")
            jobs_by_id[job_id] = job
            run_roots[job_id] = _find_run_root(job, jobs_path, explicit_root)
            for input_name in job.get("inputs", {}):
                _verified_input(run_roots[job_id], job, str(input_name))
        dry_payload = {
            "status": "dry-run",
            "task": args.task,
            "jobCount": len(jobs),
            "model": args.model,
            "maskModel": args.mask_model if args.task == "segment" else "none",
            "device": args.device,
            "localFilesOnly": args.local_files_only,
            "output": str(output),
            "downloadsMayOccur": not args.local_files_only,
        }
        if args.dry_run:
            print(json.dumps(dry_payload, ensure_ascii=False, indent=2))
            return 0

        os.environ.setdefault("HF_HOME", str((SKILL_ROOT / ".local" / "model-cache").resolve()))
        os.environ.setdefault("HF_HUB_CACHE", str(Path(os.environ["HF_HOME"]) / "hub"))
        model = processor = None
        results: list[dict[str, Any]] = []
        evidence = output.parent / f"{output.stem}-raw"
        evidence.mkdir(parents=True, exist_ok=True)
        checkpoints = output.parent / f"{output.stem}-checkpoints"
        checkpoints.mkdir(exist_ok=True)
        for index, job in enumerate(jobs, start=1):
            started = time.monotonic()
            root = run_roots[job["jobId"]]
            cache_key = sha256(json.dumps({"job":job,"model":args.model,"revision":args.revision,
                "worker":digest_file(Path(__file__)),"tokens":args.max_new_tokens,"device":args.device},sort_keys=True).encode()).hexdigest()
            saved = checkpoints / f"{job['jobId']}.json"
            if saved.exists():
                cached = json.loads(saved.read_text(encoding="utf-8"))
                if cached.get("key") == cache_key:
                    result = cached["result"]
                    if sha256(json.dumps(result,sort_keys=True).encode()).hexdigest() != cached.get("resultSha256"):
                        raise ItemModelWorkerError("cached model result hash mismatch")
                    results.append(result)
                    print(json.dumps({"status":"reused","completed":index,"total":len(jobs),"jobId":job["jobId"]}),file=os.sys.stderr,flush=True)
                    continue
            if model is None:
                model, processor = _load_qwen(args.model, args.device, args.local_files_only, args.revision)
            if args.task == "classify":
                light_path = _verified_input(root, job, "lightComposite")
                dark_path = _verified_input(root, job, "darkComposite")
                with Image.open(light_path) as light_opened, Image.open(dark_path) as dark_opened:
                    light_opened.load()
                    dark_opened.load()
                    images = [light_opened.convert("RGB"), dark_opened.convert("RGB")]
                prompt = (
                    str(job["prompt"])
                    + " The two images show the same sprite on light and dark backgrounds. "
                    + "Return one object, never an array or Markdown."
                )
                raw = _generate_json(model, processor, images, prompt, args.max_new_tokens,
                                     evidence / f"{job['jobId']}.txt", classification_schema(job))
                (evidence / f"{job['jobId']}.json").write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
                result = _classification_result(job, raw, args.model)
            else:
                light_path = _verified_input(root, job, "lightComposite")
                with Image.open(light_path) as opened:
                    opened.load()
                    image = opened.convert("RGB")
                with Image.open(_verified_input(root, job, "sheetContext")) as opened:
                    images = [image, opened.convert("RGB")]
                prompt = (
                    str(job["prompt"])
                    + " Each instances entry MUST be an array [label,x0,y0,x1,y1,confidence]. "
                    + "Return one object, never an array or Markdown."
                )
                raw = _generate_json(model, processor, images, prompt, args.max_new_tokens,
                                     evidence / f"{job['jobId']}.txt")
                (evidence / f"{job['jobId']}.json").write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
                result = _segmentation_result(job, raw, args.model)
            results.append(result)
            result["modelRevision"] = getattr(model.config, "_commit_hash", None) or args.revision
            result["maskRevision"] = args.mask_revision if args.task == "segment" else None
            import torch
            result["inference"] = {"seconds":round(time.monotonic()-started,3),
                "peakAllocatedMiB":round(torch.cuda.max_memory_allocated()/1048576,1) if torch.cuda.is_available() else None}
            temporary_cache = saved.with_suffix(".tmp")
            temporary_cache.write_text(json.dumps({"key":cache_key,"result":result,
                "resultSha256":sha256(json.dumps(result,sort_keys=True).encode()).hexdigest()}),encoding="utf-8")
            temporary_cache.replace(saved)
            print(
                json.dumps(
                    {"status": "progress", "completed": index, "total": len(jobs), "jobId": job["jobId"]}
                ),
                file=os.sys.stderr,
            )

        del model
        del processor
        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass
        if args.task == "segment" and args.mask_model != "none":
            output.parent.mkdir(parents=True, exist_ok=True)
            _refine_masks(
                results,
                jobs_by_id,
                run_roots,
                output_path=output,
                mask_model_id=args.mask_model,
                device=args.device,
                local_files_only=args.local_files_only,
                revision=args.mask_revision,
            )
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(output.suffix + ".tmp")
        temporary.write_text(
            "".join(json.dumps(result, ensure_ascii=False) + "\n" for result in results),
            encoding="utf-8",
        )
        temporary.replace(output)
    except (ItemModelWorkerError, ItemSegmentationError, OSError, KeyError) as exc:
        print(json.dumps({"status": "operational-error", "errors": [str(exc)]}, ensure_ascii=False))
        return 3
    print(
        json.dumps(
            {
                "status": "pass",
                "task": args.task,
                "resultCount": len(results),
                "model": args.model,
                "maskModel": args.mask_model if args.task == "segment" else "none",
                "output": str(output),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
