"""Exact, hash-bound provenance validation for accepted sprite sources."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping

from spritecore.contracts import ContractError, load_provenance, load_sprite_request
from spritecore.paths import PathSafetyError, resolve_run_path
from spritecore.results import CheckResult, CheckStatus


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fingerprint(*documents: Mapping[str, Any]) -> str:
    payload = json.dumps(
        [dict(document) for document in documents],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def validate_provenance(
    run_dir: Path,
    *,
    allow_imported: bool = False,
    allow_fixture: bool = False,
) -> CheckResult:
    """Validate provenance against the request and current source bytes.

    This callable never writes. The CLI wrapper owns report persistence so the
    same result can be composed by the aggregate validator without side effects.
    """

    run_root = Path(run_dir).expanduser().resolve()
    errors: list[str] = []
    warnings: list[str] = []
    evidence_sources: list[dict[str, Any]] = []
    expected_states: tuple[str, ...] = ()

    try:
        request = load_sprite_request(run_root / "sprite-request.json")
        expected_states = tuple(sorted(request.data["states"]))
    except ContractError as exc:
        return CheckResult(
            id="generation-provenance",
            applicable=True,
            errors=(f"sprite request is missing or invalid: {exc}",),
            complete=True,
            status=CheckStatus.FAIL,
        )

    try:
        provenance = load_provenance(run_root / "source-provenance.json")
    except ContractError as exc:
        return CheckResult(
            id="generation-provenance",
            applicable=True,
            checked_items=expected_states,
            errors=(f"source provenance is missing or invalid: {exc}",),
            complete=True,
            status=CheckStatus.FAIL,
        )

    data = provenance.data
    source_type = data["source_type"]
    request_source_type = request.data.get("source_type")
    if request_source_type is not None and request_source_type != source_type:
        errors.append(
            "source_type mismatch: request declares "
            f"{request_source_type!r}, provenance declares {source_type!r}"
        )
    if data["verification_status"] != "verified":
        errors.append("legacy-unverified provenance cannot satisfy production QA")
    if source_type == "fixture" and not allow_fixture:
        errors.append("fixture provenance requires explicit allow_fixture policy")
    if source_type == "imported" and not allow_imported:
        errors.append("imported provenance requires explicit allow_imported policy")

    expected = set(expected_states)
    declared_coverage = set(data["state_coverage"])
    missing = sorted(expected - declared_coverage)
    unknown = sorted(declared_coverage - expected)
    if missing:
        errors.append(f"state coverage is missing expected states: {', '.join(missing)}")
    if unknown:
        errors.append(f"state coverage contains unknown states: {', '.join(unknown)}")

    for index, entry in enumerate(data["accepted_sources"]):
        relative_path = entry["path"]
        try:
            source_path = resolve_run_path(run_root, relative_path)
        except PathSafetyError as exc:
            errors.append(f"accepted_sources[{index}].path is unsafe: {exc}")
            continue
        if not source_path.is_file():
            errors.append(f"accepted source does not exist as a file: {relative_path}")
            continue
        try:
            actual_size = source_path.stat().st_size
            actual_hash = _file_sha256(source_path)
        except OSError as exc:
            errors.append(f"accepted source could not be read: {relative_path}: {exc}")
            continue
        if entry["size_bytes"] != actual_size:
            errors.append(
                f"accepted source size changed for {relative_path}: "
                f"expected {entry['size_bytes']}, got {actual_size}"
            )
        if entry["sha256"] != actual_hash:
            errors.append(f"accepted source sha256 changed for {relative_path}")
        evidence_sources.append(
            {
                "path": str(source_path),
                "sha256": actual_hash,
                "size_bytes": actual_size,
                "states": list(entry["states"]),
            }
        )

    fingerprint = _fingerprint(request.to_dict(), provenance.to_dict())
    return CheckResult(
        id="generation-provenance",
        applicable=True,
        checked_items=expected_states,
        errors=errors,
        warnings=warnings,
        evidence={
            "provenance": str((run_root / "source-provenance.json").resolve()),
            "source_type": source_type,
            "sources": evidence_sources,
        },
        input_fingerprint=fingerprint,
        complete=True,
        status=CheckStatus.FAIL if errors else CheckStatus.PASS,
    )


__all__ = ["validate_provenance"]
