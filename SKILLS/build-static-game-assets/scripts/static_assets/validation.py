"""Executable contract and deterministic QA for loose static raster packs."""

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


class StaticAssetPackError(ValueError):
    def __init__(self, issues: list[str]):
        self.issues = tuple(issues)
        super().__init__("invalid static asset pack: " + "; ".join(issues))


_SCHEMA = json.loads(
    (
        Path(__file__).resolve().parents[2]
        / "references"
        / "schemas"
        / "static-asset-pack-v1.schema.json"
    ).read_text(encoding="utf-8")
)
Draft202012Validator.check_schema(_SCHEMA)
_MAPPING_VALIDATOR = validators.extend(
    Draft202012Validator,
    type_checker=Draft202012Validator.TYPE_CHECKER.redefine(
        "object", lambda _checker, instance: isinstance(instance, Mapping)
    ),
)
_VALIDATOR = _MAPPING_VALIDATOR(_SCHEMA)
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
_ISOLATED_ROLES = {"prop", "item", "pickup", "icon", "cursor", "badge"}


def _check_provider_record(
    provenance: Mapping[str, Any], root: Path, label: str, issues: list[str]
) -> dict[str, Any] | None:
    pin = provenance.get("provider_record")
    if pin is None:
        return None
    try:
        path = resolve_pack_path(root, pin["path"])
    except StaticAssetPackError as exc:
        issues.extend(f"{label} provider record: {issue}" for issue in exc.issues)
        return None
    if not path.is_file():
        issues.append(f"{label}: provider record does not exist: {pin['path']}")
        return None
    actual = _hash(path)
    if actual != pin["sha256"]:
        issues.append(f"{label}: provider record sha256 mismatch")
    return {"path": pin["path"], "sha256": actual, "verified": actual == pin["sha256"]}


def _schema_path(error: Any) -> str:
    path = "$"
    for part in error.absolute_path:
        path += f"[{part}]" if isinstance(part, int) else f".{part}"
    return path


def resolve_pack_path(root: Path, value: str) -> Path:
    if unicodedata.normalize("NFC", value) != value:
        raise StaticAssetPackError([f"path must be NFC-normalized: {value!r}"])
    if not value or "\\" in value or value.startswith("/") or ":" in value:
        raise StaticAssetPackError([f"path must be portable and relative: {value!r}"])
    parts = value.split("/")
    if any(
        part in {"", ".", ".."}
        or any(unicodedata.category(char) in {"Cc", "Cf"} for char in part)
        or part.rstrip(" .") != part
        or part.split(".", 1)[0].upper() in _RESERVED
        for part in parts
    ):
        raise StaticAssetPackError([f"unsafe path component or traversal: {value!r}"])
    target = (root / Path(*parts)).resolve()
    if not target.is_relative_to(root):
        raise StaticAssetPackError([f"path escapes pack root: {value!r}"])
    return target


