"""Read-only validation for hash-bound source row intake.

This module deliberately performs no writes.  It validates the complete intake
contract and returns an immutable execution plan; the public CLI owns locking
and atomic mutation only after this boundary succeeds.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator
from PIL import Image, UnidentifiedImageError

from spritecore.contracts import ContractError, load_provenance, load_sprite_request
from spritecore.paths import (
    RUN_MARKER_FILENAME,
    RUN_MARKER_KIND,
    RUN_MARKER_VERSION,
    PathSafetyError,
    resolve_run_path,
)


_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "references"
    / "schemas"
    / "source-intake-v1.schema.json"
)
_TYPE_BINDINGS = {
    "imagegen": ("imagegen", "provider-output", {"generated"}),
    "grok-imagine-image": ("grok-imagine", "provider-output", {"generated"}),
    "imported": ("imported", "user-import", {"user-owned", "licensed"}),
    "fixture": ("fixture", "fixture", {"fixture"}),
}
_IMAGE_MIMES = {
    "PNG": "image/png",
    "WEBP": "image/webp",
    "JPEG": "image/jpeg",
}


class SourceIntakeError(ValueError):
    """The intake cannot safely authorize a raw-row mutation."""

    def __init__(self, issues: list[str] | tuple[str, ...]):
        self.issues = tuple(dict.fromkeys(str(issue) for issue in issues if issue))
        super().__init__("invalid source intake: " + "; ".join(self.issues))


@dataclass(frozen=True, slots=True)
class SourceIntakePlan:
    """Fully validated inputs needed by the mutating CLI boundary."""

    run_dir: Path
    job_id: str
    state: str
    source_type: str
    engine: str
    license_ref: str
    license_status: str
    candidate_path: Path
    output_path: Path
    provenance_path: Path
    report_path: Path
    candidate_sha256: str
    candidate_mime: str
    width: int
    height: int
    request: Mapping[str, Any]
    intake: Mapping[str, Any]
    existing_provenance: Mapping[str, Any] | None


def file_sha256(path: Path) -> str:
    """Return the lowercase SHA-256 of the current file bytes."""

    digest = sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def document_fingerprint(document: Mapping[str, Any]) -> str:
    """Fingerprint JSON semantics rather than incidental file whitespace."""

    payload = json.dumps(
        dict(document),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def load_source_intake(source: str | Path | Mapping[str, Any]) -> dict[str, Any]:
    """Load one intake JSON object without validating or mutating its run."""

    if isinstance(source, Mapping):
        payload: Any = dict(source)
    else:
        try:
            payload = json.loads(
                Path(source).expanduser().resolve().read_text(encoding="utf-8-sig")
            )
        except (OSError, UnicodeError, ValueError) as exc:
            raise SourceIntakeError([f"intake JSON could not be loaded: {exc}"]) from exc
    if not isinstance(payload, dict):
        raise SourceIntakeError(["intake JSON root must be an object"])
    return payload


def _schema_issues(payload: Mapping[str, Any]) -> list[str]:
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    issues: list[str] = []
    for error in sorted(
        validator.iter_errors(dict(payload)), key=lambda item: list(item.absolute_path)
    ):
        location = ".".join(str(part) for part in error.absolute_path)
        issues.append(f"{location}: {error.message}" if location else error.message)
    return issues


def _owned_run_issues(run_root: Path) -> list[str]:
    marker = run_root / RUN_MARKER_FILENAME
    is_junction = getattr(marker, "is_junction", lambda: False)()
    if marker.is_symlink() or is_junction or not marker.is_file():
        return [f"run is unowned: missing or unsafe {RUN_MARKER_FILENAME}"]
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        return [f"run marker is unreadable: {exc}"]
    if not isinstance(payload, dict):
        return ["run marker must be a JSON object"]
    issues: list[str] = []
    if payload.get("version") != RUN_MARKER_VERSION:
        issues.append("run marker version is unsupported")
    if payload.get("kind") != RUN_MARKER_KIND:
        issues.append("run marker kind is invalid")
    if not isinstance(payload.get("run_id"), str) or not payload["run_id"].strip():
        issues.append("run marker id is missing")
    return issues


def _resolve_binding(
    run_root: Path,
    name: str,
    binding: Mapping[str, Any],
    issues: list[str],
) -> Path | None:
    try:
        path = resolve_run_path(run_root, str(binding.get("path", "")))
    except PathSafetyError as exc:
        issues.append(f"{name}.path is unsafe: {exc}")
        return None
    if not path.is_file():
        issues.append(f"{name} file is missing: {binding.get('path')}")
        return None
    try:
        actual_hash = file_sha256(path)
    except OSError as exc:
        issues.append(f"{name} file could not be read: {exc}")
        return None
    if binding.get("sha256") != actual_hash:
        issues.append(f"{name} sha256 is stale")
    return path


def _request_binding(
    request: Mapping[str, Any], name: str
) -> tuple[str, str | None] | None:
    declared = request.get(name)
    if isinstance(declared, str) and declared:
        return declared, None
    if isinstance(declared, Mapping):
        path = declared.get("path")
        digest = declared.get("sha256")
        if isinstance(path, str) and path:
            return path, digest if isinstance(digest, str) else None
    if name == "identity_anchor":
        character = request.get("character")
        if isinstance(character, Mapping):
            base_image = character.get("base_image")
            if isinstance(base_image, str) and base_image:
                return base_image, None
    return None


def _validate_existing_provenance(
    run_root: Path,
    request: Mapping[str, Any],
    state: str,
    source_type: str,
    license_ref: str,
    issues: list[str],
) -> dict[str, Any] | None:
    try:
        path = resolve_run_path(run_root, "source-provenance.json")
    except PathSafetyError as exc:
        issues.append(f"source-provenance.json path is unsafe: {exc}")
        return None
    if not path.exists():
        return None
    try:
        provenance = load_provenance(path).to_dict()
    except ContractError as exc:
        issues.append(f"existing source provenance is invalid: {exc}")
        return None
    if provenance.get("verification_status") != "verified":
        issues.append("existing source provenance is not verified")
    # A run may deliberately combine providers per state. The writer promotes
    # the root provenance to ``mixed`` and keeps the concrete source type on
    # each accepted source entry. License validity is still checked against
    # the current request before this existing-provenance validation.
    expected_states = set(request.get("states", {}))
    coverage = set(provenance.get("state_coverage", []))
    unknown = sorted(coverage - expected_states)
    if unknown:
        issues.append(
            "existing source provenance covers unknown states: " + ", ".join(unknown)
        )
    for index, entry in enumerate(provenance.get("accepted_sources", [])):
        entry_states = entry.get("states", [])
        if state in entry_states and (
            entry_states != [state] or entry.get("path") != f"raw/{state}.png"
        ):
            issues.append(
                f"existing provenance for {state!r} is not a replaceable single-state raw row"
            )
        try:
            source = resolve_run_path(run_root, entry.get("path", ""))
        except PathSafetyError as exc:
            issues.append(
                f"existing accepted_sources[{index}].path is unsafe: {exc}"
            )
            continue
        if not source.is_file():
            issues.append(
                f"existing accepted source is missing: {entry.get('path')}"
            )
            continue
        try:
            actual_hash = file_sha256(source)
            actual_size = source.stat().st_size
        except OSError as exc:
            issues.append(f"existing accepted source could not be read: {exc}")
            continue
        if entry.get("sha256") != actual_hash:
            issues.append(
                f"existing accepted source sha256 is stale: {entry.get('path')}"
            )
        if entry.get("size_bytes") != actual_size:
            issues.append(
                f"existing accepted source size is stale: {entry.get('path')}"
            )
    return provenance


def validate_source_intake(
    payload: Mapping[str, Any], *, run_dir: Path, force: bool = False
) -> SourceIntakePlan:
    """Validate all intake inputs and return a no-write execution plan."""

    intake = dict(payload)
    issues = _schema_issues(intake)
    run_root = Path(run_dir).expanduser().resolve()
    issues.extend(_owned_run_issues(run_root))
    if issues:
        raise SourceIntakeError(issues)

    job_id = str(intake["job_id"])
    state = str(intake["expected"]["state"])
    source_type = str(intake["source_type"])
    engine = str(intake["engine"])
    source_stage = str(intake["source_stage"])
    license_ref = str(intake["license_ref"])
    license_status = str(intake["license_status"])
    candidate = intake["candidate"]
    provider = intake["provider"]

    if intake["status"] != "selected":
        issues.append(f"intake status is not selected: {intake['status']}")
    if provider["status"] != "succeeded":
        issues.append(f"provider status is not succeeded: {provider['status']}")
    if provider.get("job_id") not in (None, job_id):
        issues.append("provider.job_id does not match job_id")
    if intake["expected"]["artifact_kind"] != "raw-row":
        issues.append("expected.artifact_kind must be raw-row")
    if candidate["role"] != "selected":
        issues.append(
            f"candidate role {candidate['role']!r} cannot be ingested as a raw row"
        )
    expected_engine, expected_stage, allowed_licenses = _TYPE_BINDINGS[source_type]
    if engine != expected_engine:
        issues.append(
            f"engine {engine!r} does not match source_type {source_type!r}"
        )
    if source_stage != expected_stage:
        issues.append(
            f"source_stage {source_stage!r} does not match source_type {source_type!r}"
        )
    if license_status not in allowed_licenses:
        issues.append(
            f"license_status {license_status!r} is not valid for {source_type!r}"
        )

    try:
        request_path = resolve_run_path(run_root, intake["request"]["path"])
    except PathSafetyError as exc:
        issues.append(f"sprite-request path is unsafe: {exc}")
        request_path = run_root / ".invalid-source-intake-request"
    try:
        request_document = load_sprite_request(request_path)
        request = request_document.to_dict()
    except ContractError as exc:
        issues.append(f"sprite request is missing or invalid: {exc}")
        request = {}
    if request and intake["request"]["fingerprint"] != document_fingerprint(request):
        issues.append("sprite-request fingerprint is stale")

    states = request.get("states", {}) if isinstance(request, Mapping) else {}
    entry = states.get(state) if isinstance(states, Mapping) else None
    if not isinstance(entry, Mapping):
        issues.append(f"expected state {state!r} is not in the current sprite request")

    licenses = request.get("licenses", []) if isinstance(request, Mapping) else []
    license_ids = [
        item.get("id")
        for item in licenses
        if isinstance(item, Mapping) and isinstance(item.get("id"), str)
    ]
    if len(license_ids) != len(set(license_ids)):
        issues.append("sprite request contains duplicate license ids")
    license_entries = {
        item.get("id"): item
        for item in licenses
        if isinstance(item, Mapping) and isinstance(item.get("id"), str)
    }
    license_entry = license_entries.get(license_ref)
    if not isinstance(license_entry, Mapping):
        issues.append(f"unknown license_ref {license_ref!r}")
    elif license_entry.get("status") != license_status:
        issues.append(
            f"license_status does not match license {license_ref!r} in sprite request"
        )

    for binding_name in ("style_reference", "identity_anchor"):
        intake_binding = intake.get(binding_name)
        declared = _request_binding(request, binding_name)
        if declared is not None and not isinstance(intake_binding, Mapping):
            issues.append(f"{binding_name} binding is required by sprite request")
            continue
        if isinstance(intake_binding, Mapping):
            _resolve_binding(run_root, binding_name, intake_binding, issues)
            if declared is not None:
                expected_path, expected_hash = declared
                if intake_binding.get("path") != expected_path:
                    issues.append(f"{binding_name}.path does not match sprite request")
                if expected_hash is not None and intake_binding.get("sha256") != expected_hash:
                    issues.append(f"{binding_name}.sha256 does not match sprite request")

    try:
        candidate_path = resolve_run_path(run_root, candidate["path"])
    except PathSafetyError as exc:
        issues.append(f"candidate.path is unsafe: {exc}")
        candidate_path = run_root / ".invalid-source-intake-candidate"
    try:
        output_path = resolve_run_path(run_root, f"raw/{state}.png")
    except PathSafetyError as exc:
        issues.append(f"raw output path is unsafe: {exc}")
        output_path = run_root / ".invalid-source-intake-output"
    try:
        provenance_path = resolve_run_path(run_root, "source-provenance.json")
    except PathSafetyError as exc:
        issues.append(f"source provenance output path is unsafe: {exc}")
        provenance_path = run_root / ".invalid-source-intake-provenance"
    try:
        report_path = resolve_run_path(run_root, "qa/source-intake-report.json")
    except PathSafetyError as exc:
        issues.append(f"source intake report path is unsafe: {exc}")
        report_path = run_root / ".invalid-source-intake-report"
    if candidate_path == output_path:
        issues.append("candidate.path must be a staging input, not the raw output path")
    if output_path.exists() and not force:
        issues.append(
            f"raw output already exists for {state!r}; pass --force to reingest"
        )

    actual_mime: str | None = None
    actual_width: int | None = None
    actual_height: int | None = None
    if not candidate_path.is_file():
        issues.append(f"selected provider output is missing: {candidate['path']}")
    else:
        try:
            actual_hash = file_sha256(candidate_path)
        except OSError as exc:
            issues.append(f"selected provider output could not be read: {exc}")
            actual_hash = None
        if actual_hash is not None and candidate["sha256"] != actual_hash:
            issues.append("candidate sha256 does not match current file bytes")
        try:
            with Image.open(candidate_path) as image:
                actual_width, actual_height = image.size
                actual_mime = _IMAGE_MIMES.get(str(image.format).upper())
                image.verify()
        except (OSError, ValueError, UnidentifiedImageError) as exc:
            issues.append(f"candidate is not a readable supported bitmap: {exc}")
        if actual_mime is None:
            issues.append("candidate bitmap format is not PNG, WebP, or JPEG")
        else:
            if candidate["mime"] not in _IMAGE_MIMES.values():
                issues.append(f"candidate MIME is unsupported: {candidate['mime']}")
            elif candidate["mime"] != actual_mime:
                issues.append(
                    f"candidate MIME does not match bitmap bytes: expected {actual_mime}"
                )
        if (
            actual_width is not None
            and actual_height is not None
            and (candidate["width"], candidate["height"])
            != (actual_width, actual_height)
        ):
            issues.append(
                "candidate dimensions do not match bitmap bytes: "
                f"declared {candidate['width']}x{candidate['height']}, "
                f"actual {actual_width}x{actual_height}"
            )

    if isinstance(entry, Mapping):
        layout = entry.get("raw_layout")
        columns = (
            int(layout.get("columns", 0))
            if isinstance(layout, Mapping)
            else int(entry.get("frames", 0))
        )
        rows = int(layout.get("rows", 0)) if isinstance(layout, Mapping) else 1
        if columns <= 0 or rows <= 0:
            issues.append(f"raw_layout for {state!r} must declare positive columns and rows")
        elif candidate["width"] < columns or candidate["height"] < rows:
            issues.append(
                f"candidate resolution is too small for raw_layout {columns}x{rows} "
                f"for {state!r}; every source slot must contain at least one pixel"
            )

    existing_provenance = _validate_existing_provenance(
        run_root, request, state, source_type, license_ref, issues
    )
    if issues:
        raise SourceIntakeError(issues)
    assert actual_mime is not None
    assert actual_width is not None and actual_height is not None
    return SourceIntakePlan(
        run_dir=run_root,
        job_id=job_id,
        state=state,
        source_type=source_type,
        engine=engine,
        license_ref=license_ref,
        license_status=license_status,
        candidate_path=candidate_path,
        output_path=output_path,
        provenance_path=provenance_path,
        report_path=report_path,
        candidate_sha256=str(candidate["sha256"]),
        candidate_mime=actual_mime,
        width=actual_width,
        height=actual_height,
        request=request,
        intake=intake,
        existing_provenance=existing_provenance,
    )


__all__ = [
    "SourceIntakeError",
    "SourceIntakePlan",
    "document_fingerprint",
    "file_sha256",
    "load_source_intake",
    "validate_source_intake",
]
