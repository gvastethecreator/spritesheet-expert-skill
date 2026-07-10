"""Pure aggregation of asset-pack deliverables and leaf validation reports."""

from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping

from .contracts import AssetValidationReference, validate_asset_pack
from .paths import AssetPackPathError, resolve_pack_path


_LEAF_STATUSES = frozenset(
    {"pass", "fail", "blocked", "operational-error", "skipped"}
)
_LEAF_FIELDS = (
    "id",
    "applicable",
    "checked_items",
    "errors",
    "warnings",
    "evidence",
    "input_fingerprint",
    "complete",
    "status",
)


def _sha256(content: bytes) -> str:
    return sha256(content).hexdigest()


def _references(document: Mapping[str, Any]) -> tuple[AssetValidationReference, ...]:
    return tuple(
        AssetValidationReference(
            asset_id=asset["id"],
            asset_kind=asset["kind"],
            path=asset["validation_report"]["path"],
            sha256=asset["validation_report"]["sha256"],
            input_fingerprint=asset["validation_report"]["input_fingerprint"],
            status=asset["validation_report"]["status"],
            required_variants=tuple(asset["required_variants"]),
        )
        for asset in sorted(document["inventory"]["assets"], key=lambda item: item["id"])
    )


def _leaf_shape_errors(leaf: Mapping[str, Any]) -> list[str]:
    errors = [f"missing field {field}" for field in _LEAF_FIELDS if field not in leaf]
    if "id" in leaf and (not isinstance(leaf["id"], str) or not leaf["id"]):
        errors.append("id must be a non-empty string")
    for field in ("applicable", "complete"):
        if field in leaf and type(leaf[field]) is not bool:
            errors.append(f"{field} must be a boolean")
    for field in ("checked_items", "errors", "warnings"):
        value = leaf.get(field)
        if field in leaf and (
            not isinstance(value, list)
            or any(not isinstance(item, str) or not item for item in value)
        ):
            errors.append(f"{field} must be an array of non-empty strings")
    if "evidence" in leaf and not isinstance(leaf["evidence"], Mapping):
        errors.append("evidence must be an object")
    fingerprint = leaf.get("input_fingerprint")
    if "input_fingerprint" in leaf and (
        not isinstance(fingerprint, str) or not fingerprint
    ):
        errors.append("input_fingerprint must be a non-empty string")
    if "status" in leaf and leaf["status"] not in _LEAF_STATUSES:
        errors.append("status is unknown")
    return errors