def _hash(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _proof_path(root: Path, value: Path) -> Path:
    target = Path(value).expanduser().resolve()
    if not target.is_relative_to(root):
        raise StaticAssetPackError(["contact-sheet proof path must stay inside pack root"])
    return target


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


def _preview_backdrop(name: str, size: tuple[int, int]) -> Image.Image:
    colors = {
        "black": (0, 0, 0, 255),
        "gray": (128, 128, 128, 255),
        "white": (255, 255, 255, 255),
    }
    if name in colors:
        return Image.new("RGBA", size, colors[name])
    tile = 8
    backdrop = Image.new("RGBA", size, (224, 224, 224, 255))
    draw = ImageDraw.Draw(backdrop)
    for y in range(0, size[1], tile):
        for x in range(0, size[0], tile):
            if (x // tile + y // tile) % 2:
                draw.rectangle((x, y, x + tile - 1, y + tile - 1), fill=(176, 176, 176, 255))
    return backdrop


def _variant_issues(assets: list[Mapping[str, Any]]) -> list[str]:
    by_id = {asset["id"]: asset for asset in assets}
    issues: list[str] = []
    graph: dict[str, str] = {}
    for asset in assets:
        parent = asset.get("variant_of")
        if parent is None:
            continue
        if parent not in by_id:
            issues.append(f"variant {asset['id']} references unknown parent {parent}")
            continue
        graph[asset["id"]] = parent
        if asset["parent_sha256"] != by_id[parent]["source"]["sha256"]:
            issues.append(f"variant {asset['id']} has stale parent_sha256")
    for start in graph:
        seen: list[str] = []
        current = start
        while current in graph:
            if current in seen:
                issues.append("variant cycle: " + " -> ".join([*seen[seen.index(current):], current]))
                break
            seen.append(current)
            current = graph[current]
    return sorted(set(issues))


def _render_contact(records: list[dict[str, Any]], target: Path) -> dict[str, Any]:
    views = ("checker", "black", "gray", "white")
    panel = 64
    cell_width = panel * len(views)
    cell_height = panel + 24
    columns = min(2, max(1, len(records)))
    rows = (len(records) + columns - 1) // columns
    board = Image.new("RGBA", (columns * cell_width, rows * cell_height), (24, 24, 28, 255))
    draw = ImageDraw.Draw(board)
    for index, record in enumerate(records):
        with Image.open(record["absolute_path"]) as opened:
            thumb = opened.convert("RGBA")
        thumb.thumbnail((panel - 12, panel - 12), Image.Resampling.NEAREST)
        left = (index % columns) * cell_width
        top = (index // columns) * cell_height
        for view_index, view in enumerate(views):
            backdrop = _preview_backdrop(view, (panel, panel))
            backdrop.alpha_composite(thumb, ((panel - thumb.width) // 2, (panel - thumb.height) // 2))
            board.alpha_composite(backdrop, (left + view_index * panel, top))
            draw.text((left + view_index * panel + 3, top + 3), view[0].upper(), fill=(255, 96, 96, 255))
        draw.text((left + 4, top + panel + 4), record["id"], fill=(245, 245, 245, 255))
    _atomic_save(board, target, format="PNG")
    return {
        "path": str(target),
        "sha256": _hash(target),
        "width": board.width,
        "height": board.height,
        "views": list(views),
    }


def validate_static_pack(
    document: Mapping[str, Any],
    *,
    root: Path,
    contact_sheet: Path | None = None,
) -> dict[str, Any]:
    """Validate current source bytes, runtime semantics, lineage and licenses."""

    schema_errors = sorted(_VALIDATOR.iter_errors(document), key=lambda error: list(error.absolute_path))
    if schema_errors:
        raise StaticAssetPackError([f"{_schema_path(error)}: {error.message}" for error in schema_errors])
    assets = list(document["assets"])
    ids = [asset["id"] for asset in assets]
    license_ids = [license_entry["id"] for license_entry in document["licenses"]]
    licenses_by_id = {license_entry["id"]: license_entry for license_entry in document["licenses"]}
    issues: list[str] = []
    if len(ids) != len(set(ids)):
        issues.append("asset ids must be unique")
    if len(license_ids) != len(set(license_ids)):
        issues.append("license ids must be unique")
    issues.extend(
        f"asset {asset['id']} references unknown license {asset['license_ref']}"
        for asset in assets
        if asset["license_ref"] not in set(license_ids)
    )
    issues.extend(_variant_issues(assets))
    root = Path(root).expanduser().resolve()
    contact_target = (
        _proof_path(root, contact_sheet) if contact_sheet is not None else None
    )
    records: list[dict[str, Any]] = []
    for asset in assets:
        provenance = asset["source"]["provenance"]
        license_entry = licenses_by_id.get(asset["license_ref"])
        expected_license_status = {
            "imagegen": "generated",
            "grok-imagine-image": "generated",
            "fixture": "fixture",
        }.get(provenance["source_type"])
        if expected_license_status and license_entry is not None and license_entry["status"] != expected_license_status:
            issues.append(
                f"asset {asset['id']}: {provenance['source_type']} provenance requires "
                f"a {expected_license_status} license status"
            )
        if (
            provenance["source_type"] == "imported"
            and license_entry is not None
            and license_entry["status"] not in {"user-owned", "licensed"}
        ):
            issues.append(
                f"asset {asset['id']}: imported provenance requires a user-owned or licensed status"
            )
        provider_record = _check_provider_record(
            provenance, root, f"asset {asset['id']}", issues
        )
        try:
            path = resolve_pack_path(root, asset["source"]["path"])
        except StaticAssetPackError as exc:
            issues.extend(f"asset {asset['id']}: {issue}" for issue in exc.issues)
            continue
        if not path.is_file():
            issues.append(f"asset {asset['id']}: source does not exist: {asset['source']['path']}")
            continue
        actual_hash = _hash(path)
        if actual_hash != asset["source"]["sha256"]:
            issues.append(f"asset {asset['id']}: source sha256 mismatch")
            continue
        try:
            with Image.open(path) as opened:
                image = opened.convert("RGBA")
        except OSError as exc:
            issues.append(f"asset {asset['id']}: source is not a readable image: {exc}")
            continue
        expected_size = (asset["target"]["width"], asset["target"]["height"])
        if image.size != expected_size:
            issues.append(f"asset {asset['id']}: dimensions {image.size} do not match target {expected_size}")
        alpha_min, alpha_max = image.getchannel("A").getextrema()
        if asset["transparency"] == "required" and not (alpha_min < 255 and alpha_max > 0):
            issues.append(f"asset {asset['id']}: required transparency is absent")
        if asset["transparency"] == "opaque" and alpha_min != 255:
            issues.append(f"asset {asset['id']}: opaque policy forbids transparent pixels")
        bbox = image.getchannel("A").getbbox()
        opaque = sum(image.getchannel("A").histogram()[1:])
        ratio = opaque / (image.width * image.height)
        if bbox is None:
            issues.append(f"asset {asset['id']}: blank image")
        elif asset["role"] in _ISOLATED_ROLES and (
            bbox[0] == 0 or bbox[1] == 0 or bbox[2] == image.width or bbox[3] == image.height
        ):
            issues.append(f"asset {asset['id']}: isolated silhouette is clipped at an edge")
        if ratio < 0.01 or (asset["role"] in _ISOLATED_ROLES and ratio > 0.95):
            issues.append(f"asset {asset['id']}: extreme target-size occupancy {ratio:.4f}")
        records.append(
            {
                "id": asset["id"],
                "role": asset["role"],
                "path": asset["source"]["path"],
                "absolute_path": str(path),
                "sha256": actual_hash,
                "dimensions": list(image.size),
                "opaque_ratio": round(ratio, 6),
                "bbox": list(bbox) if bbox else None,
                "pivot": dict(asset["pivot"]),
                "provenance": {
                    **dict(provenance),
                    **({"provider_record": provider_record} if provider_record else {}),
                },
            }
        )
    if contact_target is not None and any(
        contact_target == Path(record["absolute_path"]) for record in records
    ):
        issues.append("contact-sheet proof path must not overwrite an asset input")
    if issues:
        raise StaticAssetPackError(sorted(set(issues)))
    representative = all(
        not asset["source"]["provenance"]["fixture"] for asset in assets
    )
    source_types = sorted(
        {asset["source"]["provenance"]["source_type"] for asset in assets}
    )
    report: dict[str, Any] = {
        "version": 1,
        "kind": "static-asset-pack-validation",
        "ok": True,
        "pack_id": document["pack_id"],
        "style_fingerprint": document["style_fingerprint"],
        "representative": representative,
        "source_types": source_types,
        "evidence": {
            "production_media": {
                "representative": representative,
                "provenance_verified": True,
                "source_types": source_types,
            }
        },
        "checked_assets": sorted(ids),
        "assets": [
            {key: value for key, value in record.items() if key != "absolute_path"}
            for record in records
        ],
        "errors": [],
        "warnings": [],
    }
    if contact_target is not None:
        report["contact_sheet"] = _render_contact(records, contact_target)
        report["contact_sheet"]["path"] = contact_target.relative_to(root).as_posix()
    return report
