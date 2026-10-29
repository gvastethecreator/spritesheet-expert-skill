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
_VIDEO_SOURCE_SCHEMA = (
    Path(__file__).resolve().parents[2]
    / "references"
    / "schemas"
    / "video-source-v1.schema.json"
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
    additional_outputs: tuple[tuple[Path, bytes], ...] = ()


@dataclass(frozen=True, slots=True)
class FrameSignature:
    """Small deterministic pose descriptor used for adaptive video sampling."""

    rgb: bytes
    mask: bytes
    foreground_ratio: float
    center_x: float
    center_y: float
    sharpness: float
    source_edge_foreground_ratio: float
    bbox_width_ratio: float
    bbox_height_ratio: float
    core_bbox_height_ratio: float


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


def _validate_video_source_report(report: Mapping[str, Any]) -> None:
    schema = json.loads(_VIDEO_SOURCE_SCHEMA.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema).iter_errors(report),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        rendered = "; ".join(
            f"{'.'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
            for error in errors
        )
        raise VideoAnimationError(f"invalid video source report: {rendered}")


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


def _workflow_names(entry: Mapping[str, Any]) -> set[str]:
    return {
        str(value).strip().lower()
        for value in entry.get("animation_workflows", [])
        if isinstance(value, str)
    }


def _video_motion_lock(entry: Mapping[str, Any]) -> str:
    workflows = _workflow_names(entry)
    if "gesture-loop" in workflows:
        return (
            " Keep the pelvis, both legs, knees, ankles, both feet, and the contact footprint "
            "pixel-for-pixel fixed in their first-frame positions for the entire video: no step, "
            "weight shift, hip translation, knee bend, ankle turn, foot rotation, foot slide, body "
            "sway, or root travel. Only the waving shoulder, arm, wrist, and hand may perform the "
            "gesture; keep torso and head motion minimal."
        )
    if "front-fps-creature-locomotion" in workflows:
        return (
            " Preserve the full-frontal FPS view, fixed ground line, apparent scale, body center, "
            "and camera for one complete in-place movement cycle. Use two clearly different and "
            "opposite active poses driven by the creature's declared anatomy: limbs, wings, tail, "
            "or lower body may change pose as appropriate, but never replace that motion with a "
            "generic biped mirror, whole-body side sway, three-quarter turn, top-down tilt, or "
            "body scaling. Return through the exact supplied idle anchor between active poses."
        )
    if "front-fps-creature-attack" in workflows:
        return (
            " Preserve the full-frontal FPS view, fixed ground line or hover center, apparent scale, "
            "body center, and camera. Build threat through a compact anticipation and a clear anatomical "
            "contact pose, not through body growth or camera depth. Keep support anatomy stable unless the "
            "action explicitly names it; return to the exact supplied idle anchor after contact."
        )
    if "sideview-locomotion" in workflows:
        return (
            " Preserve the side-view ground line and animate one complete in-place locomotion "
            "cycle with two unmistakably opposite anatomical contact phases. Frame 0 starts with "
            "the reference support leg planted. At the midpoint, that same leg and foot must be "
            "visibly lifted while the other anatomical leg is extended forward and planted as the "
            "sole support foot. Show a clear leg pass/crossover, near-leg versus far-leg depth swap, "
            "and opposite arm counter-swing between those contacts. Never repeat the same support "
            "limb on both contacts, never mirror the whole character, and keep the pelvis centered "
            "without forward root travel or foot sliding."
        )
    return ""


def _video_prompt_contract(
    request: Mapping[str, Any],
    state: str,
    entry: Mapping[str, Any],
) -> dict[str, Any]:
    workflows = _workflow_names(entry)
    creature_motion = request.get("creature_motion")
    is_front_creature = bool(
        workflows
        & {"front-fps-creature-locomotion", "front-fps-creature-attack"}
    )
    if is_front_creature and not isinstance(creature_motion, Mapping):
        raise VideoAnimationError(
            f"state {state!r} requires creature_motion before Grok video preparation"
        )

    creature = creature_motion if isinstance(creature_motion, Mapping) else {}
    anatomy = str(creature.get("anatomy") or "unspecified").strip().lower()
    locomotion = str(creature.get("locomotion") or "unspecified").strip().lower()
    camera = str(creature.get("camera") or "unspecified").strip().lower()
    movement_source = str(creature.get("movement_source") or "").strip()
    attack_source = str(creature.get("attack_source") or "").strip()
    if is_front_creature and camera != "front-fps":
        raise VideoAnimationError(
            f"state {state!r} uses a front-FPS workflow but creature_motion.camera is {camera!r}"
        )
    if "front-fps-creature-locomotion" in workflows and not movement_source:
        raise VideoAnimationError(
            f"state {state!r} requires creature_motion.movement_source"
        )
    if "front-fps-creature-attack" in workflows and not attack_source:
        raise VideoAnimationError(
            f"state {state!r} requires creature_motion.attack_source"
        )

    configured = entry.get("video_prompt")
    configured = configured if isinstance(configured, Mapping) else {}
    motion_window_seconds = float(configured.get("motion_window_seconds", 1.8))
    if not 0.5 <= motion_window_seconds <= 4.0:
        raise VideoAnimationError(
            f"states.{state}.video_prompt.motion_window_seconds must be between 0.5 and 4.0"
        )
    edge_margin_ratio = float(configured.get("edge_margin_ratio", 0.12))
    if not 0.08 <= edge_margin_ratio <= 0.30:
        raise VideoAnimationError(
            f"states.{state}.video_prompt.edge_margin_ratio must be between 0.08 and 0.30"
        )
    motion_plane = str(configured.get("motion_plane", "image-plane")).strip().lower()
    if motion_plane not in {"image-plane", "depth-allowed"}:
        raise VideoAnimationError(
            f"states.{state}.video_prompt.motion_plane must be image-plane or depth-allowed"
        )

    later_motion = (
        "Later motion may repeat only that same stable action."
        if bool(entry.get("loop", True))
        else "After recovery, hold the exact supplied idle for the rest of the video."
    )
    if "front-fps-creature-locomotion" in workflows:
        phase_semantics = ["exact-idle", "phase-a", "exact-idle", "phase-b"]
        allowed_motion = movement_source
        timing = (
            f"Start in the exact supplied idle. Complete one readable in-place cycle within the first "
            f"{motion_window_seconds:g} seconds: phase A, exact idle pass, phase B, exact idle recovery. "
            f"{later_motion}"
        )
    elif "front-fps-creature-attack" in workflows:
        phase_semantics = ["exact-idle", "anticipation", "contact", "exact-idle"]
        allowed_motion = attack_source
        timing = (
            f"Start in the exact supplied idle. Complete one attack within the first "
            f"{motion_window_seconds:g} seconds: compact anticipation, clear threatening contact, "
            f"exact idle recovery. {later_motion}"
        )
    else:
        phase_semantics = []
        allowed_motion = ""
        timing = ""

    return {
        "anatomy": anatomy,
        "locomotion": locomotion,
        "camera": camera,
        "workflow": sorted(workflows),
        "allowed_motion": allowed_motion,
        "motion_plane": motion_plane,
        "motion_window_seconds": motion_window_seconds,
        "edge_margin_ratio": edge_margin_ratio,
        "phase_semantics": phase_semantics,
        "pose_transition_policy": "articulated-pose-only",
        "root_policy": "stationary-image-plane-anchor",
        "timing": timing,
    }


def _video_creature_lock(contract: Mapping[str, Any]) -> str:
    allowed_motion = str(contract.get("allowed_motion") or "").strip()
    if not allowed_motion:
        return ""
    anatomy = str(contract.get("anatomy") or "creature")
    locomotion = str(contract.get("locomotion") or "custom")
    plane = str(contract.get("motion_plane") or "image-plane")
    margin_percent = round(float(contract.get("edge_margin_ratio", 0.12)) * 100)
    plane_rule = (
        "Motion stays on the same flat 2D image plane. Interpret any phrase such as "
        "'toward the player' as pose readability only: no depth translation, foreshortening, "
        "perspective enlargement, giant foreground limb, or body approach."
        if plane == "image-plane"
        else "Depth motion is allowed only when the action text explicitly names it."
    )
    return (
        f"SUBJECT TYPE: {anatomy} creature; locomotion: {locomotion}.\n"
        f"ONLY MOTION DRIVER: {allowed_motion}. Do not substitute generic biped motion, a mirrored pose, "
        "or whole-body deformation.\n"
        "POSE MECHANICS: animate with clean articulated pose changes only. Preserve every bone or segment "
        "length, limb thickness, body volume, topology, and left/right identity. No mirror-flip substitute, "
        "liquify, rubber deformation, squash-and-stretch, shrinking, growing, or cross-fade into a new drawing.\n"
        "DRIVER SCALE LOCK: moving hands, feet, jaws, wings, claws, or tendrils keep their exact palm, digit, "
        "segment, and tip lengths. Move them through the declared joints; never enlarge the moving part to imply "
        "depth, impact, or threat.\n"
        "ROOT LOCK: keep the registered body root and average subject center stationary on the image plane. "
        "Locomotion is in place; an attack may lean or extend only through the declared joints, never by moving "
        "or scaling the whole creature.\n"
        "NON-DRIVER LOCK: anatomy not named by the motion driver remains structurally stable and may use only "
        "small physically connected secondary motion.\n"
        "CANDIDATE READABILITY: hold each useful phase as a sharp recognizable pose for several source frames. "
        "Avoid twitching, jitter, motion blur, rapid oscillation, and deformed transitional smears.\n"
        f"MOTION PLANE: {plane_rule}\n"
        f"FRAME SAFETY: preserve at least the existing empty border, target {margin_percent}% clear space "
        "from every source edge, and keep every limb, wing, weapon, tail, and effect fully visible."
    )


def _video_identity_lock(request: Mapping[str, Any]) -> str:
    creature_motion = request.get("creature_motion")
    preserve: list[str] = []
    reject: list[str] = []
    if isinstance(creature_motion, Mapping):
        preserve = [str(value).strip() for value in creature_motion.get("preserve", []) if str(value).strip()]
        reject = [str(value).strip() for value in creature_motion.get("reject", []) if str(value).strip()]
    covered_preserve = {
        "exact approved identity",
        "full frontal orientation",
        "head and torso scale",
        "body volume",
        "limb count",
        "palette and surface markings",
    }
    covered_reject = {
        "camera movement",
        "three-quarter rotation",
        "top-down tilt",
        "whole-body side sway",
        "body scaling",
        "extra or missing limbs",
        "identity morphing",
        "cropped anatomy",
    }
    preserve = [value for value in preserve if value.lower() not in covered_preserve]
    reject = [value for value in reject if value.lower() not in covered_reject]
    combined_reject = " ".join(reject).lower()
    combined_preserve = " ".join(preserve).lower()
    if any(
        term in combined_reject or term in combined_preserve
        for term in (
            "invented mouth",
            "turning the core into a face",
            "invented face",
            "mouth or teeth",
            "featureless black face",
            "featureless head",
        )
    ):
        face_lock = (
            "Keep the head exactly faceless as supplied: do not create eyes, a mouth, teeth, "
            "a nose, or any facial opening, glow, or expression."
        )
    else:
        face_lock = (
            "Keep facial topology and markings identical to the first frame for the entire video: "
            "same count, size, shape, position, and color for every existing eye, mouth, tooth, nose, "
            "opening, and surface mark; do not invent absent features or substitute a new expression design. "
            "Do not add blush, cheek dots, new markings, or decorative facial details."
        )
    contract = ""
    if preserve:
        contract += " Preserve exactly: " + "; ".join(preserve) + "."
    if reject:
        contract += " Never produce: " + "; ".join(reject) + "."
    return (
        face_lock + contract
    )


def prepare_video_job(
    *,
    repo_root: Path,
    run_dir: Path,
    state: str,
    first_frame_name: str,
    duration_seconds: int = 6,
    provider_action_override: str | None = None,
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
    video_prompt = entry.get("video_prompt")
    video_prompt = video_prompt if isinstance(video_prompt, Mapping) else {}
    if provider_action_override is not None:
        action = str(provider_action_override).strip().rstrip(".")
        action_source = "cli-override"
    else:
        action = str(video_prompt.get("provider_action") or entry.get("action") or state).strip().rstrip(".")
        action_source = (
            "request-video-prompt"
            if video_prompt.get("provider_action")
            else "request-state-action"
        )
    if not action or len(action) > 800:
        raise VideoAnimationError("provider action must contain 1..800 characters")
    background_name = str(background["name"])
    background_hex = str(background["hex"])
    closure_text = (
        "Return naturally to the exact starting pose."
        if entry.get("loop", True)
        else "Finish with a clean exact-pose settle."
    )
    motion_lock = _video_motion_lock(entry)
    prompt_contract = _video_prompt_contract(request, state, entry)
    prompt_contract["provider_action"] = action
    prompt_contract["provider_action_source"] = action_source
    creature_lock = _video_creature_lock(prompt_contract)
    identity_lock = _video_identity_lock(request)
    prompt_text = (
        "PROVIDER CALL: invoke image_to_video exactly once and produce exactly one video. "
        "Do not generate alternatives, variants, previews, or a second take after the first successful call.\n"
        f"TASK: Animate the exact supplied full-body first frame for {duration_seconds} seconds. "
        f"One continuous action: {action}. {closure_text}\n"
        "HARD CAMERA LOCK: use a locked camera; projection, framing, ground line, subject center, and "
        "subject pixel scale remain fixed. No cuts, pans, tilts, rolls, zooms, push-ins, pull-backs, "
        "reframing, or camera shake.\n"
        f"{creature_lock}\n"
        f"PHASE TIMING: {prompt_contract['timing']}\n"
        f"ANATOMY MOTION: {motion_lock.strip()}\n"
        f"IDENTITY LOCK: {identity_lock}\n"
        f"BACKGROUND LOCK: flat neutral {background_name} {background_hex}; every background pixel and the "
        "first-frame lighting remain unchanged. No cast shadow, flicker, exposure change, detached effect, "
        "text, prop, extra object, motion blur, identity redesign, added anatomy, or missing anatomy.\n"
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
        "prompt_contract": {
            key: value
            for key, value in prompt_contract.items()
            if key != "timing"
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


def reviewed_sample_indices(
    total_frames: int,
    requested_frames: int,
    indices: list[int],
) -> list[int]:
    if len(indices) != requested_frames:
        raise VideoAnimationError(
            f"reviewed selection has {len(indices)} indices; expected {requested_frames}"
        )
    if not indices or indices[0] != 0:
        raise VideoAnimationError("reviewed selection must start at video frame 0")
    if len(set(indices)) != len(indices):
        raise VideoAnimationError("reviewed selection contains duplicate frame indices")
    if indices != sorted(indices):
        raise VideoAnimationError("reviewed selection must be in chronological order")
    if any(index < 0 or index >= total_frames for index in indices):
        raise VideoAnimationError(
            f"reviewed selection indices must stay inside 0..{total_frames - 1}"
        )
    return list(indices)


def uniform_fallback_metrics(
    total_frames: int,
    indices: list[int],
) -> dict[str, Any]:
    candidates = [list(indices)]
    for slot in range(1, len(indices)):
        for delta in (-1, 1):
            changed = list(indices)
            changed[slot] += delta
            if (
                0 <= changed[slot] < total_frames
                and changed == sorted(set(changed))
                and changed not in candidates
            ):
                candidates.append(changed)
            if len(candidates) == 8:
                break
        if len(candidates) == 8:
            break
    return {
        "method": "uniform-fallback",
        "reason": "the video has too few decoded frames for full adaptive analysis",
        "candidate_sets": [
            {
                "rank": rank,
                "indices": candidate,
                "score": round(1.0 - (rank - 1) * 0.01, 6),
                "timestamps_ratio": [
                    round(index / total_frames, 6) for index in candidate
                ],
            }
            for rank, candidate in enumerate(candidates, start=1)
        ],
    }


def _frame_signature(image: Image.Image, sample_size: int = 64) -> FrameSignature:
    sampled = image.convert("RGB").resize(
        (sample_size, sample_size), Image.Resampling.BILINEAR
    )
    pixels = list(sampled.get_flattened_data())
    corners = (
        pixels[0],
        pixels[sample_size - 1],
        pixels[-sample_size],
        pixels[-1],
    )
    background = tuple(sum(pixel[channel] for pixel in corners) / 4.0 for channel in range(3))
    mask_values = bytearray(sample_size * sample_size)
    xs: list[int] = []
    ys: list[int] = []
    luma = bytearray(sample_size * sample_size)
    for index, pixel in enumerate(pixels):
        distance = sum(abs(pixel[channel] - background[channel]) for channel in range(3))
        foreground = distance >= 36
        mask_values[index] = 255 if foreground else 0
        if foreground:
            xs.append(index % sample_size)
            ys.append(index // sample_size)
        luma[index] = round(0.299 * pixel[0] + 0.587 * pixel[1] + 0.114 * pixel[2])
    if xs:
        center_x = sum(xs) / len(xs) / max(1, sample_size - 1)
        center_y = sum(ys) / len(ys) / max(1, sample_size - 1)
        bbox_width_ratio = (max(xs) - min(xs) + 1) / sample_size
        bbox_height_ratio = (max(ys) - min(ys) + 1) / sample_size
    else:
        center_x = center_y = 0.5
        bbox_width_ratio = bbox_height_ratio = 0.0
    core_min_x = round(sample_size * 0.31)
    core_max_x = round(sample_size * 0.69)
    core_ys = [
        index // sample_size
        for index, value in enumerate(mask_values)
        if value and core_min_x <= index % sample_size <= core_max_x
    ]
    core_bbox_height_ratio = (
        (max(core_ys) - min(core_ys) + 1) / sample_size if core_ys else 0.0
    )
    edge_total = 0
    edge_count = 0
    for y in range(sample_size - 1):
        for x in range(sample_size - 1):
            index = y * sample_size + x
            if mask_values[index]:
                edge_total += abs(luma[index] - luma[index + 1])
                edge_total += abs(luma[index] - luma[index + sample_size])
                edge_count += 2
    source_edge_values = [
        mask_values[x]
        for x in range(sample_size)
    ] + [
        mask_values[(sample_size - 1) * sample_size + x]
        for x in range(sample_size)
    ] + [
        mask_values[y * sample_size]
        for y in range(1, sample_size - 1)
    ] + [
        mask_values[y * sample_size + sample_size - 1]
        for y in range(1, sample_size - 1)
    ]
    return FrameSignature(
        rgb=sampled.tobytes(),
        mask=bytes(mask_values),
        foreground_ratio=len(xs) / (sample_size * sample_size),
        center_x=center_x,
        center_y=center_y,
        sharpness=(edge_total / edge_count / 255.0) if edge_count else 0.0,
        source_edge_foreground_ratio=(
            sum(1 for value in source_edge_values if value) / len(source_edge_values)
            if source_edge_values
            else 0.0
        ),
        bbox_width_ratio=bbox_width_ratio,
        bbox_height_ratio=bbox_height_ratio,
        core_bbox_height_ratio=core_bbox_height_ratio,
    )


def reviewed_selection_metrics(
    signatures: list[FrameSignature],
    indices: list[int],
    exact_first: FrameSignature,
    candidate_metrics: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Attach metrics for the reviewed indices, not only auto-ranked candidates."""

    metrics = dict(candidate_metrics or {})
    selected = [signatures[index] for index in indices]
    reference_height = max(exact_first.bbox_height_ratio, 1e-9)
    reference_core_height = max(exact_first.core_bbox_height_ratio, 1e-9)
    reference_width = max(exact_first.bbox_width_ratio, 1e-9)
    metrics["reviewed_indices"] = list(indices)
    metrics["reviewed_selection"] = {
        "foreground_ratio": [round(item.foreground_ratio, 6) for item in selected],
        "bbox_width_ratio_vs_first_frame": [
            round(item.bbox_width_ratio / reference_width, 6) for item in selected
        ],
        "bbox_height_ratio_vs_first_frame": [
            round(item.bbox_height_ratio / reference_height, 6) for item in selected
        ],
        "core_bbox_height_ratio_vs_first_frame": [
            round(item.core_bbox_height_ratio / reference_core_height, 6)
            for item in selected
        ],
        "center": [
            [round(item.center_x, 6), round(item.center_y, 6)] for item in selected
        ],
        "source_edge_foreground_ratio": [
            round(item.source_edge_foreground_ratio, 6) for item in selected
        ],
        "source_edge_contact_frames": [
            index
            for index, item in zip(indices, selected)
            if item.source_edge_foreground_ratio > 0.0
        ],
    }
    return metrics


def validate_reviewed_locomotion_scale(
    request: Mapping[str, Any],
    state: str,
    signatures: list[FrameSignature],
    indices: list[int],
    exact_first: FrameSignature,
    exact_idle_slots: list[int],
    *,
    minimum_height_ratio: float = 0.78,
    maximum_height_ratio: float = 1.22,
) -> None:
    """Fail before background removal when reviewed locomotion zooms or shrinks."""

    if not _is_locomotion_state(request, state) or exact_first.bbox_height_ratio <= 0:
        return
    use_core_height = exact_first.core_bbox_height_ratio > 0
    reference_height = (
        exact_first.core_bbox_height_ratio
        if use_core_height
        else exact_first.bbox_height_ratio
    )
    ratios = [
        (
            signatures[index].core_bbox_height_ratio
            if use_core_height and signatures[index].core_bbox_height_ratio > 0
            else signatures[index].bbox_height_ratio
        )
        / reference_height
        for index in indices
    ]
    active_ratios = [
        ratio for slot, ratio in enumerate(ratios) if slot not in set(exact_idle_slots)
    ]
    if not active_ratios:
        return
    smallest = min(active_ratios)
    largest = max(active_ratios)
    if smallest < minimum_height_ratio or largest > maximum_height_ratio:
        raise VideoAnimationError(
            "reviewed locomotion selection changes subject core height to "
            f"{smallest:.2f}x..{largest:.2f}x the exact first frame; expected "
            f"{minimum_height_ratio:.2f}x..{maximum_height_ratio:.2f}x. "
            "Choose stable in-place frames or regenerate before background removal."
        )


def _is_locomotion_state(
    request: Mapping[str, Any], state: str
) -> bool:
    entry = request.get("states", {}).get(state, {})
    workflows = entry.get("animation_workflows", []) if isinstance(entry, Mapping) else []
    return state == "idle-step" or any(
        "locomotion" in str(workflow).lower() for workflow in workflows
    )


def _signature_distance(left: FrameSignature, right: FrameSignature) -> float:
    union = 0
    changed = 0
    for left_value, right_value in zip(left.mask, right.mask):
        if left_value or right_value:
            union += 1
            if bool(left_value) != bool(right_value):
                changed += 1
    silhouette = changed / union if union else 0.0
    rgb_difference = sum(abs(a - b) for a, b in zip(left.rgb, right.rgb))
    rgb_difference /= max(1, len(left.rgb) * 255)
    return 0.72 * silhouette + 0.28 * rgb_difference


def adaptive_sample_indices(
    signatures: list[FrameSignature],
    requested_frames: int,
    *,
    sampling_mode: str = "cyclic-half-open",
    enforce_scale_stability: bool = False,
) -> tuple[list[int], dict[str, Any]]:
    """Rank chronological pose sequences from visual evidence, not fixed time."""
    total_frames = len(signatures)
    minimum_frames = max(8, requested_frames * 3)
    if total_frames < minimum_frames:
        raise VideoAnimationError(
            f"adaptive video sampling requires at least {minimum_frames} decoded frames"
        )
    anchor = signatures[0]
    anchor_distances = [_signature_distance(anchor, signature) for signature in signatures]
    max_sharpness = max((signature.sharpness for signature in signatures), default=1.0) or 1.0

    def height_ratio(index: int) -> float:
        if anchor.bbox_height_ratio <= 0:
            return 1.0
        return signatures[index].bbox_height_ratio / anchor.bbox_height_ratio

    def scale_penalty(index: int) -> float:
        if not enforce_scale_stability:
            return 0.0
        ratio = height_ratio(index)
        drift = abs(ratio - 1.0)
        hard = 2.0 if ratio < 0.78 or ratio > 1.22 else 0.0
        return hard + 1.2 * drift

    scale_unstable_frames = [
        index
        for index in range(total_frames)
        if enforce_scale_stability and not 0.78 <= height_ratio(index) <= 1.22
    ]

    def stability(index: int) -> float:
        signature = signatures[index]
        area_drift = abs(signature.foreground_ratio - anchor.foreground_ratio)
        center_drift = abs(signature.center_x - anchor.center_x) + abs(signature.center_y - anchor.center_y)
        blur_penalty = max(0.0, 0.65 - signature.sharpness / max_sharpness)
        height_drift = abs(height_ratio(index) - 1.0) if enforce_scale_stability else 0.0
        return max(
            0.0,
            1.0
            - 1.4 * area_drift
            - 0.8 * center_drift
            - 0.35 * blur_penalty
            - 0.9 * height_drift,
        )

    def source_edge_contact(index: int) -> bool:
        return signatures[index].source_edge_foreground_ratio > 0.0

    def source_edge_penalty(index: int) -> float:
        # A visually interesting pose is unusable when the source video already
        # clips it. Keep such frames visible in the editor, but rank every safe
        # alternative above them.
        return 2.0 if source_edge_contact(index) else 0.0

    source_edge_contact_frames = [
        index for index in range(total_frames) if source_edge_contact(index)
    ]

    if requested_frames != 4:
        candidate_sets: list[tuple[float, list[int]]] = []
        span = total_frames if sampling_mode == "cyclic-half-open" else total_frames - 1
        window = max(2, total_frames // max(4, requested_frames * 2))
        variants = (
            (-0.30, 0.52, 0.30),
            (-0.20, 0.46, 0.36),
            (-0.10, 0.40, 0.42),
            (0.00, 0.34, 0.48),
            (0.10, 0.30, 0.52),
            (0.20, 0.42, 0.40),
            (0.30, 0.50, 0.32),
            (0.00, 0.60, 0.24),
        )
        for shift, novelty_weight, anchor_weight in variants:
            selected = [0]
            total_score = 0.0
            for slot in range(1, requested_frames):
                target = slot * span / (
                    requested_frames
                    if sampling_mode == "cyclic-half-open"
                    else requested_frames - 1
                )
                target += shift * window
                lower = max(selected[-1] + 1, round(target - window))
                upper = min(total_frames - 1, round(target + window))
                remaining = requested_frames - slot - 1
                upper = min(upper, total_frames - 1 - remaining)
                if lower > upper:
                    break
                prior = selected[-1]

                def score(index: int) -> float:
                    novelty = _signature_distance(signatures[prior], signatures[index])
                    timing = 1.0 - min(1.0, abs(index - target) / max(1, window))
                    return (
                        novelty_weight * novelty
                        + anchor_weight * anchor_distances[index]
                        + 0.12 * stability(index)
                        + 0.08 * timing
                        - source_edge_penalty(index)
                        - scale_penalty(index)
                    )

                chosen = max(range(lower, upper + 1), key=score)
                selected.append(chosen)
                total_score += score(chosen)
            if len(selected) == requested_frames:
                candidate_sets.append((total_score, selected))
        unique: list[tuple[float, list[int]]] = []
        seen: set[tuple[int, ...]] = set()
        for score, candidate in sorted(candidate_sets, reverse=True):
            key = tuple(candidate)
            if key not in seen:
                seen.add(key)
                unique.append((score, candidate))
        if not unique:
            raise VideoAnimationError("video has no valid adaptive pose candidates")
        indices = unique[0][1]
        return indices, {
            "method": "adaptive-sequence-v1",
            "anchor_distance": [round(anchor_distances[index], 6) for index in indices],
            "foreground_ratio": [
                round(signatures[index].foreground_ratio, 6) for index in indices
            ],
            "center": [
                [round(signatures[index].center_x, 6), round(signatures[index].center_y, 6)]
                for index in indices
            ],
            "sharpness": [round(signatures[index].sharpness, 6) for index in indices],
            "source_edge_foreground_ratio": [
                round(signatures[index].source_edge_foreground_ratio, 6)
                for index in indices
            ],
            "source_edge_contact_frames": source_edge_contact_frames,
            "scale_unstable_frames": scale_unstable_frames,
            "candidate_sets": [
                {
                    "rank": rank,
                    "indices": candidate,
                    "score": round(score, 6),
                    "timestamps_ratio": [
                        round(index / total_frames, 6) for index in candidate
                    ],
                    "source_edge_contact_frames": [
                        index for index in candidate if source_edge_contact(index)
                    ],
                    "scale_unstable_frames": [
                        index for index in candidate if index in scale_unstable_frames
                    ],
                    "bbox_height_ratio_vs_anchor": [
                        round(height_ratio(index), 6) for index in candidate
                    ],
                }
                for rank, (score, candidate) in enumerate(unique[:8], start=1)
            ],
        }

    margin = max(2, total_frames // 24)
    midpoint = total_frames // 2
    minimum_gap = max(2, total_frames // 12)
    separation = max(2, total_frames // 18)

    def ranked_distinct(candidates: range, score: Any, count: int) -> list[int]:
        ranked = sorted(candidates, key=score, reverse=True)
        chosen: list[int] = []
        for index in ranked:
            if all(abs(index - prior) >= separation for prior in chosen):
                chosen.append(index)
                if len(chosen) == count:
                    break
        return chosen

    first_candidates = range(margin, max(margin + 1, midpoint - margin))
    phase_as = ranked_distinct(
        first_candidates,
        lambda index: (
            anchor_distances[index] * (0.75 + 0.25 * stability(index))
            - source_edge_penalty(index)
            - scale_penalty(index)
        ),
        4,
    )
    candidate_sets: list[tuple[float, list[int]]] = []
    for phase_a in phase_as:
        recovery_start = phase_a + minimum_gap
        recovery_end = min(total_frames - margin - minimum_gap, (3 * total_frames) // 4)
        if recovery_end <= recovery_start:
            continue
        recoveries = ranked_distinct(
            range(recovery_start, recovery_end + 1),
            lambda index: (
                -source_edge_penalty(index)
                - anchor_distances[index]
                - 0.08 * abs(index - midpoint) / total_frames
                + 0.1 * stability(index)
                - scale_penalty(index)
            ),
            4,
        )
        for recovery in recoveries:
            final_candidates = range(recovery + minimum_gap, total_frames - margin)
            phase_bs = ranked_distinct(
                final_candidates,
                lambda index: (
                    0.48 * anchor_distances[index]
                    + 0.52 * _signature_distance(signatures[phase_a], signatures[index])
                )
                * (0.75 + 0.25 * stability(index))
                - source_edge_penalty(index)
                - scale_penalty(index),
                4,
            )
            for phase_b in phase_bs:
                phase_difference = _signature_distance(
                    signatures[phase_a], signatures[phase_b]
                )
                score = (
                    anchor_distances[phase_a]
                    + anchor_distances[phase_b]
                    + 1.4 * phase_difference
                    + 0.25 * (stability(phase_a) + stability(phase_b))
                    - 0.4 * anchor_distances[recovery]
                    - source_edge_penalty(phase_a)
                    - source_edge_penalty(recovery)
                    - source_edge_penalty(phase_b)
                    - scale_penalty(phase_a)
                    - scale_penalty(recovery)
                    - scale_penalty(phase_b)
                )
                candidate_sets.append((score, [0, phase_a, recovery, phase_b]))
    if not candidate_sets:
        raise VideoAnimationError("video has no valid adaptive pose candidates")
    unique_candidates: list[tuple[float, list[int]]] = []
    seen: set[tuple[int, ...]] = set()
    for score, candidate in sorted(candidate_sets, reverse=True):
        key = tuple(candidate)
        if key not in seen:
            seen.add(key)
            unique_candidates.append((score, candidate))
        if len(unique_candidates) == 8:
            break
    indices = unique_candidates[0][1]
    phase_a, recovery, phase_b = indices[1:]
    metrics = {
        "method": "adaptive-pose-v1",
        "anchor_distance": [round(anchor_distances[index], 6) for index in indices],
        "phase_a_to_phase_b_distance": round(
            _signature_distance(signatures[phase_a], signatures[phase_b]), 6
        ),
        "candidate_sets": [
            {
                "rank": rank,
                "indices": candidate,
                "score": round(score, 6),
                "timestamps_ratio": [round(index / total_frames, 6) for index in candidate],
                "source_edge_contact_frames": [
                    index for index in candidate if source_edge_contact(index)
                ],
                "scale_unstable_frames": [
                    index for index in candidate if index in scale_unstable_frames
                ],
                "bbox_height_ratio_vs_anchor": [
                    round(height_ratio(index), 6) for index in candidate
                ],
            }
            for rank, (score, candidate) in enumerate(unique_candidates, start=1)
        ],
        "foreground_ratio": [
            round(signatures[index].foreground_ratio, 6) for index in indices
        ],
        "center": [
            [round(signatures[index].center_x, 6), round(signatures[index].center_y, 6)]
            for index in indices
        ],
        "sharpness": [round(signatures[index].sharpness, 6) for index in indices],
        "source_edge_foreground_ratio": [
            round(signatures[index].source_edge_foreground_ratio, 6)
            for index in indices
        ],
        "source_edge_contact_frames": source_edge_contact_frames,
        "scale_unstable_frames": scale_unstable_frames,
    }
    return indices, metrics


def _decode_signatures(
    decoder: Any,
    video_path: Path,
    expected_size: tuple[int, int],
    expected_total: int,
) -> list[FrameSignature]:
    reader = decoder.read_frames(str(video_path), pix_fmt="rgb24")
    signatures: list[FrameSignature] = []
    try:
        try:
            metadata = next(reader)
        except StopIteration as exc:
            raise VideoAnimationError("video decoder returned no metadata during adaptive analysis") from exc
        size, _fps, _duration = _reader_metadata(metadata)
        if size != expected_size:
            raise VideoAnimationError("video decoder dimensions changed during adaptive analysis")
        expected_bytes = size[0] * size[1] * 3
        for payload in reader:
            if not isinstance(payload, (bytes, bytearray)) or len(payload) != expected_bytes:
                raise VideoAnimationError("video decoder returned a malformed RGB frame during adaptive analysis")
            signatures.append(_frame_signature(Image.frombytes("RGB", size, bytes(payload))))
    finally:
        close = getattr(reader, "close", None)
        if callable(close):
            close()
    if len(signatures) != expected_total:
        raise VideoAnimationError("video decoder frame count changed during adaptive analysis")
    return signatures


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


def _exact_idle_slots_for_state(
    request: Mapping[str, Any], state: str, requested_frames: int
) -> list[int]:
    slots = [0]
    creature_motion = request.get("creature_motion")
    if (
        requested_frames != 4
        or not isinstance(creature_motion, Mapping)
        or creature_motion.get("shared_idle") is not True
    ):
        return slots
    state_config = request.get("states", {}).get(state, {})
    workflows = state_config.get("animation_workflows", []) if isinstance(state_config, Mapping) else []
    is_attack = "attack" in state.lower() or any(
        "attack" in str(workflow).lower() for workflow in workflows
    )
    slots.append(requested_frames - 1 if is_attack else 2)
    return slots


def _merged_provenance(
    run_dir: Path,
    request: Mapping[str, Any],
    *,
    state: str,
    raw_bytes: bytes,
    report_path: Path,
    prior: Mapping[str, Any] | None,
    force: bool,
    source_type: str = "grok-imagine-video",
    art_engine: str = "grok-imagine",
    notes: str = "accepted through completed $grok-imagine video-from-image invocation and deterministic frame sampling",
    license_name: str = "xAI-provider-terms",
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
            "source_type": source_type,
            "art_engine": art_engine,
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
        "notes": notes,
        "license": "mixed-provider-terms" if mixed else license_name,
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
    sample_indices: list[int] | None = None,
    sampling_strategy: str = "adaptive",
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
    selection_metrics: dict[str, Any] | None = None
    signatures: list[FrameSignature] | None = None
    if (
        sample_indices is None
        and sampling_strategy == "adaptive"
        and total_frames >= max(8, int(job["requested_frames"]) * 3)
    ):
        signatures = _decode_signatures(
            decoder, video_path, decoded_size, total_frames
        )
        indices, selection_metrics = adaptive_sample_indices(
            signatures,
            int(job["requested_frames"]),
            sampling_mode=sampling_mode,
            enforce_scale_stability=_is_locomotion_state(request, state),
        )
        sampling_mode = "adaptive-visual"
    elif sample_indices is None and sampling_strategy == "adaptive":
        indices = uniform_sample_indices(
            total_frames,
            int(job["requested_frames"]),
            sampling_mode=sampling_mode,
        )
        selection_metrics = uniform_fallback_metrics(total_frames, indices)
    elif sample_indices is None and sampling_strategy == "uniform":
        indices = uniform_sample_indices(
            total_frames,
            int(job["requested_frames"]),
            sampling_mode=sampling_mode,
        )
    elif sample_indices is None:
        raise VideoAnimationError(
            f"unsupported video sampling strategy: {sampling_strategy!r}"
        )
    else:
        indices = reviewed_sample_indices(
            total_frames,
            int(job["requested_frames"]),
            sample_indices,
        )
        signatures = _decode_signatures(
            decoder, video_path, decoded_size, total_frames
        )
        if sampling_strategy == "adaptive" and total_frames >= max(
            8, int(job["requested_frames"]) * 3
        ):
            _automatic_indices, selection_metrics = adaptive_sample_indices(
                signatures,
                int(job["requested_frames"]),
                sampling_mode=sampling_mode,
                enforce_scale_stability=_is_locomotion_state(request, state),
            )
        sampling_mode = "reviewed-explicit"
    selected = _decode_selected(decoder, video_path, indices, decoded_size, total_frames)
    with Image.open(first_frame_path) as opened:
        opened.load()
        exact_first = opened.convert("RGBA")
    if exact_first.size != (job["first_frame"]["width"], job["first_frame"]["height"]):
        raise VideoAnimationError("exact first-frame dimensions changed after job preparation")
    shared_idle_slots = _exact_idle_slots_for_state(
        request, state, int(job["requested_frames"])
    )
    if sample_indices is not None and signatures is not None:
        exact_signature = _frame_signature(exact_first)
        selection_metrics = reviewed_selection_metrics(
            signatures, indices, exact_signature, selection_metrics
        )
        validate_reviewed_locomotion_scale(
            request,
            state,
            signatures,
            indices,
            exact_signature,
            shared_idle_slots,
        )
    frames = [_normalized_frame(selected[index], exact_first.size) for index in indices]
    frames[0] = exact_first.copy()
    for idle_slot in shared_idle_slots:
        frames[idle_slot] = exact_first.copy()
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
        "selection_reviewed": sample_indices is not None,
        "selection_metrics": selection_metrics,
        "sampled_timestamps_seconds": [round(index / fps, 6) for index in indices],
        "exact_first_frame_preserved": True,
        "exact_idle_slots": shared_idle_slots,
        "independent_frame_background_removal": True,
        "selector_required": True,
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


def ingest_imported_video(
    *,
    run_dir: Path,
    state: str,
    video_path: Path,
    first_frame_path: Path | None = None,
    force: bool = False,
    decoder: Any | None = None,
    sample_indices: list[int] | None = None,
    sampling_strategy: str = "adaptive",
    license_name: str = "caller-provided-source-terms",
) -> VideoIngestResult:
    """Ingest a caller-provided video through the provider-neutral video lane."""

    run_root = Path(run_dir).expanduser().resolve()
    if not run_root.is_dir():
        raise VideoAnimationError(f"run directory does not exist: {run_root}")
    source_video = Path(video_path).expanduser().resolve()
    if source_video.suffix.lower() not in _VIDEO_EXTENSIONS:
        raise VideoAnimationError("video must be MP4, WebM, MOV, or M4V")
    if not source_video.is_file() or source_video.stat().st_size < 1:
        raise VideoAnimationError(f"video does not exist or is empty: {source_video}")
    video_bytes = source_video.read_bytes()
    source_video_hash = _digest(video_bytes)

    request_path = run_root / "sprite-request.json"
    request = load_sprite_request(request_path).data
    if state not in request["states"]:
        raise VideoAnimationError(f"sprite request has no state {state!r}")
    entry = request["states"][state]
    requested_frames = int(entry["frames"])
    raw_layout = entry.get("raw_layout")
    if not isinstance(raw_layout, Mapping):
        raise VideoAnimationError(f"state {state!r} has no raw_layout")
    request_record = _file_record(request_path, relative_to=run_root)

    source_dir = resolve_run_path(run_root, f"provider/video/{state}")
    copied_video_path = source_dir / f"source{source_video.suffix.lower()}"
    report_path = source_dir / "video-source.json"
    raw_path = resolve_run_path(run_root, f"raw/{state}.png")
    provenance_path = run_root / "source-provenance.json"
    first_copy_path: Path | None = None
    first_bytes: bytes | None = None
    exact_first: Image.Image | None = None
    if first_frame_path is not None:
        supplied_first = Path(first_frame_path).expanduser().resolve()
        if supplied_first.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
            raise VideoAnimationError("first frame must be PNG, JPEG, or WebP")
        if not supplied_first.is_file():
            raise VideoAnimationError(f"first frame does not exist: {supplied_first}")
        first_bytes = supplied_first.read_bytes()
        try:
            with Image.open(BytesIO(first_bytes)) as opened:
                opened.load()
                exact_first = opened.convert("RGBA")
        except (OSError, ValueError) as exc:
            raise VideoAnimationError("first frame is not a decodable image") from exc
        first_copy_path = source_dir / f"first-frame{supplied_first.suffix.lower()}"

    collisions = [path for path in (copied_video_path, report_path, raw_path) if path.exists()]
    if first_copy_path is not None and first_copy_path.exists():
        collisions.append(first_copy_path)
    if collisions and not force:
        raise VideoAnimationError(
            "imported video outputs already exist; pass --force to replace known outputs"
        )
    if decoder is None:
        try:
            import imageio_ffmpeg as decoder  # type: ignore[no-redef]
        except ImportError as exc:
            raise VideoAnimationError(
                "video ingestion requires imageio-ffmpeg; install scripts/requirements-video.txt"
            ) from exc
    decoded_size, fps, duration, total_frames = _inspect_decoded_video(decoder, source_video)
    sampling_mode = _video_sampling_mode(state, entry)
    selection_metrics: dict[str, Any] | None = None
    signatures: list[FrameSignature] | None = None
    if (
        sample_indices is None
        and sampling_strategy == "adaptive"
        and total_frames >= max(8, requested_frames * 3)
    ):
        signatures = _decode_signatures(decoder, source_video, decoded_size, total_frames)
        indices, selection_metrics = adaptive_sample_indices(
            signatures,
            requested_frames,
            sampling_mode=sampling_mode,
            enforce_scale_stability=_is_locomotion_state(request, state),
        )
        effective_sampling_mode = "adaptive-visual"
    elif sample_indices is None and sampling_strategy in {"adaptive", "uniform"}:
        indices = uniform_sample_indices(
            total_frames,
            requested_frames,
            sampling_mode=sampling_mode,
        )
        effective_sampling_mode = sampling_mode
        if sampling_strategy == "adaptive":
            selection_metrics = uniform_fallback_metrics(total_frames, indices)
    elif sample_indices is None:
        raise VideoAnimationError(
            f"unsupported video sampling strategy: {sampling_strategy!r}"
        )
    else:
        indices = reviewed_sample_indices(total_frames, requested_frames, sample_indices)
        signatures = _decode_signatures(
            decoder, source_video, decoded_size, total_frames
        )
        if sampling_strategy == "adaptive" and total_frames >= max(
            8, requested_frames * 3
        ):
            _automatic_indices, selection_metrics = adaptive_sample_indices(
                signatures,
                requested_frames,
                sampling_mode=sampling_mode,
                enforce_scale_stability=_is_locomotion_state(request, state),
            )
        effective_sampling_mode = "reviewed-explicit"
    selected = _decode_selected(decoder, source_video, indices, decoded_size, total_frames)
    if exact_first is None:
        exact_first = selected[0].copy()
    target_size = exact_first.size
    exact_idle_slots = _exact_idle_slots_for_state(request, state, requested_frames)
    if sample_indices is not None and signatures is not None:
        exact_signature = _frame_signature(exact_first)
        selection_metrics = reviewed_selection_metrics(
            signatures, indices, exact_signature, selection_metrics
        )
        validate_reviewed_locomotion_scale(
            request,
            state,
            signatures,
            indices,
            exact_signature,
            exact_idle_slots,
        )
    frames = [_normalized_frame(selected[index], target_size) for index in indices]
    exact_first_preserved = first_bytes is not None
    if exact_first_preserved:
        frames[0] = exact_first.copy()
    for idle_slot in exact_idle_slots:
        frames[idle_slot] = exact_first.copy()
    raw_bytes = _compose_grid(
        frames,
        int(raw_layout["columns"]),
        int(raw_layout["rows"]),
    )
    prior_provenance, prior_provenance_hash = _prior_provenance_snapshot(
        provenance_path
    )
    output_record = {
        "path": raw_path.relative_to(run_root).as_posix(),
        "sha256": _digest(raw_bytes),
        "size_bytes": len(raw_bytes),
        "width": target_size[0] * int(raw_layout["columns"]),
        "height": target_size[1] * int(raw_layout["rows"]),
    }
    copied_video_record = {
        "path": copied_video_path.relative_to(run_root).as_posix(),
        "sha256": source_video_hash,
        "size_bytes": len(video_bytes),
    }
    first_record = None
    if first_copy_path is not None and first_bytes is not None:
        first_record = {
            "path": first_copy_path.relative_to(run_root).as_posix(),
            "sha256": _digest(first_bytes),
            "size_bytes": len(first_bytes),
            "width": target_size[0],
            "height": target_size[1],
        }
    report = {
        "version": 1,
        "kind": "sprite-video-source",
        "status": "pass",
        "origin": "imported",
        "state": state,
        "sprite_request": request_record,
        "video": copied_video_record,
        "first_frame": first_record,
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
        "sampling_mode": effective_sampling_mode,
        "selection_reviewed": sample_indices is not None,
        "selection_metrics": selection_metrics,
        "sampled_timestamps_seconds": [round(index / fps, 6) for index in indices],
        "exact_first_frame_preserved": exact_first_preserved,
        "exact_idle_slots": exact_idle_slots,
        "independent_frame_background_removal": True,
        "selector_required": True,
        "output": output_record,
    }
    _validate_video_source_report(report)
    provenance = _merged_provenance(
        run_root,
        request,
        state=state,
        raw_bytes=raw_bytes,
        report_path=report_path,
        prior=prior_provenance,
        force=force,
        source_type="imported",
        art_engine="imported",
        notes="accepted from a caller-provided video and deterministic visual frame selection",
        license_name=license_name,
    )
    outputs: list[tuple[Path, bytes]] = [(copied_video_path, video_bytes)]
    if first_copy_path is not None and first_bytes is not None:
        outputs.append((first_copy_path, first_bytes))
    return VideoIngestResult(
        run_dir=run_root,
        raw_path=raw_path,
        report_path=report_path,
        provenance_path=provenance_path,
        raw_bytes=raw_bytes,
        report=report,
        provenance=provenance,
        source_hashes={
            "sprite_request": request_record["sha256"],
            "input_video": source_video_hash,
            "input_first_frame": _digest(first_bytes) if first_bytes is not None else "<absent>",
            "prior_provenance": prior_provenance_hash,
            "input_video_path": str(source_video),
            "input_first_frame_path": str(Path(first_frame_path).expanduser().resolve())
            if first_frame_path is not None
            else "<absent>",
        },
        force=force,
        additional_outputs=tuple(outputs),
    )


def revalidate_imported_video_sources(result: VideoIngestResult) -> None:
    source_video_path = Path(result.source_hashes["input_video_path"])
    first_path_value = str(result.source_hashes["input_first_frame_path"])
    current = {
        "sprite_request": _digest((result.run_dir / "sprite-request.json").read_bytes()),
        "input_video": _digest(source_video_path.read_bytes()),
        "input_first_frame": (
            _digest(Path(first_path_value).read_bytes())
            if first_path_value != "<absent>"
            else "<absent>"
        ),
        "prior_provenance": (
            _digest(result.provenance_path.read_bytes())
            if result.provenance_path.is_file()
            else "<absent>"
        ),
        "input_video_path": str(source_video_path),
        "input_first_frame_path": first_path_value,
    }
    if current != dict(result.source_hashes):
        raise VideoAnimationError("imported video sources changed before commit")
    if not result.force and any(
        path.exists()
        for path in (result.raw_path, result.report_path, *(path for path, _ in result.additional_outputs))
    ):
        raise VideoAnimationError("imported video outputs appeared before commit")


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
    "adaptive_sample_indices",
    "ingest_imported_video",
    "ingest_video",
    "prepare_video_job",
    "revalidate_prepared_sources",
    "revalidate_imported_video_sources",
    "revalidate_video_sources",
    "reviewed_sample_indices",
    "uniform_sample_indices",
]
