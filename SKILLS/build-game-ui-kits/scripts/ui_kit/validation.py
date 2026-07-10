"""State parity, density, contrast and nine-slice QA for raster UI kits."""

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
from PIL import Image, ImageDraw


class UiKitError(ValueError):
    def __init__(self, issues: list[str]):
        self.issues = tuple(issues)
        super().__init__("invalid UI kit: " + "; ".join(issues))


_SCHEMA = json.loads((Path(__file__).resolve().parents[2] / "references" / "schemas" / "ui-kit-v1.schema.json").read_text(encoding="utf-8"))
Draft202012Validator.check_schema(_SCHEMA)
_VALIDATOR = validators.extend(
    Draft202012Validator,
    type_checker=Draft202012Validator.TYPE_CHECKER.redefine("object", lambda _checker, value: isinstance(value, Mapping)),
)(_SCHEMA)
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def resolve_kit_path(root: Path, value: str) -> Path:
    if unicodedata.normalize("NFC", value) != value or not value or "\\" in value or value.startswith("/") or ":" in value:
        raise UiKitError([f"component path must be portable and NFC relative: {value!r}"])
    parts = value.split("/")
    if any(part in {"", ".", ".."} or part.rstrip(" .") != part or part.split(".", 1)[0].upper() in _RESERVED or any(unicodedata.category(char) in {"Cc", "Cf"} for char in part) for part in parts):
        raise UiKitError([f"unsafe component path or traversal: {value!r}"])
    target = (root / Path(*parts)).resolve()
    if not target.is_relative_to(root):
        raise UiKitError([f"component path escapes kit root: {value!r}"])
    return target


