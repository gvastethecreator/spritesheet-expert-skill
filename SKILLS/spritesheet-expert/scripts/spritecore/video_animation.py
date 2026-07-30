"""Provider-boundary and deterministic decoding for first-frame video animation."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import re
from typing import Any, Mapping

from jsonschema import Draft202012Validator
from PIL import Image

from spritecore.contracts import ContractError, load_sprite_request, normalize_contract
from spritecore.paths import PathSafetyError, resolve_run_path


class VideoAnimationError(ValueError):
    """Raised before mutation when provider or video evidence is not acceptable."""


_JOB_SCHEMA = (
    Path(__file__).resolve().parents[2]
    / "references"
    / "schemas"
    / "grok-video-animation-job-v1.schema.json"
)
_VIDEO_EXTENSIONS = {".mp4", ".webm", ".mov", ".m4v"}
_MAX_DECODED_FRAMES = 900
_MAX_DIMENSION = 4096


@dataclass(frozen=True, slots=True)
class PreparedVideoJob:
    run_dir: Path
    prompt_path: Path
    job_path: Path
    prompt_text: str
    job: dict[str, Any]
    source_hashes: Mapping[str, str]
    force: bool


@dataclass(frozen=True, slots=True)
class VideoIngestResult:
    run_dir: Path
    raw_path: Path
    report_path: Path
    provenance_path: Path
    raw_bytes: bytes
    report: dict[str, Any]
    provenance: dict[str, Any]
    source_hashes: Mapping[str, str]
    force: bool


def _digest(content: bytes) -> str:
    return sha256(content).hexdigest()


def _file_record(path: Path, *, relative_to: Path | None = None) -> dict[str, Any]:
    content = path.read_bytes()
    stored_path = (
        path.relative_to(relative_to).as_posix() if relative_to is not None else str(path)
    )
    return {"path": stored_path, "sha256": _digest(content), "size_bytes": len(content)}


def _inside(root: Path, candidate: Path, label: str) -> Path:
    root = root.expanduser().resolve()
    candidate = candidate.expanduser().resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise VideoAnimationError(f"{label} must stay inside repo root: {candidate}") from exc
    return candidate


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise VideoAnimationError(f"{label} is unreadable: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise VideoAnimationError(f"{label} must be a JSON object: {path}")
    return value


def _validate_job(job: Mapping[str, Any]) -> None:
    schema = json.loads(_JOB_SCHEMA.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema).iter_errors(job),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        rendered = "; ".join(
            f"{'.'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
            for error in errors
        )
        raise VideoAnimationError(f"invalid Grok video job: {rendered}")


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:48] or "sprite"


def _video_sampling_mode(state: str, entry: Mapping[str, Any]) -> str:
    workflows = {
        str(value).strip().lower()
        for value in entry.get("animation_workflows", [])
        if isinstance(value, str)
    }
    descriptor = " ".join(
        (
            state,
            str(entry.get("action") or ""),
            " ".join(sorted(workflows)),
        )
    ).lower()
    cyclic_workflow = any(
        "locomotion" in workflow
        or workflow in {"water-loop", "wind-ambient-loop", "idle-breath", "fighting-stance-idle"}
        for workflow in workflows
    )
    cyclic_motion = bool(
        re.search(r"(^|[^a-z])(walk|walking|run|running|sprint|swim|flying|fly|crawl)([^a-z]|$)", descriptor)
    )
    if bool(entry.get("loop", True)) and (cyclic_workflow or cyclic_motion):
        return "cyclic-half-open"
    return "bookended-inclusive"


def prepare_video_job(
    *,
    repo_root: Path,
    run_dir: Path,
    state: str,
    first_frame_name: str,
    duration_seconds: int = 6,
    force: bool = False,
) -> PreparedVideoJob:
    repo = Path(repo_root).expanduser().resolve()
    run_root = Path(run_dir).expanduser().resolve()
    if not repo.is_dir():
        raise VideoAnimationError(f"repo root does not exist: {repo}")
    if not run_root.is_dir():
        raise VideoAnimationError(f"run directory does not exist: {run_root}")
    _inside(repo, run_root, "run directory")
    try:
        first_frame = resolve_run_path(run_root, first_frame_name)
    except PathSafetyError as exc:
        raise VideoAnimationError(str(exc)) from exc
    _inside(repo, first_frame, "first frame")
    if not first_frame.is_file():
        raise VideoAnimationError(f"first frame does not exist: {first_frame_name}")
    if first_frame.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise VideoAnimationError("first frame must be PNG, JPEG, or WebP")
    try:
        with Image.open(first_frame) as opened:
            opened.verify()
        with Image.open(first_frame) as opened:
            width, height = opened.size
    except (OSError, ValueError) as exc:
        raise VideoAnimationError("first frame is not a decodable image") from exc
    if width < 1 or height < 1 or width > _MAX_DIMENSION or height > _MAX_DIMENSION:
        raise VideoAnimationError(
            f"first-frame dimensions must be between 1 and {_MAX_DIMENSION}: {(width, height)}"
        )

    request_path = run_root / "sprite-request.json"
    request = load_sprite_request(request_path).data
    request_record = _file_record(request_path, relative_to=run_root)
    if state not in request["states"]:
        raise VideoAnimationError(f"sprite request has no state {state!r}")
    entry = request["states"][state]
    requested_frames = int(entry["frames"])
    if requested_frames < 2:
        raise VideoAnimationError("video animation requires at least two requested frames")
    if duration_seconds not in {6, 10}:
        raise VideoAnimationError("Grok video duration must be 6 or 10 seconds")
    background = request.get("generation_background")
    if not isinstance(background, Mapping) or background.get("family") != "neutral":
        raise VideoAnimationError(
            "video animation requires a neutral generation_background in sprite-request.json"
        )

    job_dir = resolve_run_path(run_root, f"provider/grok-imagine/{state}")
    prompt_path = job_dir / "prompt.txt"
    job_path = job_dir / "job.json"
    collisions = [path for path in (prompt_path, job_path) if path.exists()]
    if collisions and not force:
        raise VideoAnimationError(
            "Grok video job already exists; pass --force to replace the prompt and job only"
        )

    first_record = _file_record(first_frame, relative_to=run_root)
    first_record.update({"width": width, "height": height})
    action = str(entry.get("action") or state).strip().rstrip(".")
    background_name = str(background["name"])
    background_hex = str(background["hex"])
    loop_text = "that returns naturally to the starting pose" if entry.get("loop", True) else "with a clean final settle"
    prompt_text = (
        f"Animate this exact full-body first frame as one continuous {duration_seconds}-second {action}, {loop_text}; use a locked camera, fixed framing and scale, stable character identity, and clear readable motion with no cuts, zooms, pans, text, extra objects, detached effects, motion blur, or cast shadows. "
        f"Keep the flat neutral {background_name} {background_hex} background perfectly unchanged across the full shot, keep every body part inside frame, and do not redesign the subject.\n"
    )
    prompt_bytes = prompt_text.encode("utf-8")
    prompt_record = {
        "path": prompt_path.relative_to(run_root).as_posix(),
        "sha256": _digest(prompt_bytes),
        "size_bytes": len(prompt_bytes),
    }
    sampling_mode = _video_sampling_mode(state, entry)
    run_label = _safe_slug(run_root.relative_to(repo).as_posix())
    output_rel = (
        Path(".scratch")
        / "agent-cli-delegation"
        / "grok-imagine"
        / "spritesheet-video"
        / f"{run_label}-{state}-{first_record['sha256'][:10]}-{prompt_record['sha256'][:10]}"
        / "result.json"
    ).as_posix()
    invocation_rel = str(Path(output_rel).parent / "invocation.json").replace("\\", "/")
    args = [
        "--mode",
        "video-from-image",
        "--repo",
        str(repo),
        "--prompt-file",
        str(prompt_path),
        "--source-file",
        str(first_frame),
        "--expected-videos",
        "1",
        "--timeout-ms",
        "1800000",
        "--output",
        output_rel,
        "--dry-run",
    ]
    job = {
        "version": 1,
        "kind": "sprite-grok-video-animation-job",
        "provider": "grok-imagine",
        "operation": "video-from-image",
        "repo_root": str(repo),
        "state": state,
        "duration_seconds": duration_seconds,
        "requested_frames": requested_frames,
        "loop": bool(entry.get("loop", True)),
        "sampling_mode": sampling_mode,
        "generation_background": {
            "family": "neutral",
            "name": background_name,
            "hex": background_hex,
        },
        "sprite_request": request_record,
        "first_frame": first_record,
        "prompt": prompt_record,
        "provider_output": {
            "result_path": output_rel,
            "invocation_path": invocation_rel,
            "expected_videos": 1,
        },
        "dry_run": {
            "skill": "$grok-imagine",
            "wrapper": "run-grok-imagine.mjs",
            "args": args,
            "real_run_ack_flag": "--ack-run",
        },
    }
    _validate_job(job)
    return PreparedVideoJob(
        run_dir=run_root,
        prompt_path=prompt_path,
        job_path=job_path,
        prompt_text=prompt_text,
        job=job,
        source_hashes={
            "sprite_request": request_record["sha256"],
            "first_frame": first_record["sha256"],
        },
        force=force,
    )


def uniform_sample_indices(
    total_frames: int,
    requested_frames: int,
    *,
    sampling_mode: str,
) -> list[int]:
    if requested_frames < 2:
        raise VideoAnimationError("requested frame count must be at least two")
    if total_frames < requested_frames:
        raise VideoAnimationError(
            f"video contains {total_frames} decoded frames but {requested_frames} are required"
        )
    if sampling_mode == "cyclic-half-open":
        indices = [(index * total_frames) // requested_frames for index in range(requested_frames)]
    elif sampling_mode == "bookended-inclusive":
        indices = [
            round(index * (total_frames - 1) / (requested_frames - 1))
            for index in range(requested_frames)
        ]
    else:
        raise VideoAnimationError(f"unsupported video sampling mode: {sampling_mode!r}")
    if len(set(indices)) != len(indices):
        raise VideoAnimationError("video sampling did not produce unique frame indices")
    return indices


def _reader_metadata(metadata: Any) -> tuple[tuple[int, int], float, float | None]:
    if not isinstance(metadata, Mapping):
        raise VideoAnimationError("video decoder returned invalid metadata")
    size = metadata.get("size")
    if (
        not isinstance(size, (list, tuple))
        or len(size) != 2
        or any(isinstance(value, bool) or not isinstance(value, int) for value in size)
    ):
        raise VideoAnimationError("video decoder metadata has no valid size")
    width, height = int(size[0]), int(size[1])
    if width < 1 or height < 1 or width > _MAX_DIMENSION or height > _MAX_DIMENSION:
        raise VideoAnimationError(
            f"decoded video dimensions must be between 1 and {_MAX_DIMENSION}: {(width, height)}"
        )
    fps = metadata.get("fps")
    if isinstance(fps, bool) or not isinstance(fps, (int, float)) or fps <= 0:
        raise VideoAnimationError("video decoder metadata has no valid fps")
    duration = metadata.get("duration")
    parsed_duration = float(duration) if isinstance(duration, (int, float)) and duration > 0 else None
    return (width, height), float(fps), parsed_duration


def _inspect_decoded_video(decoder: Any, video_path: Path) -> tuple[tuple[int, int], float, float | None, int]:
    reader = decoder.read_frames(str(video_path), pix_fmt="rgb24")
    try:
        try:
            metadata = next(reader)
        except StopIteration as exc:
            raise VideoAnimationError("video decoder returned no metadata") from exc
        size, fps, duration = _reader_metadata(metadata)
        expected_bytes = size[0] * size[1] * 3
        count = 0
        for payload in reader:
            if not isinstance(payload, (bytes, bytearray)) or len(payload) != expected_bytes:
                raise VideoAnimationError("video decoder returned a malformed RGB frame")
            count += 1
            if count > _MAX_DECODED_FRAMES:
                raise VideoAnimationError(
                    f"video exceeds the {_MAX_DECODED_FRAMES}-frame safety limit"
                )
    finally:
        close = getattr(reader, "close", None)
        if callable(close):
            close()
    if count < 1:
        raise VideoAnimationError("video decoder returned zero frames")
    return size, fps, duration, count


def _decode_selected(
    decoder: Any,
    video_path: Path,
    indices: list[int],
    expected_size: tuple[int, int],
    expected_total: int,
) -> dict[int, Image.Image]:
    wanted = set(indices)
    selected: dict[int, Image.Image] = {}
    reader = decoder.read_frames(str(video_path), pix_fmt="rgb24")
    try:
        try:
            metadata = next(reader)
        except StopIteration as exc:
            raise VideoAnimationError("video decoder returned no metadata on second pass") from exc
        size, _fps, _duration = _reader_metadata(metadata)
        if size != expected_size:
            raise VideoAnimationError("video decoder dimensions changed between passes")
        expected_bytes = size[0] * size[1] * 3
        count = 0
        for count, payload in enumerate(reader, start=1):
            if not isinstance(payload, (bytes, bytearray)) or len(payload) != expected_bytes:
                raise VideoAnimationError("video decoder returned a malformed RGB frame on second pass")
            index = count - 1
            if index in wanted:
                selected[index] = Image.frombytes("RGB", size, bytes(payload)).convert("RGBA")
    finally:
        close = getattr(reader, "close", None)
        if callable(close):
            close()
    if count != expected_total:
        raise VideoAnimationError("video decoder frame count changed between passes")
    missing = wanted - set(selected)
    if missing:
        raise VideoAnimationError(f"video decoder missed sampled frames: {sorted(missing)}")
    return selected


def _normalized_frame(image: Image.Image, target_size: tuple[int, int]) -> Image.Image:
    if image.size == target_size:
        return image.convert("RGBA")
    source_ratio = image.width / image.height
    target_ratio = target_size[0] / target_size[1]
    if abs(source_ratio - target_ratio) / target_ratio > 0.01:
        raise VideoAnimationError(
            f"video aspect ratio {image.size} does not match first frame {target_size}"
        )
    return image.convert("RGBA").resize(target_size, Image.Resampling.LANCZOS)


def _compose_grid(frames: list[Image.Image], columns: int, rows: int) -> bytes:
    if columns < 1 or rows < 1 or columns * rows < len(frames):
        raise VideoAnimationError(
            f"raw layout capacity {columns}x{rows} cannot hold {len(frames)} requested frames"
        )
    width, height = frames[0].size
    grid = Image.new("RGBA", (columns * width, rows * height), (0, 0, 0, 0))
    for index, frame in enumerate(frames):
        grid.alpha_composite(frame, ((index % columns) * width, (index // columns) * height))
    buffer = BytesIO()
    grid.save(buffer, format="PNG")
    return buffer.getvalue()


def _merged_provenance(
    run_dir: Path,
    request: Mapping[str, Any],
    *,
    state: str,
    raw_bytes: bytes,
    report_path: Path,
    prior: Mapping[str, Any] | None,
    force: bool,
) -> dict[str, Any]:
    accepted: list[dict[str, Any]] = []
    if prior is not None:
        for entry in prior["accepted_sources"]:
            if state in entry["states"]:
                if not force:
                    raise VideoAnimationError(
                        f"source provenance already covers {state!r}; pass --force to replace that state"
                    )
                continue
            accepted.append(dict(entry))
    accepted.append(
        {
            "path": f"raw/{state}.png",
            "sha256": _digest(raw_bytes),
            "size_bytes": len(raw_bytes),
            "states": [state],
            "source_type": "grok-imagine-video",
            "art_engine": "grok-imagine",
            "upstream_report": report_path.relative_to(run_dir).as_posix(),
        }
    )
    state_order = {name: index for index, name in enumerate(request["states"])}
    accepted.sort(
        key=lambda entry: min(
            (state_order.get(name, len(state_order)) for name in entry["states"]),
            default=len(state_order),
        )
    )
    coverage = [
        name
        for name in request["states"]
        if any(name in entry["states"] for entry in accepted)
    ]
    source_types = {
        str(entry.get("source_type") or "unknown") for entry in accepted
    }
    art_engines = {
        str(entry.get("art_engine") or "unknown") for entry in accepted
    }
    mixed = len(source_types) > 1 or len(art_engines) > 1
    final_source_type = "mixed" if mixed else next(iter(source_types))
    final_art_engine = "mixed" if mixed else next(iter(art_engines))
    provenance = {
        "version": 2,
        "kind": "sprite-source-provenance",
        "source_type": final_source_type,
        "art_engine": final_art_engine,
        "fixture": False,
        "verification_status": "verified",
        "accepted_sources": accepted,
        "state_coverage": coverage,
        "notes": "accepted through completed $grok-imagine video-from-image invocation and deterministic frame sampling",
        "license": "mixed-provider-terms" if mixed else "xAI-provider-terms",
    }
    return normalize_contract(provenance, expected_kind="source-provenance").to_dict()


def _prior_provenance_snapshot(path: Path) -> tuple[dict[str, Any] | None, str]:
    if not path.exists():
        return None, "<absent>"
    if not path.is_file():
        raise VideoAnimationError("source provenance path is not a regular file")
    try:
        content = path.read_bytes()
        payload = json.loads(content.decode("utf-8"))
        prior = normalize_contract(payload, expected_kind="source-provenance").to_dict()
    except (ContractError, OSError, UnicodeError, ValueError) as exc:
        raise VideoAnimationError(f"source provenance is unreadable: {exc}") from exc
    return prior, _digest(content)


def ingest_video(
    *,
    run_dir: Path,
    state: str,
    invocation_path: Path,
    job_name: str | None = None,
    force: bool = False,
    decoder: Any | None = None,
) -> VideoIngestResult:
    run_root = Path(run_dir).expanduser().resolve()
    if not run_root.is_dir():
        raise VideoAnimationError(f"run directory does not exist: {run_root}")
    job_name = job_name or f"provider/grok-imagine/{state}/job.json"
    try:
        job_path = resolve_run_path(run_root, job_name)
    except PathSafetyError as exc:
        raise VideoAnimationError(str(exc)) from exc
    job = _load_object(job_path, "Grok video job")
    _validate_job(job)
    if job["state"] != state:
        raise VideoAnimationError(
            f"job state {job['state']!r} does not match requested state {state!r}"
        )
    request_path = run_root / "sprite-request.json"
    request = load_sprite_request(request_path).data
    request_record = _file_record(request_path, relative_to=run_root)
    if request_record != job["sprite_request"]:
        raise VideoAnimationError("sprite-request.json changed after job preparation")
    if state not in request["states"]:
        raise VideoAnimationError(f"sprite request has no state {state!r}")
    if int(job["requested_frames"]) != int(request["states"][state]["frames"]):
        raise VideoAnimationError("job frame count no longer matches sprite-request.json")

    repo_root = Path(job["repo_root"]).expanduser().resolve()
    _inside(repo_root, run_root, "run directory")
    expected_invocation = (repo_root / job["provider_output"]["invocation_path"]).resolve()
    supplied_invocation = Path(invocation_path).expanduser().resolve()
    if supplied_invocation != expected_invocation:
        raise VideoAnimationError(
            f"invocation path does not match job: expected {expected_invocation}"
        )
    _inside(repo_root, supplied_invocation, "invocation")
    invocation = _load_object(supplied_invocation, "Grok invocation")
    if invocation.get("provider") != "grok-imagine" or invocation.get("mode") != "video-from-image":
        raise VideoAnimationError("invocation is not a grok-imagine video-from-image run")
    if invocation.get("status") != "completed" or invocation.get("exitCode") != 0:
        raise VideoAnimationError("Grok invocation did not complete successfully")
    if Path(str(invocation.get("cwd", ""))).resolve() != repo_root:
        raise VideoAnimationError("invocation cwd does not match the job repo root")

    prompt_path = resolve_run_path(run_root, job["prompt"]["path"])
    first_frame_path = resolve_run_path(run_root, job["first_frame"]["path"])
    if not prompt_path.is_file() or not first_frame_path.is_file():
        raise VideoAnimationError("job prompt or exact first frame is missing")
    prompt_record = _file_record(prompt_path, relative_to=run_root)
    first_record = _file_record(first_frame_path, relative_to=run_root)
    if prompt_record["sha256"] != job["prompt"]["sha256"]:
        raise VideoAnimationError("Grok prompt changed after job preparation")
    if first_record["sha256"] != job["first_frame"]["sha256"]:
        raise VideoAnimationError("exact first frame changed after job preparation")
    if Path(str(invocation.get("promptFile", ""))).resolve() != prompt_path:
        raise VideoAnimationError("invocation promptFile does not match the prepared prompt")

    enforcement = invocation.get("enforcement")
    if not isinstance(enforcement, Mapping):
        raise VideoAnimationError("invocation enforcement evidence is missing")
    source_files = enforcement.get("sourceFiles")
    resolved_sources = (
        [Path(str(value)).resolve() for value in source_files]
        if isinstance(source_files, list)
        else []
    )
    if (
        enforcement.get("operation") != "video-from-image"
        or enforcement.get("expectedImages") != 0
        or enforcement.get("expectedVideos") != 1
        or resolved_sources != [first_frame_path]
    ):
        raise VideoAnimationError("invocation enforcement does not bind the exact first frame and one video")

    validation = invocation.get("resultValidation")
    images = validation.get("images") if isinstance(validation, Mapping) else None
    videos = validation.get("videos") if isinstance(validation, Mapping) else None
    if not isinstance(validation, Mapping) or validation.get("ok") is not True:
        raise VideoAnimationError("provider result validation did not pass")
    if not isinstance(videos, list) or len(videos) != 1:
        raise VideoAnimationError("provider result must contain exactly one accepted video")
    if not isinstance(images, list) or images:
        raise VideoAnimationError("provider result must contain exactly zero accepted images")
    result_path = (repo_root / job["provider_output"]["result_path"]).resolve()
    if not result_path.is_file():
        raise VideoAnimationError("provider result JSON named by the job is missing")
    expected_media_dir = result_path.parent / "media"
    video_path = Path(str(videos[0])).expanduser().resolve()
    if video_path.parent != expected_media_dir.resolve():
        raise VideoAnimationError("accepted video is outside the job media directory")
    if video_path.stem != "video-01" or video_path.suffix.lower() not in _VIDEO_EXTENSIONS:
        raise VideoAnimationError("accepted video must be the wrapper-owned media/video-01 file")
    if not video_path.is_file() or video_path.stat().st_size < 1:
        raise VideoAnimationError("accepted provider video is missing or empty")

    raw_path = resolve_run_path(run_root, f"raw/{state}.png")
    report_path = resolve_run_path(
        run_root, f"provider/grok-imagine/{state}/video-source.json"
    )
    provenance_path = run_root / "source-provenance.json"
    if not force and (raw_path.exists() or report_path.exists()):
        raise VideoAnimationError(
            f"video-derived source for {state!r} already exists; pass --force to replace known outputs"
        )

    if decoder is None:
        try:
            import imageio_ffmpeg as decoder  # type: ignore[no-redef]
        except ImportError as exc:
            raise VideoAnimationError(
                "video ingestion requires imageio-ffmpeg; install scripts/requirements-video.txt"
            ) from exc
    decoded_size, fps, duration, total_frames = _inspect_decoded_video(decoder, video_path)
    sampling_mode = str(job.get("sampling_mode") or _video_sampling_mode(state, request["states"][state]))
    indices = uniform_sample_indices(
        total_frames,
        int(job["requested_frames"]),
        sampling_mode=sampling_mode,
    )
    selected = _decode_selected(decoder, video_path, indices, decoded_size, total_frames)
    with Image.open(first_frame_path) as opened:
        opened.load()
        exact_first = opened.convert("RGBA")
    if exact_first.size != (job["first_frame"]["width"], job["first_frame"]["height"]):
        raise VideoAnimationError("exact first-frame dimensions changed after job preparation")
    frames = [_normalized_frame(selected[index], exact_first.size) for index in indices]
    frames[0] = exact_first.copy()
    raw_layout = request["states"][state].get("raw_layout")
    if not isinstance(raw_layout, Mapping):
        raise VideoAnimationError(f"state {state!r} has no raw_layout")
    raw_bytes = _compose_grid(
        frames,
        int(raw_layout["columns"]),
        int(raw_layout["rows"]),
    )
    video_record = _file_record(video_path)
    invocation_record = _file_record(supplied_invocation)
    result_record = _file_record(result_path)
    job_record = _file_record(job_path, relative_to=run_root)
    prior_provenance, prior_provenance_hash = _prior_provenance_snapshot(
        provenance_path
    )
    output_record = {
        "path": raw_path.relative_to(run_root).as_posix(),
        "sha256": _digest(raw_bytes),
        "size_bytes": len(raw_bytes),
        "width": exact_first.width * int(raw_layout["columns"]),
        "height": exact_first.height * int(raw_layout["rows"]),
    }
    report = {
        "version": 1,
        "kind": "sprite-grok-video-source",
        "status": "pass",
        "provider": "grok-imagine",
        "operation": "video-from-image",
        "state": state,
        "sprite_request": request_record,
        "job": job_record,
        "prompt": prompt_record,
        "invocation": invocation_record,
        "provider_result": result_record,
        "first_frame": {**first_record, "width": exact_first.width, "height": exact_first.height},
        "video": video_record,
        "decoder": {
            "name": "imageio-ffmpeg",
            "version": str(getattr(decoder, "__version__", "unknown")),
        },
        "decoded": {
            "width": decoded_size[0],
            "height": decoded_size[1],
            "fps": fps,
            "duration_seconds": duration,
            "frame_count": total_frames,
        },
        "sampled_video_indices": indices,
        "sampling_mode": sampling_mode,
        "sampled_timestamps_seconds": [round(index / fps, 6) for index in indices],
        "exact_first_frame_preserved": True,
        "output": output_record,
    }
    provenance = _merged_provenance(
        run_root,
        request,
        state=state,
        raw_bytes=raw_bytes,
        report_path=report_path,
        prior=prior_provenance,
        force=force,
    )
    source_hashes = {
        "sprite_request": request_record["sha256"],
        "job": job_record["sha256"],
        "prompt": prompt_record["sha256"],
        "first_frame": first_record["sha256"],
        "invocation": invocation_record["sha256"],
        "provider_result": result_record["sha256"],
        "video": video_record["sha256"],
        "prior_provenance": prior_provenance_hash,
    }
    return VideoIngestResult(
        run_dir=run_root,
        raw_path=raw_path,
        report_path=report_path,
        provenance_path=provenance_path,
        raw_bytes=raw_bytes,
        report=report,
        provenance=provenance,
        source_hashes=source_hashes,
        force=force,
    )


def revalidate_video_sources(result: VideoIngestResult) -> None:
    report = result.report
    current = {
        "sprite_request": _digest(
            (result.run_dir / report["sprite_request"]["path"]).read_bytes()
        ),
        "job": _digest((result.run_dir / report["job"]["path"]).read_bytes()),
        "prompt": _digest((result.run_dir / report["prompt"]["path"]).read_bytes()),
        "first_frame": _digest(
            (result.run_dir / report["first_frame"]["path"]).read_bytes()
        ),
        "invocation": _digest(Path(report["invocation"]["path"]).read_bytes()),
        "provider_result": _digest(
            Path(report["provider_result"]["path"]).read_bytes()
        ),
        "video": _digest(Path(report["video"]["path"]).read_bytes()),
        "prior_provenance": (
            _digest(result.provenance_path.read_bytes())
            if result.provenance_path.is_file()
            else "<absent>"
        ),
    }
    if current != dict(result.source_hashes):
        raise VideoAnimationError("provider or first-frame sources changed before commit")
    if not result.force and (result.raw_path.exists() or result.report_path.exists()):
        raise VideoAnimationError("video-derived outputs appeared before commit")


def revalidate_prepared_sources(prepared: PreparedVideoJob) -> None:
    current = {
        "sprite_request": _digest((prepared.run_dir / "sprite-request.json").read_bytes()),
        "first_frame": _digest(
            (prepared.run_dir / prepared.job["first_frame"]["path"]).read_bytes()
        ),
    }
    if current != dict(prepared.source_hashes):
        raise VideoAnimationError("sprite request or first frame changed before job commit")


__all__ = [
    "PreparedVideoJob",
    "VideoAnimationError",
    "VideoIngestResult",
    "ingest_video",
    "prepare_video_job",
    "revalidate_prepared_sources",
    "revalidate_video_sources",
    "uniform_sample_indices",
]