def aggregate_asset_pack(
    document: Mapping[str, Any],
    artifacts: Mapping[str, bytes],
    *,
    artifact_errors: Mapping[str, str] | None = None,
    pack_root: str | None = None,
) -> tuple[dict[str, Any], int]:
    """Validate supplied artifact bytes and return one deterministic report."""

    validate_asset_pack(document)
    artifact_errors = artifact_errors or {}
    blockers: list[str] = []
    outcomes: set[str] = set()
    style_bible = document["style_bible"]
    expected_style_tokens = {
        "palette": list(style_bible["palette"]),
        "projection": style_bible["projection"],
        "pixels_per_unit": style_bible["scale"]["pixels_per_unit"],
        "lighting": style_bible["lighting"],
        "line_weight": style_bible["line_weight"],
        "camera": style_bible["camera"],
        "shading": style_bible["shading"],
        "identity_tokens": list(style_bible["identity_tokens"]),
        "typography": list(style_bible["typography"]),
    }

    def block(message: str, outcome: str = "fail") -> None:
        blockers.append(message)
        outcomes.add(outcome)

    deliverable_results: list[dict[str, Any]] = []
    for item in sorted(
        document["delivery_manifest"]["deliverables"], key=lambda value: value["id"]
    ):
        content = artifacts.get(item["path"])
        actual_sha256 = _sha256(content) if isinstance(content, bytes) else None
        verified = actual_sha256 == item["sha256"]
        if content is None:
            read_error = artifact_errors.get(item["path"])
            if read_error:
                block(
                    f"deliverable {item['id']}: operational read failure: {read_error}",
                    "operational-error",
                )
            else:
                block(f"deliverable {item['id']}: missing artifact {item['path']}")
        elif not verified:
            block(f"deliverable {item['id']}: sha256 mismatch")
        deliverable_results.append(
            {
                "id": item["id"],
                "asset_id": item["asset_id"],
                "variant_id": item.get("variant_id"),
                "path": item["path"],
                "expected_sha256": item["sha256"],
                "actual_sha256": actual_sha256,
                "verified": verified,
            }
        )

    checked_assets: list[str] = []
    leaf_results: list[dict[str, Any]] = []
    for reference in _references(document):
        content = artifacts.get(reference.path)
        actual_sha256 = _sha256(content) if isinstance(content, bytes) else None
        leaf: Mapping[str, Any] | None = None
        shape_errors: list[str] = []
        if content is None:
            read_error = artifact_errors.get(reference.path)
            if read_error:
                block(
                    f"asset {reference.asset_id}: operational report read failure: {read_error}",
                    "operational-error",
                )
            else:
                block(
                    f"asset {reference.asset_id}: missing validation report {reference.path}"
                )
        else:
            try:
                decoded = json.loads(content.decode("utf-8-sig"))
            except (UnicodeDecodeError, ValueError):
                block(
                    f"asset {reference.asset_id}: malformed validation report {reference.path}"
                )
            else:
                if isinstance(decoded, Mapping):
                    leaf = decoded
                    shape_errors = _leaf_shape_errors(leaf)
                    if shape_errors:
                        block(
                            f"asset {reference.asset_id}: malformed validation report: "
                            + "; ".join(shape_errors)
                        )
                else:
                    block(
                        f"asset {reference.asset_id}: validation report must be a JSON object"
                    )

        checked = leaf.get("checked_items", []) if leaf is not None else []
        if isinstance(checked, list):
            checked_assets.extend(item for item in checked if isinstance(item, str))
        style_tokens_ok = False
        if leaf is not None and isinstance(leaf.get("evidence"), Mapping):
            candidate = leaf["evidence"].get("style_tokens")
            if isinstance(candidate, Mapping):
                mismatches = [
                    key
                    for key, expected in expected_style_tokens.items()
                    if candidate.get(key) != expected
                ]
                if mismatches:
                    for key in mismatches:
                        block(
                            f"asset {reference.asset_id}: style token {key} drifts from style bible"
                        )
                else:
                    style_tokens_ok = True
            else:
                block(f"asset {reference.asset_id}: style_tokens evidence is missing")
        verified = (
            leaf is not None
            and not shape_errors
            and actual_sha256 == reference.sha256
            and leaf.get("input_fingerprint") == reference.input_fingerprint
            and leaf.get("status") == reference.status
            and reference.status == "pass"
            and leaf.get("applicable") is True
            and leaf.get("complete") is True
            and not leaf.get("errors")
            and reference.asset_id in checked
            and style_tokens_ok
        )
        if leaf is not None and actual_sha256 != reference.sha256:
            block(f"asset {reference.asset_id}: validation report sha256 mismatch")
        if leaf is not None and leaf.get("input_fingerprint") != reference.input_fingerprint:
            block(f"asset {reference.asset_id}: stale input_fingerprint")
        if leaf is not None and leaf.get("status") != reference.status:
            block(f"asset {reference.asset_id}: validation report status mismatch")
        if leaf is not None and reference.asset_id not in checked:
            block(f"asset {reference.asset_id}: validation report did not check asset")
        if leaf is not None:
            leaf_status = leaf.get("status")
            if leaf_status == "operational-error":
                block(
                    f"asset {reference.asset_id} ({reference.asset_kind}): validation reported operational-error",
                    "operational-error",
                )
            elif leaf_status == "blocked":
                block(
                    f"asset {reference.asset_id} ({reference.asset_kind}): validation reported blocked",
                    "blocked",
                )
            elif leaf_status == "fail":
                block(
                    f"asset {reference.asset_id} ({reference.asset_kind}): validation reported fail"
                )
            elif leaf_status == "skipped":
                block(
                    f"asset {reference.asset_id}: skipped validation cannot satisfy inventory"
                )
            elif leaf_status != "pass":
                block(f"asset {reference.asset_id}: validation report has unknown status")
            if leaf.get("complete") is not True and leaf_status not in {
                "fail",
                "skipped",
                "operational-error",
            }:
                block(
                    f"asset {reference.asset_id}: validation is incomplete",
                    "blocked",
                )
            if leaf_status == "pass" and leaf.get("applicable") is not True:
                block(
                    f"asset {reference.asset_id}: passing validation must be applicable"
                )
            if reference.status != "pass" and leaf_status == "pass":
                block(
                    f"asset {reference.asset_id}: expected status must be pass for aggregate approval"
                )
        leaf_results.append(
            {
                "asset_id": reference.asset_id,
                "asset_kind": reference.asset_kind,
                "path": reference.path,
                "expected_sha256": reference.sha256,
                "actual_sha256": actual_sha256,
                "expected_input_fingerprint": reference.input_fingerprint,
                "actual_input_fingerprint": leaf.get("input_fingerprint") if leaf else None,
                "expected_status": reference.status,
                "actual_status": leaf.get("status") if leaf else None,
                "applicable": leaf.get("applicable") if leaf else None,
                "complete": leaf.get("complete") if leaf else None,
                "checked_items": checked if isinstance(checked, list) else [],
                "validation_errors": shape_errors,
                "style_tokens_verified": style_tokens_ok,
                "verified": verified,
            }
        )

    counts = Counter(checked_assets)
    inventory_ids = sorted(asset["id"] for asset in document["inventory"]["assets"])
    for asset_id in inventory_ids:
        if counts[asset_id] != 1:
            block(
                f"asset {asset_id}: expected exactly one leaf validation, found {counts[asset_id]}"
            )

    blockers = sorted(dict.fromkeys(blockers))
    if "operational-error" in outcomes:
        status, exit_code, complete = "operational-error", 3, False
    elif "fail" in outcomes:
        status, exit_code, complete = "fail", 1, True
    elif "blocked" in outcomes:
        status, exit_code, complete = "blocked", 2, False
    else:
        status, exit_code, complete = "pass", 0, True
    fingerprint_payload = {
        "pack_id": document["pack_id"],
        "deliverables": deliverable_results,
        "leaf_reports": leaf_results,
    }
    input_fingerprint = _sha256(
        json.dumps(
            fingerprint_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    report = {
        "version": 1,
        "kind": "asset-pack-validation-report",
        "pack_id": document["pack_id"],
        "pack_root": pack_root,
        "ok": status == "pass",
        "status": status,
        "complete": complete,
        "exit_code": exit_code,
        "input_fingerprint": input_fingerprint,
        "checked_assets": inventory_ids if not blockers else sorted(set(checked_assets)),
        "deliverables": deliverable_results,
        "leaf_reports": leaf_results,
        "blockers": blockers,
    }
    return report, exit_code


def validate_asset_pack_root(
    document: Mapping[str, Any], pack_root: Path
) -> tuple[dict[str, Any], int]:
    """Resolve and read every declared artifact below ``pack_root``."""

    validate_asset_pack(document)
    root = Path(pack_root).expanduser().resolve()
    paths = {
        item["path"] for item in document["delivery_manifest"]["deliverables"]
    }
    paths.update(
        asset["validation_report"]["path"]
        for asset in document["inventory"]["assets"]
    )
    artifacts: dict[str, bytes] = {}
    errors: dict[str, str] = {}
    for relative_path in sorted(paths):
        try:
            target = resolve_pack_path(root, relative_path)
        except AssetPackPathError as exc:
            errors[relative_path] = str(exc)
            continue
        try:
            artifacts[relative_path] = target.read_bytes()
        except FileNotFoundError:
            continue
        except OSError as exc:
            errors[relative_path] = str(exc)
    return aggregate_asset_pack(
        document,
        artifacts,
        artifact_errors=errors,
        pack_root=str(root),
    )


__all__ = ["aggregate_asset_pack", "validate_asset_pack_root"]