def _hash(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_save(image: Image.Image, path: Path, *, format: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        image.save(temporary, format=format)
        with temporary.open("r+b") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _rgb(value: str) -> tuple[int, int, int]:
    return tuple(int(value[index:index + 2], 16) for index in (1, 3, 5))  # type: ignore[return-value]


def _luminance(color: tuple[int, int, int]) -> float:
    channels = []
    for value in color:
        normalized = value / 255
        channels.append(normalized / 12.92 if normalized <= 0.04045 else ((normalized + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _contrast(foreground: str, background: str) -> float:
    first, second = _luminance(_rgb(foreground)), _luminance(_rgb(background))
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


def _proof_path(root: Path, value: Path, label: str) -> Path:
    target = Path(value).expanduser().resolve()
    if not target.is_relative_to(root):
        raise UiKitError([f"{label} proof path must stay inside kit root"])
    return target


def _nine_slice(image: Image.Image, guides: Mapping[str, Any], target: tuple[int, int]) -> Image.Image:
    source = image.convert("RGBA")
    left, top, right, bottom = (guides[key] for key in ("left", "top", "right", "bottom"))
    sw, sh = source.size
    tw, th = target
    xs = (0, left, sw - right, sw)
    ys = (0, top, sh - bottom, sh)
    tx = (0, left, tw - right, tw)
    ty = (0, top, th - bottom, th)
    output = Image.new("RGBA", target, (0, 0, 0, 0))
    for row in range(3):
        for column in range(3):
            patch = source.crop((xs[column], ys[row], xs[column + 1], ys[row + 1]))
            size = (tx[column + 1] - tx[column], ty[row + 1] - ty[row])
            if patch.size != size:
                patch = patch.resize(size, Image.Resampling.NEAREST)
            output.alpha_composite(patch, (tx[column], ty[row]))
    return output


def _state_board(records: list[dict[str, Any]], path: Path) -> dict[str, Any]:
    cell_w, cell_h = 112, 72
    columns = min(4, max(1, len(records)))
    rows = (len(records) + columns - 1) // columns
    board = Image.new("RGBA", (columns * cell_w, rows * cell_h), (24, 24, 28, 255))
    draw = ImageDraw.Draw(board)
    for index, record in enumerate(records):
        image = record["image"].copy()
        image.thumbnail((96, 48), Image.Resampling.NEAREST)
        x, y = (index % columns) * cell_w, (index // columns) * cell_h
        board.alpha_composite(image, (x + (cell_w - image.width) // 2, y + 2))
        draw.text((x + 4, y + 52), f"{record['component']}:{record['state']}@{record['density']}x", fill=(245, 245, 245, 255))
    _atomic_save(board, path, format="PNG")
    return {"path": str(path), "sha256": _hash(path)}


def validate_ui_kit(
    document: Mapping[str, Any],
    *,
    root: Path,
    state_board_path: Path | None = None,
    stretch_board_path: Path | None = None,
) -> dict[str, Any]:
    schema_errors = sorted(_VALIDATOR.iter_errors(document), key=lambda error: list(error.absolute_path))
    if schema_errors:
        raise UiKitError([f"{'.'.join(map(str, error.absolute_path)) or '$'}: {error.message}" for error in schema_errors])
    densities = set(document["densities"])
    contrast = _contrast(document["tokens"]["foreground"], document["tokens"]["background"])
    issues: list[str] = []
    if contrast < document["tokens"]["minimum_contrast"]:
        issues.append(f"token contrast {contrast:.2f} is below {document['tokens']['minimum_contrast']:.2f}")
    components = list(document["components"])
    ids = [component["id"] for component in components]
    if len(ids) != len(set(ids)):
        issues.append("component ids must be unique")
    root = Path(root).expanduser().resolve()
    state_board_target = (
        _proof_path(root, state_board_path, "state board")
        if state_board_path is not None
        else None
    )
    stretch_board_target = (
        _proof_path(root, stretch_board_path, "stretch board")
        if stretch_board_path is not None
        else None
    )
    proof_targets = [
        target
        for target in (state_board_target, stretch_board_target)
        if target is not None
    ]
    if len(proof_targets) != len(set(proof_targets)):
        issues.append("proof output paths must be distinct")
    records: list[dict[str, Any]] = []
    stretch_records: list[tuple[str, Image.Image]] = []
    source_paths: set[Path] = set()
    for component in components:
        states = component["states"]
        for required in component["required_states"]:
            if required not in states:
                issues.append(f"component {component['id']}: missing required state {required}")
        base_size = (component["base_size"]["width"], component["base_size"]["height"])
        guides = component.get("nine_slice")
        if guides:
            left, top, right, bottom = (guides[key] for key in ("left", "top", "right", "bottom"))
            if left + right >= base_size[0] or top + bottom >= base_size[1]:
                issues.append(f"component {component['id']}: invalid nine_slice margins")
            safe = guides["content_safe"]
            if safe["x"] < left or safe["y"] < top or safe["x"] + safe["width"] > base_size[0] - right or safe["y"] + safe["height"] > base_size[1] - bottom:
                issues.append(f"component {component['id']}: content_safe leaves nine-slice center")
        for state, variants in states.items():
            seen_densities = [variant["density"] for variant in variants]
            if set(seen_densities) != densities or len(seen_densities) != len(set(seen_densities)):
                issues.append(f"component {component['id']} state {state}: density variants must equal {sorted(densities)}")
            for variant in variants:
                try:
                    path = resolve_kit_path(root, variant["path"])
                except UiKitError as exc:
                    issues.extend(f"component {component['id']} state {state}: {issue}" for issue in exc.issues)
                    continue
                if not path.is_file():
                    issues.append(f"component {component['id']} state {state}: missing variant image")
                    continue
                actual_hash = _hash(path)
                if actual_hash != variant["sha256"]:
                    issues.append(f"component {component['id']} state {state}: sha256 mismatch")
                    continue
                try:
                    with Image.open(path) as opened:
                        image = opened.convert("RGBA")
                except OSError as exc:
                    issues.append(f"component {component['id']} state {state}: unreadable image: {exc}")
                    continue
                expected = (base_size[0] * variant["density"], base_size[1] * variant["density"])
                if image.size != expected:
                    issues.append(f"component {component['id']} state {state}: dimensions {image.size} do not match density target {expected}")
                source_paths.add(path)
                records.append({"component": component["id"], "state": state, "density": variant["density"], "path": variant["path"], "sha256": actual_hash, "image": image})
                if guides and variant["density"] == 1 and state == component["required_states"][0]:
                    stretch_records.append((component["id"], _nine_slice(image, guides, (base_size[0] * 2, base_size[1] * 2))))
    if any(target in source_paths for target in proof_targets):
        issues.append("proof output paths must not overwrite component inputs")
    if issues:
        raise UiKitError(sorted(set(issues)))
    state_board = _state_board(records, state_board_target) if state_board_target else None
    if state_board is not None and state_board_target is not None:
        state_board["path"] = state_board_target.relative_to(root).as_posix()
    stretch_board = None
    if stretch_board_target:
        width = max(image.width for _id, image in stretch_records) if stretch_records else 1
        height = sum(image.height + 20 for _id, image in stretch_records) or 1
        board = Image.new("RGBA", (width, height), (24, 24, 28, 255))
        draw = ImageDraw.Draw(board)
        y = 0
        for component_id, image in stretch_records:
            board.alpha_composite(image, (0, y))
            draw.text((4, y + image.height + 2), component_id, fill=(245, 245, 245, 255))
            y += image.height + 20
        target = stretch_board_target
        _atomic_save(board, target, format="PNG")
        stretch_board = {
            "path": target.relative_to(root).as_posix(),
            "sha256": _hash(target),
        }
    return {
        "version": 1,
        "kind": "ui-kit-validation",
        "ok": True,
        "kit_id": document["kit_id"],
        "checked_components": sorted(ids),
        "contrast_ratio": round(contrast, 4),
        "state_board": state_board,
        "stretch_board": stretch_board,
        "variants": [{key: value for key, value in record.items() if key != "image"} for record in records],
        "errors": [],
        "warnings": [],
    }
