from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker, validators
from jsonschema.exceptions import ValidationError
from referencing import Registry, Resource


@dataclass(frozen=True, slots=True)
class PresentationContractIssue:
    """One machine-readable validation issue with a human-readable message."""

    code: str
    path: str
    message: str


class PresentationContractError(ValueError):
    """Raised when a presentation document violates its public contract."""

    def __init__(
        self, issues: str | list[PresentationContractIssue | str]
    ) -> None:
        if isinstance(issues, str):
            self.issues = (PresentationContractIssue("contract", "$", issues),)
            super().__init__(issues)
            return
        self.issues = tuple(
            issue
            if isinstance(issue, PresentationContractIssue)
            else PresentationContractIssue("semantic", "$", issue)
            for issue in issues
        )
        super().__init__(
            "; ".join(f"{issue.path}: {issue.message}" for issue in self.issues)
        )


_SCHEMA_DIR = Path(__file__).resolve().parents[2] / "references" / "schemas"


def _is_mapping(_checker: Any, instance: Any) -> bool:
    return isinstance(instance, Mapping)


_MAPPING_VALIDATOR = validators.extend(
    Draft202012Validator,
    type_checker=Draft202012Validator.TYPE_CHECKER.redefine("object", _is_mapping),
)


def _load_named_validator(schema_name: str) -> Draft202012Validator:
    schemas = []
    for path in sorted(_SCHEMA_DIR.glob("*.schema.json")):
        schema = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        schemas.append(schema)
    registry = Registry().with_resources(
        (schema["$id"], Resource.from_contents(schema)) for schema in schemas
    )
    root = next(
        schema
        for schema in schemas
        if schema["$id"].endswith(f"/{schema_name}")
    )
    return _MAPPING_VALIDATOR(root, registry=registry, format_checker=FormatChecker())


def _load_validator() -> Draft202012Validator:
    return _load_named_validator("presentation.schema.json")


_VALIDATOR = _load_validator()


def _schema_path(error: ValidationError) -> str:
    path = "$"
    for part in error.absolute_path:
        path += f"[{part}]" if isinstance(part, int) else f".{part}"
    return path


def _schema_issue(error: ValidationError) -> PresentationContractIssue:
    return PresentationContractIssue(
        code=f"schema.{error.validator or 'validation'}",
        path=_schema_path(error),
        message=error.message,
    )


