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


def _source_record_error(
    run_root: Path, record: Any, label: str, *, allow_external: bool = False
) -> str | None:
    if not isinstance(record, Mapping) or not isinstance(record.get("path"), str):
        return f"video source report has no valid {label} record"
    try:
        candidate = Path(record["path"]).expanduser()
        if candidate.is_absolute():
            path = candidate.resolve()
            if not allow_external:
                path = resolve_run_path(run_root, path.relative_to(run_root))
        else:
            path = resolve_run_path(run_root, candidate)
        if not path.is_file():
            return f"video source {label} is missing: {record['path']}"
        if _file_sha256(path) != record.get("sha256") or path.stat().st_size != record.get("size_bytes"):
            return f"video source {label} bytes changed: {record['path']}"
    except (OSError, ValueError) as exc:
        return f"video source {label} is unreadable or unsafe: {exc}"
    return None


def _validate_video_selector(
    run_root: Path,
    *,
    source_entry: Mapping[str, Any],
    source_index: int,
    source_type: str,
) -> tuple[list[str], dict[str, Any] | None]:
    requires_grok_video = source_entry.get("source_type", source_type) == "grok-imagine-video"
    upstream = source_entry.get("upstream_report")
    if not isinstance(upstream, str):
        if requires_grok_video:
            return [f"accepted_sources[{source_index}] requires a Grok video source report"], None
        return [], None
    try:
        report_path = resolve_run_path(run_root, upstream)
    except PathSafetyError as exc:
        return [f"accepted_sources[{source_index}].upstream_report is unsafe: {exc}"], None
    if not report_path.is_file():
        return [f"video source report does not exist: {upstream}"], None
    try:
        report_bytes = report_path.read_bytes()
        report = json.loads(report_bytes.decode("utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        return [f"video source report is unreadable: {upstream}: {exc}"], None
    if not isinstance(report, Mapping):
        return [f"upstream source report must be a JSON object: {upstream}"], None
    kind = report.get("kind")
    # Generic non-video receipts may omit kind; Grok video must still match below.
    if kind is not None and not isinstance(kind, str):
        return [f"upstream source report kind must be a string: {upstream}"], None
    if kind not in {"sprite-video-source", "sprite-grok-video-source"}:
        if requires_grok_video:
            return [f"accepted_sources[{source_index}] requires a Grok video source report"], None
        return [], None
    states = source_entry.get("states")
    state = report.get("state")
    errors: list[str] = []
    if report.get("status") != "pass":
        errors.append(f"video source report does not pass: {upstream}")
    if requires_grok_video and kind != "sprite-grok-video-source":
        errors.append(f"Grok video provenance has a mismatched source report: {upstream}")
    if not isinstance(states, (list, tuple)) or state not in states:
        errors.append(f"video source report state does not match accepted source: {upstream}")
        return errors, None
    for label in ("sprite_request", "video", "first_frame"):
        record = report.get(label)
        if label == "first_frame" and record is None and report.get("exact_first_frame_preserved") is False:
            continue
        issue = _source_record_error(
            run_root, record, label,
            allow_external=label == "video" and kind == "sprite-grok-video-source",
        )
        if issue:
            errors.append(issue)
    request_record = report.get("sprite_request")
    if isinstance(request_record, Mapping) and request_record.get("path") != "sprite-request.json":
        errors.append(f"video source report does not bind sprite-request.json: {upstream}")
    indices = report.get("sampled_video_indices")
    if not isinstance(indices, list) or not indices or any(
        type(index) is not int or index < 0 for index in indices
    ):
        return [f"video source report has invalid sampled_video_indices: {upstream}"], None
    output = report.get("output")
    if not isinstance(output, Mapping):
        errors.append(f"video source report has no output record: {upstream}")
    elif (
        output.get("path") != source_entry.get("path")
        or output.get("sha256") != source_entry.get("sha256")
    ):
        errors.append(f"video source report output does not match accepted source: {upstream}")
    selector_relative = f"qa/{state}-video-frame-selector/selector.evidence.json"
    try:
        selector_path = resolve_run_path(run_root, selector_relative)
    except PathSafetyError as exc:
        return [*errors, f"video frame selector path is unsafe: {exc}"], None
    if not selector_path.is_file():
        errors.append(f"required video frame selector is missing: {selector_relative}")
        return errors, None
    try:
        selector = json.loads(selector_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        errors.append(f"video frame selector evidence is unreadable: {selector_relative}: {exc}")
        return errors, None
    if not isinstance(selector, Mapping):
        errors.append(f"video frame selector evidence must be a JSON object: {selector_relative}")
        return errors, None
    expected_report_hash = sha256(report_bytes).hexdigest()
    if (
        selector.get("kind") != "sprite-video-frame-selector-evidence"
        or selector.get("status") != "pass"
        or selector.get("state") != state
    ):
        errors.append(f"video frame selector evidence is invalid: {selector_relative}")
    source_report = selector.get("source_report")
    if not isinstance(source_report, Mapping) or (
        source_report.get("sha256") != expected_report_hash or source_report.get("path") != upstream
    ):
        errors.append(f"video frame selector is stale for source report: {upstream}")
    video = report.get("video")
    if not isinstance(video, Mapping) or selector.get("video") != {
        "path": video.get("path"), "sha256": video.get("sha256")
    }:
        errors.append(f"video frame selector video record is stale: {upstream}")
    if selector.get("selected_indices") != indices:
        errors.append(f"video frame selector selection is stale for state {state}")
    candidate_count = selector.get("candidate_count")
    decoded = report.get("decoded")
    decoded_count = decoded.get("frame_count") if isinstance(decoded, Mapping) else None
    requested_count = len(indices)
    minimum_candidates = 2 if isinstance(decoded_count, int) and decoded_count > requested_count else 1
    if type(candidate_count) is not int or candidate_count < minimum_candidates:
        errors.append(f"video frame selector needs at least {minimum_candidates} candidate cycles for state {state}")
    html_record = selector.get("html")
    if isinstance(html_record, Mapping) and isinstance(html_record.get("path"), str):
        try:
            html_path = resolve_run_path(run_root, html_record["path"])
        except PathSafetyError as exc:
            errors.append(f"video frame selector HTML path is unsafe: {exc}")
        else:
            if not html_path.is_file() or _file_sha256(html_path) != html_record.get("sha256"):
                errors.append(f"video frame selector HTML is missing or changed: {html_record['path']}")
    else:
        errors.append(f"video frame selector evidence has no HTML record: {selector_relative}")
    return errors, {
        "state": state,
        "source_report": upstream,
        "selector": selector_relative,
        "candidate_count": candidate_count,
        "selected_indices": selector.get("selected_indices"),
    }


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
    video_selectors: list[dict[str, Any]] = []
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
        selector_errors, selector_evidence = _validate_video_selector(
            run_root,
            source_entry=entry,
            source_index=index,
            source_type=source_type,
        )
        errors.extend(selector_errors)
        if selector_evidence is not None:
            video_selectors.append(selector_evidence)

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
            "video_selectors": video_selectors,
        },
        input_fingerprint=fingerprint,
        complete=True,
        status=CheckStatus.FAIL if errors else CheckStatus.PASS,
    )


__all__ = ["validate_provenance"]
