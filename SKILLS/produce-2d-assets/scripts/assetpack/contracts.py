from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, validators
from jsonschema.exceptions import ValidationError
from referencing import Registry, Resource

from .paths import AssetPackPathError, portable_relative_parts


@dataclass(frozen=True, slots=True)
class AssetPackContractIssue:
    """One machine-readable validation issue with a human-readable message."""

    code: str
    path: str
    message: str


@dataclass(frozen=True, slots=True)
class AssetValidationReference:
    """Canonical leaf report reference declared by one inventory asset."""

    asset_id: str
    asset_kind: str
    path: str
    sha256: str
    input_fingerprint: str
    status: str
    required_variants: tuple[str, ...]


class AssetPackContractError(ValueError):
    """Raised when an asset-pack document violates its public contract."""

    def __init__(
        self, issues: str | list[AssetPackContractIssue | str]
    ) -> None:
        if isinstance(issues, str):
            self.issues = (AssetPackContractIssue("contract", "$", issues),)
            super().__init__(issues)
            return
        self.issues = tuple(
            issue
            if isinstance(issue, AssetPackContractIssue)
            else AssetPackContractIssue("semantic", "$", issue)
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


def _load_validator() -> Draft202012Validator:
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
        if schema["$id"].endswith("/asset-pack.schema.json")
    )
    return _MAPPING_VALIDATOR(root, registry=registry)


_VALIDATOR = _load_validator()


def _schema_path(error: ValidationError) -> str:
    path = "$"
    for part in error.absolute_path:
        path += f"[{part}]" if isinstance(part, int) else f".{part}"
    return path


def _schema_issue(error: ValidationError) -> AssetPackContractIssue:
    return AssetPackContractIssue(
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


def _inventory_graph_errors(assets: list[Mapping[str, Any]]) -> list[str]:
    graph = {asset["id"]: list(asset["depends_on"]) for asset in assets}
    errors = [
        f"asset '{asset_id}' depends on unknown asset '{dependency}'"
        for asset_id, dependencies in graph.items()
        for dependency in dependencies
        if dependency not in graph
    ]
    state: dict[str, int] = {}
    stack: list[str] = []

    def visit(asset_id: str) -> None:
        if state.get(asset_id) == 2:
            return
        if state.get(asset_id) == 1:
            start = stack.index(asset_id)
            cycle = [*stack[start:], asset_id]
            errors.append(f"inventory dependency cycle: {' -> '.join(cycle)}")
            return
        state[asset_id] = 1
        stack.append(asset_id)
        for dependency in graph[asset_id]:
            if dependency in graph:
                visit(dependency)
        stack.pop()
        state[asset_id] = 2

    for asset_id in graph:
        visit(asset_id)
    return errors


def _variant_errors(
    assets: list[Mapping[str, Any]],
    declared_axes: Mapping[str, list[Any]],
    variants: list[Mapping[str, Any]],
    deliverables: list[Mapping[str, Any]],
) -> list[str]:
    asset_ids = {asset["id"] for asset in assets}
    variants_by_id = {variant["id"]: variant for variant in variants}
    errors = [
        f"variant '{variant['id']}' references unknown asset '{variant['asset_id']}'"
        for variant in variants
        if variant["asset_id"] not in asset_ids
    ]
    for variant in variants:
        for axis_id, value in variant["axes"].items():
            if axis_id not in declared_axes:
                errors.append(
                    f"variant '{variant['id']}' uses undeclared axis '{axis_id}'"
                )
            elif value not in declared_axes[axis_id]:
                errors.append(
                    f"variant '{variant['id']}' uses disallowed value {value!r} "
                    f"for axis '{axis_id}'"
                )
    for asset in assets:
        for variant_id in asset["required_variants"]:
            variant = variants_by_id.get(variant_id)
            if variant is None or variant["asset_id"] != asset["id"]:
                errors.append(
                    f"asset '{asset['id']}' requires unresolved variant '{variant_id}'"
                )
    for item in deliverables:
        if item["asset_id"] not in asset_ids:
            errors.append(
                f"deliverable '{item['id']}' references unknown asset '{item['asset_id']}'"
            )
        variant_id = item.get("variant_id")
        if variant_id is None:
            continue
        variant = variants_by_id.get(variant_id)
        if variant is None or variant["asset_id"] != item["asset_id"]:
            errors.append(
                f"deliverable '{item['id']}' references unresolved variant '{variant_id}'"
            )
    delivered_variants = {
        item["variant_id"] for item in deliverables if item.get("variant_id") is not None
    }
    for asset in assets:
        for variant_id in asset["required_variants"]:
            if variant_id not in delivered_variants:
                errors.append(
                    f"required variant '{variant_id}' for asset '{asset['id']}' has no deliverable"
                )
    return errors


def _is_portable_relative_path(value: str) -> bool:
    try:
        portable_relative_parts(value)
    except AssetPackPathError:
        return False
    return True


def _semantic_errors(
    document: Mapping[str, Any],
) -> list[AssetPackContractIssue | str]:
    assets = document["inventory"]["assets"]
    variants = document["variant_matrix"]["variants"]
    deliverables = document["delivery_manifest"]["deliverables"]
    assets_by_id = {asset["id"]: asset for asset in assets}
    known_owners = {record["id"] for record in document["owners"]}
    owner_errors = [
        f"asset '{asset['id']}' has unknown owner '{asset['owner']}'"
        for asset in assets
        if asset["owner"] not in known_owners
    ]
    owner_errors.extend(
        f"deliverable '{item['id']}' has unknown owner '{item['owner']}'"
        for item in deliverables
        if item["owner"] not in known_owners
    )
    for index, item in enumerate(deliverables):
        asset = assets_by_id.get(item["asset_id"])
        if asset is not None and item["owner"] != asset["owner"]:
            owner_errors.append(
                AssetPackContractIssue(
                    code="owner_mismatch",
                    path=f"$.delivery_manifest.deliverables[{index}].owner",
                    message=(
                        f"deliverable '{item['id']}' owner '{item['owner']}' does not match "
                        f"asset '{item['asset_id']}' owner '{asset['owner']}'"
                    ),
                )
            )
    path_errors = [
        f"deliverable '{item['id']}' path must be a portable relative path"
        for item in deliverables
        if not _is_portable_relative_path(item["path"])
    ]
    path_errors.extend(
        f"style reference path must be a portable relative path: {reference!r}"
        for reference in document["style_bible"]["references"]
        if not _is_portable_relative_path(reference)
    )
    path_errors.extend(
        f"asset '{asset['id']}' validation report path must be a portable relative path"
        for asset in assets
        if not _is_portable_relative_path(asset["validation_report"]["path"])
    )
    return [
        *_duplicate_id_errors("owner", document["owners"]),
        *_duplicate_id_errors("inventory asset", assets),
        *_duplicate_id_errors("variant", variants),
        *_duplicate_id_errors("deliverable", deliverables),
        *owner_errors,
        *path_errors,
        *_inventory_graph_errors(assets),
        *_variant_errors(
            assets, document["variant_matrix"].get("axes", {}), variants, deliverables
        ),
    ]


def validate_asset_pack(document: Mapping[str, Any]) -> Mapping[str, Any]:
    """Validate one complete 2D asset-pack contract and return it unchanged."""

    errors = sorted(_VALIDATOR.iter_errors(document), key=lambda item: list(item.absolute_path))
    if errors:
        raise AssetPackContractError([_schema_issue(error) for error in errors])
    semantic_errors = _semantic_errors(document)
    if semantic_errors:
        raise AssetPackContractError(semantic_errors)
    return document