def _duplicate_id_errors(label: str, records: list[Mapping[str, Any]]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for record in records:
        record_id = str(record["id"])
        if record_id in seen:
            duplicates.add(record_id)
        seen.add(record_id)
    return [f"duplicate {label} id '{record_id}'" for record_id in sorted(duplicates)]


def _is_portable_relative_path(value: str) -> bool:
    if "\\" in value or value.startswith("/"):
        return False
    if len(value) >= 2 and value[0].isalpha() and value[1] == ":":
        return False
    return all(part not in {"", ".", ".."} for part in value.split("/"))


def _path_errors(document: Mapping[str, Any]) -> list[str]:
    paths: list[tuple[str, str]] = []
    for item in document["inventory"]["assets"]:
        for pin_name, pin in item["source"].items():
            paths.append((f"asset '{item['id']}' {pin_name}", pin["path"]))
    for item in document["brand_kit"]["fonts"]:
        for pin_name, pin in item["source"].items():
            paths.append((f"font '{item['id']}' {pin_name}", pin["path"]))
    paths.extend(
        (f"license '{item['id']}'", item["evidence"]["path"])
        for item in document["licenses"]
    )
    paths.extend(
        (f"provenance '{item['id']}'", item["source_path"])
        for item in document["provenance"]
    )
    paths.extend(
        (f"manifest output '{item['id']}'", item["path"])
        for item in document["manifest"]["outputs"]
    )
    for scene in document["gameplay_scenes"]:
        evidence = scene.get("capture_evidence")
        if evidence is not None:
            paths.append((f"scene '{scene['id']}' capture evidence", evidence["artifact_path"]))
    for source in document["provenance"]:
        evidence = source.get("capture_evidence")
        if evidence is not None:
            paths.append(
                (f"provenance '{source['id']}' capture evidence", evidence["artifact_path"])
            )
    return [
        f"{label} path must be a portable relative path"
        for label, value in paths
        if not _is_portable_relative_path(value)
    ]


def _composition_semantic_errors(
    document: Mapping[str, Any],
) -> list[PresentationContractIssue | str]:
    copy_ids = {item["id"] for item in document["brief"]["approved_copy"]}
    fonts = document["brand_kit"]["fonts"]
    font_ids = {item["id"] for item in fonts}
    errors: list[PresentationContractIssue | str] = [
        *_duplicate_id_errors("approved copy", document["brief"]["approved_copy"]),
        *_duplicate_id_errors("font", fonts),
    ]
    for composition_index, composition in enumerate(document["compositions"]):
        canvas = composition["canvas"]
        ratio = canvas["aspect_ratio"]
        if canvas["width"] * ratio["height"] != canvas["height"] * ratio["width"]:
            errors.append(
                PresentationContractIssue(
                    "aspect_ratio_mismatch",
                    f"$.compositions[{composition_index}].canvas.aspect_ratio",
                    f"declared aspect ratio does not match {canvas['width']}x{canvas['height']}",
                )
            )
        safe = canvas["safe_zone"]
        if safe["x"] + safe["width"] > canvas["width"] or safe["y"] + safe["height"] > canvas["height"]:
            errors.append(
                PresentationContractIssue(
                    "safe_zone_out_of_bounds",
                    f"$.compositions[{composition_index}].canvas.safe_zone",
                    "safe zone exceeds canvas bounds",
                )
            )
        for layer_index, layer in enumerate(composition["layers"]):
            if layer["layer_type"] == "text":
                if layer["copy_id"] not in copy_ids:
                    errors.append(
                        PresentationContractIssue(
                            "unknown_copy",
                            f"$.compositions[{composition_index}].layers[{layer_index}].copy_id",
                            f"text layer references unknown approved copy '{layer['copy_id']}'",
                        )
                    )
                if layer["font_id"] not in font_ids:
                    errors.append(
                        PresentationContractIssue(
                            "unknown_font",
                            f"$.compositions[{composition_index}].layers[{layer_index}].font_id",
                            f"text layer references unknown licensed font '{layer['font_id']}'",
                        )
                    )
    for scene_index, scene in enumerate(document["gameplay_scenes"]):
        if scene["truth_type"] != "runtime-captured" and "capture_evidence" in scene:
            errors.append(
                PresentationContractIssue(
                    "capture_truth_mismatch",
                    f"$.gameplay_scenes[{scene_index}].capture_evidence",
                    "capture evidence is reserved for runtime-captured truth",
                )
            )
    return errors


def _reference_errors(
    document: Mapping[str, Any],
) -> list[PresentationContractIssue | str]:
    assets = document["inventory"]["assets"]
    scenes = document["gameplay_scenes"]
    compositions = document["compositions"]
    licenses = document["licenses"]
    provenance = document["provenance"]
    outputs = document["manifest"]["outputs"]
    assets_by_id = {item["id"]: item for item in assets}
    asset_ids = set(assets_by_id)
    scenes_by_id = {item["id"]: item for item in scenes}
    scene_ids = set(scenes_by_id)
    composition_ids = {item["id"] for item in compositions}
    license_ids = {item["id"] for item in licenses}
    provenance_by_id = {item["id"]: item for item in provenance}
    fonts = document["brand_kit"]["fonts"]
    errors = [
        *_duplicate_id_errors("inventory asset", assets),
        *_duplicate_id_errors("gameplay scene", scenes),
        *_duplicate_id_errors("composition", compositions),
        *_duplicate_id_errors("license", licenses),
        *_duplicate_id_errors("provenance", provenance),
        *_duplicate_id_errors("manifest output", outputs),
        *_path_errors(document),
        *_composition_semantic_errors(document),
    ]
    for asset_index, asset in enumerate(assets):
        if asset["license_ref"] not in license_ids:
            errors.append(
                f"asset '{asset['id']}' references missing license '{asset['license_ref']}'"
            )
        source = provenance_by_id.get(asset["provenance_ref"])
        if source is None:
            errors.append(
                f"asset '{asset['id']}' references missing provenance '{asset['provenance_ref']}'"
            )
        elif source["asset_id"] != asset["id"]:
            errors.append(
                PresentationContractIssue(
                    code="provenance_owner_mismatch",
                    path=f"$.inventory.assets[{asset_index}].provenance_ref",
                    message=(
                        f"asset '{asset['id']}' references provenance "
                        f"'{asset['provenance_ref']}' belonging to asset "
                        f"'{source['asset_id']}'"
                    ),
                )
            )
        elif source["truth_type"] != asset["truth_type"]:
            errors.append(
                f"asset '{asset['id']}' truth type '{asset['truth_type']}' does not match "
                f"provenance '{source['id']}' truth type '{source['truth_type']}'"
            )
    for source in provenance:
        if source["asset_id"] not in asset_ids:
            errors.append(
                f"provenance '{source['id']}' references unknown asset '{source['asset_id']}'"
            )
    for scene in scenes:
        for asset_id in scene["asset_ids"]:
            if asset_id not in asset_ids:
                errors.append(
                    f"scene '{scene['id']}' references unknown asset '{asset_id}'"
                )
    for composition_index, composition in enumerate(compositions):
        composition_asset_ids = set(composition["asset_ids"])
        errors.extend(
            _duplicate_id_errors(
                f"composition '{composition['id']}' layer", composition["layers"]
            )
        )
        for layer in composition["layers"]:
            if layer["layer_type"] == "asset" and layer["asset_id"] not in composition_asset_ids:
                errors.append(
                    f"composition '{composition['id']}' layer '{layer['id']}' uses "
                    f"unlisted asset '{layer['asset_id']}'"
                )
        scene = scenes_by_id.get(composition["scene_id"])
        if scene is None:
            errors.append(
                f"composition '{composition['id']}' references unknown scene '{composition['scene_id']}'"
            )
        else:
            scene_asset_ids = set(scene["asset_ids"])
            for asset_index, asset_id in enumerate(composition["asset_ids"]):
                if asset_id not in scene_asset_ids:
                    errors.append(
                        PresentationContractIssue(
                            code="composition_asset_outside_scene",
                            path=(
                                f"$.compositions[{composition_index}]"
                                f".asset_ids[{asset_index}]"
                            ),
                            message=(
                                f"composition '{composition['id']}' uses asset '{asset_id}' "
                                f"outside scene '{scene['id']}'"
                            ),
                        )
                    )
        for asset_id in composition["asset_ids"]:
            if asset_id not in asset_ids:
                errors.append(
                    f"composition '{composition['id']}' references unknown asset '{asset_id}'"
                )
                continue
            asset = assets_by_id[asset_id]
            if asset["license_ref"] not in composition["license_refs"]:
                errors.append(
                    f"composition '{composition['id']}' omits license "
                    f"'{asset['license_ref']}' for asset '{asset_id}'"
                )
            if asset["provenance_ref"] not in composition["provenance_refs"]:
                errors.append(
                    f"composition '{composition['id']}' omits provenance "
                    f"'{asset['provenance_ref']}' for asset '{asset_id}'"
                )
        for license_id in composition["license_refs"]:
            if license_id not in license_ids:
                errors.append(
                    f"composition '{composition['id']}' references missing license '{license_id}'"
                )
        for provenance_id in composition["provenance_refs"]:
            if provenance_id not in provenance_by_id:
                errors.append(
                    f"composition '{composition['id']}' references missing provenance '{provenance_id}'"
                )
    for asset_id in document["brand_kit"].get("logo_asset_ids", []):
        if asset_id not in asset_ids:
            errors.append(f"brand kit references unknown logo asset '{asset_id}'")
    for font in fonts:
        if font["license_ref"] not in license_ids:
            errors.append(
                f"font '{font['id']}' references missing license '{font['license_ref']}'"
            )
    for output in outputs:
        if output["composition_id"] not in composition_ids:
            errors.append(
                f"manifest output '{output['id']}' references unknown composition '{output['composition_id']}'"
            )
    return errors


def validate_presentation(document: Mapping[str, Any]) -> Mapping[str, Any]:
    """Validate a complete asset-presentation contract and return it unchanged."""

    errors = sorted(_VALIDATOR.iter_errors(document), key=lambda item: list(item.absolute_path))
    if errors:
        raise PresentationContractError([_schema_issue(error) for error in errors])
    semantic_errors = _reference_errors(document)
    if semantic_errors:
        raise PresentationContractError(semantic_errors)
    return document


def validate_prepared_presentation(document: Mapping[str, Any]) -> Mapping[str, Any]:
    """Validate a canonical prepared-presentation envelope."""

    validator = _load_named_validator("prepared-presentation.schema.json")
    errors = sorted(validator.iter_errors(document), key=lambda item: list(item.absolute_path))
    if errors:
        raise PresentationContractError([_schema_issue(error) for error in errors])
    validate_presentation(document["presentation"])
    return document
