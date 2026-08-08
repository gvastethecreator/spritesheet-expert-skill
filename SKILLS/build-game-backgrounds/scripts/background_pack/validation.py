"""Layer, seam, camera and parallax QA for deterministic background packs."""

from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
import unicodedata
from typing import Any

from jsonschema import Draft202012Validator, validators
from PIL import Image, ImageChops


class BackgroundPackError(ValueError):
    def __init__(self, issues: list[str]):
        self.issues = tuple(issues)
        super().__init__("invalid background pack: " + "; ".join(issues))


_SCHEMA = json.loads((Path(__file__).resolve().parents[2] / "references" / "schemas" / "background-pack-v1.schema.json").read_text(encoding="utf-8"))
Draft202012Validator.check_schema(_SCHEMA)
_VALIDATOR = validators.extend(
    Draft202012Validator,
    type_checker=Draft202012Validator.TYPE_CHECKER.redefine("object", lambda _checker, value: isinstance(value, Mapping)),
)(_SCHEMA)
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def _check_provider_record(
    provenance: Mapping[str, Any], root: Path, label: str, issues: list[str]
) -> dict[str, Any] | None:
    pin = provenance.get("provider_record")
    if pin is None:
        return None
    try:
        path = resolve_pack_path(root, pin["path"])
    except BackgroundPackError as exc:
        issues.extend(f"{label} provider record: {issue}" for issue in exc.issues)
        return None
    if not path.is_file():
        issues.append(f"{label}: provider record does not exist: {pin['path']}")
        return None
    actual = _hash(path)
    if actual != pin["sha256"]:
        issues.append(f"{label}: provider record sha256 mismatch")
    return {"path": pin["path"], "sha256": actual, "verified": actual == pin["sha256"]}


def resolve_pack_path(root: Path, value: str) -> Path:
    if unicodedata.normalize("NFC", value) != value or not value or "\\" in value or value.startswith("/") or ":" in value:
        raise BackgroundPackError([f"layer path must be portable and NFC relative: {value!r}"])
    parts = value.split("/")
    if any(part in {"", ".", ".."} or part.rstrip(" .") != part or part.split(".", 1)[0].upper() in _RESERVED or any(unicodedata.category(char) in {"Cc", "Cf"} for char in part) for part in parts):
        raise BackgroundPackError([f"unsafe layer path or traversal: {value!r}"])
    target = (root / Path(*parts)).resolve()
    if not target.is_relative_to(root):
        raise BackgroundPackError([f"layer path escapes pack root: {value!r}"])
    return target


