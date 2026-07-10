"""Deterministic manifest-driven sprite runtime preview rendering."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from jsonschema import Draft202012Validator
from PIL import Image, ImageColor, __version__ as pillow_version

from spritecore.contracts import load_manifest
from spritecore.paths import PathSafetyError, resolve_run_path


class RuntimePreviewError(ValueError):
    """Raised before mutation when runtime evidence cannot be produced honestly."""


@dataclass(frozen=True, slots=True)
class PreviewPlan:
    run_dir: Path
    manifest_path: Path
    atlas_path: Path
    output_path: Path
    report_path: Path
    manifest: Mapping[str, Any]
    state: str
    kind: str
    frame_indices: tuple[int, ...]
    durations_ms: tuple[int, ...]
    viewport: tuple[int, int]
    dpr: float
    scale: int
    background: str
    force: bool


_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "references"
    / "schemas"
    / "screenshot-evidence-v1.schema.json"
)


def _digest(content: bytes) -> str:
    return sha256(content).hexdigest()


def _parse_viewport(value: str) -> tuple[int, int]:
    try:
        width_raw, height_raw = value.lower().split("x", 1)
        width, height = int(width_raw), int(height_raw)
    except (TypeError, ValueError) as exc:
        raise RuntimePreviewError("viewport must use WIDTHxHEIGHT") from exc
    if width < 1 or height < 1 or width > 8192 or height > 8192:
        raise RuntimePreviewError("viewport dimensions must be between 1 and 8192")
    return width, height


def _qa_output_path(run_dir: Path, value: str, *, suffix: str) -> Path:
    if "\\" in value or not value.startswith("qa/runtime-preview/"):
        raise RuntimePreviewError(
            "runtime preview outputs must be portable paths under qa/runtime-preview/"
        )
    try:
        path = resolve_run_path(run_dir, value)
    except PathSafetyError as exc:
        raise RuntimePreviewError(str(exc)) from exc
    if path.suffix.lower() != suffix:
        raise RuntimePreviewError(f"runtime preview output must use {suffix}")
    return path


def _state_timing(manifest: Mapping[str, Any], state: str, count: int) -> tuple[int, ...]:
    animation = manifest.get("animation")
    row: Mapping[str, Any] = {}
    if isinstance(animation, Mapping):
        rows = animation.get("rows")
        if isinstance(rows, Mapping) and isinstance(rows.get(state), Mapping):
            row = rows[state]
    durations = row.get("durations_ms")
    if isinstance(durations, list) and len(durations) == count and all(
        isinstance(item, int) and not isinstance(item, bool) and item > 0
        for item in durations
    ):
        return tuple(durations)
    fps = row.get("fps", 8)
    if isinstance(fps, bool) or not isinstance(fps, (int, float)) or fps <= 0:
        raise RuntimePreviewError(f"animation row {state!r} has invalid fps")
    duration = max(1, round(1000 / fps))
    return (duration,) * count


def prepare_preview(
    *,
    run_dir: Path,
    manifest_name: str,
    state: str,
    kind: str,
    frame: int,
    output_name: str | None,
    report_name: str | None,
    viewport: str,
    dpr: float,
    scale: int,
    background: str,
    force: bool,
) -> PreviewPlan:
    """Validate every input and path without creating output directories."""

    run_root = Path(run_dir).expanduser().resolve()
    if not run_root.is_dir():
        raise RuntimePreviewError(f"run directory does not exist: {run_root}")
    if kind not in {"runtime-still", "runtime-playback"}:
        raise RuntimePreviewError("kind must be runtime-still or runtime-playback")
    if isinstance(dpr, bool) or not 0.5 <= dpr <= 4:
        raise RuntimePreviewError("dpr must be between 0.5 and 4")
    if isinstance(scale, bool) or scale < 1 or scale > 32:
        raise RuntimePreviewError("scale must be an integer between 1 and 32")
    try:
        ImageColor.getrgb(background)
    except ValueError as exc:
        raise RuntimePreviewError("background must be a valid #RRGGBB color") from exc
    if len(background) != 7 or not background.startswith("#"):
        raise RuntimePreviewError("background must be a valid #RRGGBB color")

    try:
        manifest_path = resolve_run_path(run_root, manifest_name)
    except PathSafetyError as exc:
        raise RuntimePreviewError(str(exc)) from exc
    if not manifest_path.is_file():
        raise RuntimePreviewError(f"manifest does not exist: {manifest_name}")
    try:
        manifest = load_manifest(manifest_path).data
    except ValueError as exc:
        raise RuntimePreviewError(str(exc)) from exc
    rows = manifest["frame_layout"]["rows"]
    if state not in rows:
        raise RuntimePreviewError(f"manifest has no state {state!r}")
    rects = rows[state]
    if kind == "runtime-still":
        if frame < 0 or frame >= len(rects):
            raise RuntimePreviewError(f"frame {frame} is outside state {state!r}")
        frame_indices = (frame,)
    else:
        frame_indices = tuple(range(len(rects)))
    all_durations = _state_timing(manifest, state, len(rects))
    durations = tuple(all_durations[index] for index in frame_indices)

    atlas_name = manifest["atlas"]["path"]
    try:
        atlas_path = resolve_run_path(run_root, atlas_name)
    except PathSafetyError as exc:
        raise RuntimePreviewError(str(exc)) from exc
    if atlas_path == manifest_path or not atlas_path.is_file():
        raise RuntimePreviewError(f"atlas does not exist: {atlas_name}")
    try:
        with Image.open(atlas_path) as opened:
            opened.verify()
        with Image.open(atlas_path) as opened:
            actual_dimensions = opened.size
    except (OSError, ValueError) as exc:
        raise RuntimePreviewError(f"atlas is not a decodable image: {atlas_name}") from exc
    expected_dimensions = (manifest["atlas"]["width"], manifest["atlas"]["height"])
    if actual_dimensions != expected_dimensions:
        raise RuntimePreviewError(
            f"atlas dimensions {actual_dimensions} do not match manifest {expected_dimensions}"
        )

    width, height = _parse_viewport(viewport)
    stem = f"{state}-playback" if kind == "runtime-playback" else f"{state}-frame-{frame}"
    suffix = ".gif" if kind == "runtime-playback" else ".png"
    output_name = output_name or f"qa/runtime-preview/{stem}{suffix}"
    report_name = report_name or f"qa/runtime-preview/{stem}.evidence.json"
    output_path = _qa_output_path(run_root, output_name, suffix=suffix)
    report_path = _qa_output_path(run_root, report_name, suffix=".json")
    if output_path == report_path or output_path in {atlas_path, manifest_path}:
        raise RuntimePreviewError("runtime preview outputs cannot overwrite sources")
    if not force:
        collisions = [path for path in (output_path, report_path) if path.exists()]
        if collisions:
            raise RuntimePreviewError(
                "output already exists; pass --force to replace known preview outputs"
            )
    return PreviewPlan(
        run_dir=run_root,
        manifest_path=manifest_path,
        atlas_path=atlas_path,
        output_path=output_path,
        report_path=report_path,
        manifest=manifest,
        state=state,
        kind=kind,
        frame_indices=frame_indices,
        durations_ms=durations,
        viewport=(width, height),
        dpr=dpr,
        scale=scale,
        background=background.upper(),
        force=force,
    )


def _render_frames(plan: PreviewPlan) -> tuple[list[Image.Image], list[dict[str, Any]]]:
    pixel_dimensions = (
        round(plan.viewport[0] * plan.dpr),
        round(plan.viewport[1] * plan.dpr),
    )
    if min(pixel_dimensions) < 1:
        raise RuntimePreviewError("viewport and dpr resolve to an empty capture")
    resample = (
        Image.Resampling.NEAREST
        if plan.manifest["sampling_policy"]["filter"] == "nearest"
        else Image.Resampling.LANCZOS
    )
    frames: list[Image.Image] = []
    placements: list[dict[str, Any]] = []
    with Image.open(plan.atlas_path) as opened:
        atlas = opened.convert("RGBA")
        rects: Sequence[Mapping[str, int]] = plan.manifest["frame_layout"]["rows"][plan.state]
        for index in plan.frame_indices:
            rect = rects[index]
            sprite = atlas.crop(
                (rect["x"], rect["y"], rect["x"] + rect["w"], rect["y"] + rect["h"])
            )
            target_size = (
                round(rect["w"] * plan.scale * plan.dpr),
                round(rect["h"] * plan.scale * plan.dpr),
            )
            sprite = sprite.resize(target_size, resample=resample)
            x = (pixel_dimensions[0] - target_size[0]) // 2
            y = (pixel_dimensions[1] - target_size[1]) // 2
            if x < 0 or y < 0:
                raise RuntimePreviewError(
                    "scaled frame does not fit the declared viewport and dpr"
                )
            canvas = Image.new("RGBA", pixel_dimensions, ImageColor.getrgb(plan.background) + (255,))
            canvas.alpha_composite(sprite, (x, y))
            frames.append(canvas)
            placements.append(
                {
                    "frame": index,
                    "x": x,
                    "y": y,
                    "width": target_size[0],
                    "height": target_size[1],
                    "source_rect": {key: rect[key] for key in ("x", "y", "w", "h")},
                }
            )
    return frames, placements


def encode_preview(plan: PreviewPlan) -> tuple[bytes, list[dict[str, Any]]]:
    frames, placements = _render_frames(plan)
    buffer = BytesIO()
    if plan.kind == "runtime-still":
        frames[0].save(buffer, format="PNG", optimize=False, compress_level=9)
    else:
        adaptive = getattr(Image, "Palette", Image).ADAPTIVE
        palette_frames = [frame.convert("P", palette=adaptive, colors=255) for frame in frames]
        palette_frames[0].save(
            buffer,
            format="GIF",
            save_all=True,
            append_images=palette_frames[1:],
            duration=list(plan.durations_ms),
            loop=0,
            disposal=2,
            optimize=False,
        )
    return buffer.getvalue(), placements


def build_evidence(
    plan: PreviewPlan,
    artifact_bytes: bytes,
    placements: list[dict[str, Any]],
) -> dict[str, Any]:
    manifest_bytes = plan.manifest_path.read_bytes()
    atlas_bytes = plan.atlas_path.read_bytes()
    sources = [
        {
            "role": "manifest",
            "path": plan.manifest_path.relative_to(plan.run_dir).as_posix(),
            "sha256": _digest(manifest_bytes),
            "size_bytes": len(manifest_bytes),
        },
        {
            "role": "atlas",
            "path": plan.atlas_path.relative_to(plan.run_dir).as_posix(),
            "sha256": _digest(atlas_bytes),
            "size_bytes": len(atlas_bytes),
        },
    ]
    fingerprint_payload = {
        "sources": sources,
        "kind": plan.kind,
        "state": plan.state,
        "frames": list(plan.frame_indices),
        "durations_ms": list(plan.durations_ms),
        "viewport": [*plan.viewport, plan.dpr],
        "scale": plan.scale,
        "background": plan.background,
        "sampling": plan.manifest["sampling_policy"]["filter"],
    }
    fingerprint = _digest(
        json.dumps(fingerprint_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    pixel_dimensions = (
        round(plan.viewport[0] * plan.dpr),
        round(plan.viewport[1] * plan.dpr),
    )
    evidence = {
        "version": 1,
        "kind": "screenshot-evidence",
        "evidence_kind": plan.kind,
        "applicable": True,
        "artifact": {
            "path": plan.output_path.relative_to(plan.run_dir).as_posix(),
            "sha256": _digest(artifact_bytes),
            "size_bytes": len(artifact_bytes),
            "media_type": "image/gif" if plan.kind == "runtime-playback" else "image/png",
            "width": pixel_dimensions[0],
            "height": pixel_dimensions[1],
        },
        "sources": sources,
        "input_fingerprint": f"sha256:{fingerprint}",
        "state": plan.state,
        "frames": list(plan.frame_indices),
        "durations_ms": list(plan.durations_ms),
        "viewport": {"width": plan.viewport[0], "height": plan.viewport[1], "dpr": plan.dpr},
        "renderer": {
            "name": "spritesheet-expert-pillow-runtime-preview",
            "version": pillow_version,
        },
        "color_space": "sRGB",
        "background": plan.background,
        "sampling": plan.manifest["sampling_policy"]["filter"],
        "overlays": [],
        "placements": placements,
        "captured_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(evidence),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        raise RuntimePreviewError(
            "generated screenshot evidence is invalid: "
            + "; ".join(error.message for error in errors)
        )
    return evidence


def load_screenshot_evidence(
    source: Path,
    *,
    run_dir: Path,
    expected_kind: str | None = None,
    expected_state: str | None = None,
) -> Mapping[str, Any]:
    """Load evidence and prove every hash-bound artifact is current."""

    run_root = Path(run_dir).expanduser().resolve()
    try:
        evidence_path = Path(source).expanduser().resolve()
        evidence_path.relative_to(run_root)
    except (OSError, ValueError) as exc:
        raise RuntimePreviewError("screenshot evidence escapes the run directory") from exc
    try:
        document = json.loads(evidence_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise RuntimePreviewError(f"screenshot evidence is unreadable: {exc}") from exc
    if not isinstance(document, Mapping):
        raise RuntimePreviewError("screenshot evidence must be a JSON object")
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(document),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        raise RuntimePreviewError(
            "invalid screenshot evidence: "
            + "; ".join(error.message for error in errors)
        )
    if expected_kind is not None and document["evidence_kind"] != expected_kind:
        raise RuntimePreviewError(
            f"expected {expected_kind} evidence, got {document['evidence_kind']}"
        )
    if expected_state is not None and document["state"] != expected_state:
        raise RuntimePreviewError(
            f"expected state {expected_state!r}, got {document['state']!r}"
        )

    records = [document["artifact"], *document["sources"]]
    for record in records:
        try:
            path = resolve_run_path(run_root, record["path"])
        except PathSafetyError as exc:
            raise RuntimePreviewError(str(exc)) from exc
        if not path.is_file():
            raise RuntimePreviewError(f"screenshot evidence artifact is missing: {record['path']}")
        content = path.read_bytes()
        if len(content) != record["size_bytes"] or _digest(content) != record["sha256"]:
            raise RuntimePreviewError(f"screenshot evidence artifact is stale: {record['path']}")
    artifact = document["artifact"]
    artifact_path = resolve_run_path(run_root, artifact["path"])
    try:
        with Image.open(artifact_path) as opened:
            opened.verify()
        with Image.open(artifact_path) as opened:
            dimensions = opened.size
            media = opened.format
    except (OSError, ValueError) as exc:
        raise RuntimePreviewError("screenshot evidence artifact is not decodable") from exc
    if dimensions != (artifact["width"], artifact["height"]):
        raise RuntimePreviewError("screenshot evidence dimensions are stale")
    expected_media = "PNG" if artifact["media_type"] == "image/png" else "GIF"
    if media != expected_media:
        raise RuntimePreviewError("screenshot evidence media type is incorrect")
    source_roles = [record["role"] for record in document["sources"]]
    if source_roles.count("manifest") != 1 or source_roles.count("atlas") != 1:
        raise RuntimePreviewError("runtime evidence requires exactly one manifest and atlas source")
    return document