def _hash(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_save(image: Image.Image, path: Path, *, format: str, **options: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        image.save(temporary, format=format, **options)
        with temporary.open("r+b") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _edge_delta(image: Image.Image) -> float:
    rgba = image.convert("RGBA")
    left = tuple(rgba.crop((0, 0, 1, rgba.height)).get_flattened_data())
    right = tuple(
        rgba.crop((rgba.width - 1, 0, rgba.width, rgba.height)).get_flattened_data()
    )
    difference = sum(abs(a - b) for lp, rp in zip(left, right) for a, b in zip(lp, rp))
    return difference / max(1, len(left) * 4 * 255)


def _proof_path(root: Path, value: Path, label: str) -> Path:
    target = Path(value).expanduser().resolve()
    if not target.is_relative_to(root):
        raise BackgroundPackError([f"{label} proof path must stay inside pack root"])
    return target


def _blend(canvas: Image.Image, layer: Image.Image, mode: str) -> Image.Image:
    if mode == "normal":
        canvas.alpha_composite(layer)
        return canvas
    base = canvas.convert("RGB")
    foreground = layer.convert("RGB")
    if mode == "screen":
        mixed = ImageChops.screen(base, foreground)
    elif mode == "multiply":
        mixed = ImageChops.multiply(base, foreground)
    else:
        mixed = ImageChops.add(base, foreground, scale=1.0, offset=0)
    mixed = mixed.convert("RGBA")
    mixed.putalpha(layer.getchannel("A"))
    canvas.alpha_composite(mixed)
    return canvas


def _composite(records: list[dict[str, Any]], size: tuple[int, int], offsets: Mapping[str, int] | None = None) -> Image.Image:
    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    for record in records:
        layer = record["image"]
        shift = (offsets or {}).get(record["id"], 0)
        if shift:
            shifted = Image.new("RGBA", size, (0, 0, 0, 0))
            if record["repeat_x"]:
                normalized = shift % size[0]
                shifted.alpha_composite(layer, (-normalized, 0))
                shifted.alpha_composite(layer, (size[0] - normalized, 0))
            else:
                # Non-repeating layers still need to move in the scroll proof.
                # Clip the translated layer at the canvas edge instead of
                # wrapping it; wrapping is reserved for explicitly tiled art.
                shifted.alpha_composite(layer, (shift, 0))
            layer = shifted
        _blend(canvas, layer, record["blend_mode"])
    return canvas


def _save_scroll(records: list[dict[str, Any]], size: tuple[int, int], path: Path) -> None:
    frames = []
    for step in range(4):
        offsets = {record["id"]: round(step * 8 * record["parallax_x"]) for record in records}
        frames.append(_composite(records, size, offsets))
    _atomic_save(
        frames[0],
        path,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        duration=160,
        loop=0,
        disposal=2,
    )


def validate_background_pack(
    document: Mapping[str, Any],
    *,
    root: Path,
    composite_path: Path | None = None,
    scroll_path: Path | None = None,
) -> dict[str, Any]:
    schema_errors = sorted(_VALIDATOR.iter_errors(document), key=lambda error: list(error.absolute_path))
    if schema_errors:
        raise BackgroundPackError([f"{'.'.join(map(str, error.absolute_path)) or '$'}: {error.message}" for error in schema_errors])
    layers = sorted(document["layers"], key=lambda layer: layer["order"])
    ids = [layer["id"] for layer in layers]
    orders = [layer["order"] for layer in layers]
    issues: list[str] = []
    if len(ids) != len(set(ids)):
        issues.append("layer ids must be unique")
    if len(orders) != len(set(orders)):
        issues.append("layer orders must be unique")
    if orders != list(range(len(orders))):
        issues.append("layer order must be contiguous from zero")
    for prior, current in zip(layers, layers[1:]):
        if current["depth"] < prior["depth"]:
            issues.append(f"depth inversion between {prior['id']} and {current['id']}")
        if current["parallax_x"] < prior["parallax_x"] or current["parallax_y"] < prior["parallax_y"]:
            issues.append(f"parallax inversion between {prior['id']} and {current['id']}")
    size = (document["canvas"]["width"], document["canvas"]["height"])
    root = Path(root).expanduser().resolve()
    composite_target = (
        _proof_path(root, composite_path, "composite")
        if composite_path is not None
        else None
    )
    scroll_target = (
        _proof_path(root, scroll_path, "scroll preview")
        if scroll_path is not None
        else None
    )
    proof_targets = [
        target for target in (composite_target, scroll_target) if target is not None
    ]
    if len(proof_targets) != len(set(proof_targets)):
        issues.append("proof output paths must be distinct")
    records: list[dict[str, Any]] = []
    for layer in layers:
        provider_record = _check_provider_record(
            layer["provenance"], root, f"layer {layer['id']}", issues
        )
        try:
            path = resolve_pack_path(root, layer["path"])
        except BackgroundPackError as exc:
            issues.extend(f"layer {layer['id']}: {issue}" for issue in exc.issues)
            continue
        if not path.is_file():
            issues.append(f"layer {layer['id']}: missing image")
            continue
        actual_hash = _hash(path)
        if actual_hash != layer["sha256"]:
            issues.append(f"layer {layer['id']}: sha256 mismatch")
            continue
        try:
            with Image.open(path) as opened:
                image = opened.convert("RGBA")
        except OSError as exc:
            issues.append(f"layer {layer['id']}: unreadable image: {exc}")
            continue
        if image.size != size:
            issues.append(f"layer {layer['id']}: dimensions {image.size} do not match canvas {size}")
        seam_delta = _edge_delta(image) if layer["repeat_x"] else None
        if seam_delta is not None and seam_delta > 0.03:
            issues.append(f"layer {layer['id']}: horizontal repeat seam delta {seam_delta:.4f}")
        records.append({
            **dict(layer),
            "provenance": {
                **dict(layer["provenance"]),
                **({"provider_record": provider_record} if provider_record else {}),
            },
            "absolute_path": str(path),
            "image": image,
            "seam_delta": seam_delta,
        })
    input_paths = {Path(record["absolute_path"]) for record in records}
    if any(target in input_paths for target in proof_targets):
        issues.append("proof output paths must not overwrite layer inputs")
    if issues:
        raise BackgroundPackError(sorted(set(issues)))
    composite_record = None
    scroll_record = None
    if composite_target is not None:
        target = composite_target
        image = _composite(records, size)
        _atomic_save(image, target, format="PNG")
        composite_record = {
            "path": target.relative_to(root).as_posix(),
            "sha256": _hash(target),
        }
    if scroll_target is not None:
        target = scroll_target
        _save_scroll(records, size, target)
        scroll_record = {
            "path": target.relative_to(root).as_posix(),
            "sha256": _hash(target),
        }
    representative = all(not layer["provenance"]["fixture"] for layer in layers)
    source_types = sorted({layer["provenance"]["source_type"] for layer in layers})
    return {
        "version": 1,
        "kind": "background-pack-validation",
        "ok": True,
        "pack_id": document["pack_id"],
        "representative": representative,
        "source_types": source_types,
        "evidence": {
            "production_media": {
                "representative": representative,
                "provenance_verified": True,
                "source_types": source_types,
            }
        },
        "checked_layers": ids,
        "camera": dict(document["camera"]),
        "layers": [{key: value for key, value in record.items() if key not in {"image", "absolute_path"}} for record in records],
        "composite": composite_record,
        "scroll_preview": scroll_record,
        "errors": [],
        "warnings": [],
    }
