#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Fail closed when an animation batch is incomplete, stale, or over-counted."""

from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

from runio import atomic_write_text
from spritecore.provenance import validate_provenance


class BatchCompletionError(ValueError):
    """Raised when the batch contract itself cannot be audited."""


def _load_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise BatchCompletionError(f"{label} is missing: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BatchCompletionError(f"{label} is unreadable: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise BatchCompletionError(f"{label} must be a JSON object: {path}")
    return payload


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_under(root: Path, value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise BatchCompletionError(f"{label} must be a non-empty path string")
    path = Path(value).expanduser()
    resolved = path.resolve() if path.is_absolute() else (root / path).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise BatchCompletionError(f"{label} must stay inside repo root: {value}") from exc
    return resolved


def _resolve_media(run_dir: Path, value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise BatchCompletionError(f"{label} must be a non-empty path string")
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (run_dir / path).resolve()


def _check_file_record(
    *,
    path: Path,
    record: Mapping[str, Any],
    label: str,
    errors: list[str],
) -> str | None:
    if not path.is_file():
        errors.append(f"{label} is missing: {path}")
        return None
    actual_size = path.stat().st_size
    expected_size = record.get("size_bytes")
    if isinstance(expected_size, int) and actual_size != expected_size:
        errors.append(
            f"{label} size drift: expected {expected_size}, found {actual_size}: {path}"
        )
    expected_hash = record.get("sha256")
    actual_hash = _sha256(path)
    if not isinstance(expected_hash, str) or actual_hash != expected_hash:
        errors.append(f"{label} SHA-256 drift: {path}")
    return actual_hash


def _identity(entry: Mapping[str, Any], fields: Sequence[str]) -> str:
    direct = entry.get("id") or entry.get("identity")
    if isinstance(direct, str) and direct:
        return direct
    parts: list[str] = []
    for field in fields:
        value = entry.get(field)
        if not isinstance(value, str) or not value:
            raise BatchCompletionError(
                f"entry is missing identity field {field!r}; add id or configure identity_fields"
            )
        parts.append(value)
    return "/".join(parts)


def _states_for_batch(
    manifest: Mapping[str, Any], override: str | None
) -> list[str]:
    if override is not None:
        states = [item.strip() for item in override.split(",") if item.strip()]
    else:
        policy = manifest.get("generation_policy")
        raw = policy.get("states_per_identity") if isinstance(policy, Mapping) else None
        states = list(raw) if isinstance(raw, list) else []
    if not states or any(not isinstance(state, str) or not state for state in states):
        raise BatchCompletionError(
            "required states are missing; set generation_policy.states_per_identity or --states"
        )
    if len(states) != len(set(states)):
        raise BatchCompletionError("required states must be unique")
    return states


def _identity_fields(
    manifest: Mapping[str, Any], override: str | None
) -> list[str]:
    if override:
        fields = [item.strip() for item in override.split(",") if item.strip()]
    else:
        policy = manifest.get("generation_policy")
        raw = policy.get("identity_fields") if isinstance(policy, Mapping) else None
        fields = list(raw) if isinstance(raw, list) else ["biome", "enemy"]
    if not fields or any(not isinstance(field, str) or not field for field in fields):
        raise BatchCompletionError("identity_fields must contain non-empty strings")
    return fields


def _completed_repair_states(run_dir: Path, errors: list[str]) -> dict[str, str | None]:
    plan_path = run_dir / "qa" / "quota-sealed-repair-plan.json"
    if not plan_path.is_file():
        return {}
    try:
        plan = _load_json(plan_path, "quota-sealed repair plan")
    except BatchCompletionError as exc:
        errors.append(str(exc))
        return {}
    if plan.get("status") != "completed":
        errors.append(f"quota-sealed repair plan is not completed: {plan_path}")
        return {}
    completed: dict[str, str | None] = {}
    repairs = plan.get("repairs")
    if isinstance(repairs, list):
        for repair in repairs:
            if not isinstance(repair, Mapping) or repair.get("status") != "completed":
                continue
            state = repair.get("state")
            if isinstance(state, str) and state:
                result = repair.get("result")
                completed[state] = result if isinstance(result, str) else None
    else:
        state = plan.get("state")
        if isinstance(state, str) and state:
            result = plan.get("result")
            completed[state] = result if isinstance(result, str) else None
    if not completed:
        errors.append(f"quota-sealed repair plan has no completed states: {plan_path}")
    return completed


def _explicit_quota_source(entry: Mapping[str, Any], state: str) -> str | None:
    for owner in (entry, entry.get("review")):
        if not isinstance(owner, Mapping):
            continue
        sources = owner.get("quota_sources")
        if not isinstance(sources, Mapping):
            continue
        value = sources.get(state)
        if isinstance(value, str):
            return value
        if isinstance(value, Mapping) and isinstance(value.get("path"), str):
            return str(value["path"])
    return None


def _quota_report_for_state(
    run_dir: Path,
    entry: Mapping[str, Any],
    state: str,
    all_reports: Sequence[Path],
    errors: list[str],
) -> tuple[Path | None, str]:
    explicit = _explicit_quota_source(entry, state)
    if explicit is not None:
        try:
            path = _resolve_media(run_dir, explicit, f"quota source for {state}")
        except BatchCompletionError as exc:
            errors.append(str(exc))
            return None, "explicit"
        return path, "explicit"

    preferred = [
        run_dir / "provider" / "grok-imagine" / state / "video-source.json",
        run_dir / "provider" / "video" / state / "video-source.json",
    ]
    for candidate in preferred:
        if candidate.is_file():
            return candidate, "canonical-provider-path"

    matches: list[Path] = []
    for candidate in all_reports:
        try:
            report = _load_json(candidate, "video source report")
        except BatchCompletionError:
            continue
        if report.get("state") == state:
            matches.append(candidate)
    if len(matches) == 1:
        return matches[0], "single-report-fallback"
    if not matches:
        errors.append(f"no quota video source report found for state {state!r}")
    else:
        errors.append(
            f"multiple non-canonical video reports found for state {state!r}; "
            "declare review.quota_sources explicitly"
        )
    return None, "unresolved"


def _audit_selector(
    *,
    run_dir: Path,
    state: str,
    report_path: Path,
    report: Mapping[str, Any],
    errors: list[str],
) -> list[int]:
    selector_path = (
        run_dir / "qa" / f"{state}-video-frame-selector" / "selector.evidence.json"
    )
    try:
        selector = _load_json(selector_path, f"selector evidence for {state}")
    except BatchCompletionError as exc:
        errors.append(str(exc))
        return []
    if selector.get("kind") != "sprite-video-frame-selector-evidence":
        errors.append(f"selector evidence kind is invalid for {state}: {selector_path}")
    if selector.get("status") != "pass" or selector.get("state") != state:
        errors.append(f"selector evidence is not a passing {state!r} review: {selector_path}")

    source_record = selector.get("source_report")
    if not isinstance(source_record, Mapping) or source_record.get("sha256") != _sha256(
        report_path
    ):
        errors.append(f"selector source report hash drift for {state}: {selector_path}")
    video_record = selector.get("video")
    report_video = report.get("video")
    if not isinstance(video_record, Mapping) or not isinstance(report_video, Mapping):
        errors.append(f"selector video record is missing for {state}: {selector_path}")
    elif video_record.get("sha256") != report_video.get("sha256"):
        errors.append(f"selector video hash does not match quota video for {state}")

    indices = selector.get("selected_indices")
    if (
        not isinstance(indices, list)
        or not indices
        or any(not isinstance(index, int) or index < 0 for index in indices)
        or indices != sorted(set(indices))
    ):
        errors.append(f"selector indices must be non-empty, unique, and chronological for {state}")
        selected: list[int] = []
    else:
        selected = list(indices)
    if selected != report.get("sampled_video_indices"):
        errors.append(f"selector selection is stale for quota video state {state}")
    decoded = report.get("decoded")
    decoded_count = decoded.get("frame_count") if isinstance(decoded, Mapping) else None
    minimum_candidates = 2 if isinstance(decoded_count, int) and decoded_count > len(selected) else 1
    if (
        not isinstance(selector.get("candidate_count"), int)
        or selector["candidate_count"] < minimum_candidates
    ):
        errors.append(
            f"selector must compare at least {minimum_candidates} candidate(s) for {state}"
        )

    html = selector.get("html")
    if isinstance(html, Mapping):
        try:
            html_path = _resolve_media(run_dir, html.get("path"), f"selector HTML for {state}")
            _check_file_record(
                path=html_path,
                record=html,
                label=f"selector HTML for {state}",
                errors=errors,
            )
        except BatchCompletionError as exc:
            errors.append(str(exc))
    else:
        errors.append(f"selector HTML record is missing for {state}")

    timeline = selector.get("timeline")
    pages = timeline.get("pages") if isinstance(timeline, Mapping) else None
    if not isinstance(pages, list) or not pages:
        errors.append(f"selector timeline pages are missing for {state}")
    else:
        for index, page in enumerate(pages):
            if not isinstance(page, Mapping):
                errors.append(f"selector timeline page {index} is invalid for {state}")
                continue
            try:
                page_path = _resolve_media(
                    selector_path.parent,
                    page.get("path"),
                    f"selector timeline page {index} for {state}",
                )
                _check_file_record(
                    path=page_path,
                    record=page,
                    label=f"selector timeline page {index} for {state}",
                    errors=errors,
                )
            except BatchCompletionError as exc:
                errors.append(str(exc))
        manifest_name = timeline.get("manifest")
        manifest_hash = timeline.get("manifest_sha256")
        if isinstance(manifest_name, str) and isinstance(manifest_hash, str):
            try:
                timeline_manifest = _resolve_media(
                    selector_path.parent,
                    manifest_name,
                    f"selector timeline manifest for {state}",
                )
                _check_file_record(
                    path=timeline_manifest,
                    record={"sha256": manifest_hash},
                    label=f"selector timeline manifest for {state}",
                    errors=errors,
                )
            except BatchCompletionError as exc:
                errors.append(str(exc))
        else:
            errors.append(f"selector timeline manifest is missing for {state}")
    return selected


def _audit_quota_report(
    *,
    run_dir: Path,
    state: str,
    report_path: Path,
    errors: list[str],
) -> dict[str, Any]:
    try:
        report = _load_json(report_path, f"quota video report for {state}")
    except BatchCompletionError as exc:
        errors.append(str(exc))
        return {"state": state, "report": str(report_path), "ok": False}
    if report.get("kind") not in {"sprite-video-source", "sprite-grok-video-source"}:
        errors.append(f"quota report is not a supported video source for {state}: {report_path}")
    if report.get("status") != "pass" or report.get("state") != state:
        errors.append(f"quota video report is not a passing {state!r} source: {report_path}")
    video = report.get("video")
    video_hash: str | None = None
    if not isinstance(video, Mapping):
        errors.append(f"quota video record is missing for {state}: {report_path}")
    else:
        if not isinstance(video.get("size_bytes"), int) or video["size_bytes"] < 1:
            errors.append(f"quota video size record is missing for {state}: {report_path}")
        try:
            video_path = _resolve_media(run_dir, video.get("path"), f"quota video for {state}")
            video_hash = _check_file_record(
                path=video_path,
                record=video,
                label=f"quota video for {state}",
                errors=errors,
            )
        except BatchCompletionError as exc:
            errors.append(str(exc))
    selected = _audit_selector(
        run_dir=run_dir,
        state=state,
        report_path=report_path,
        report=report,
        errors=errors,
    )
    return {
        "state": state,
        "report": str(report_path),
        "kind": report.get("kind"),
        "video_sha256": video_hash,
        "selected_indices": selected,
        "ok": video_hash is not None,
    }


def _audit_workbench(run_dir: Path, required_states: Sequence[str], errors: list[str]) -> None:
    evidence_path = run_dir / "qa" / "preview-workbench" / "workbench.evidence.json"
    try:
        evidence = _load_json(evidence_path, "preview workbench evidence")
    except BatchCompletionError as exc:
        errors.append(str(exc))
        return
    if evidence.get("kind") != "sprite-preview-workbench" or not evidence.get(
        "self_contained"
    ):
        errors.append(f"preview workbench evidence is invalid: {evidence_path}")
    states = evidence.get("states")
    if not isinstance(states, list) or any(state not in states for state in required_states):
        errors.append(f"preview workbench does not cover every required state: {evidence_path}")
    artifact = evidence.get("artifact")
    if not isinstance(artifact, Mapping):
        errors.append(f"preview workbench artifact record is missing: {evidence_path}")
        return
    try:
        artifact_path = _resolve_media(run_dir, artifact.get("path"), "preview workbench")
        _check_file_record(
            path=artifact_path,
            record=artifact,
            label="preview workbench",
            errors=errors,
        )
    except BatchCompletionError as exc:
        errors.append(str(exc))


def _audit_candidate(
    *,
    repo_root: Path,
    run_dir: Path,
    review: Mapping[str, Any],
    validation_fingerprint: str,
    validation_path: Path,
    errors: list[str],
) -> None:
    try:
        candidate_path = _resolve_under(repo_root, review.get("candidate"), "candidate")
    except BatchCompletionError as exc:
        errors.append(str(exc))
        return
    expected_hash = review.get("candidate_sha256")
    if not candidate_path.is_dir():
        errors.append(
            f"candidate must be a package directory with manifest.json: {candidate_path}"
        )
        return
    try:
        manifest = _load_json(candidate_path / "manifest.json", "candidate manifest")
    except BatchCompletionError as exc:
        errors.append(str(exc))
        return
    output = manifest.get("outputs")
    png = output.get("png") if isinstance(output, Mapping) else None
    if not isinstance(png, Mapping):
        errors.append(f"candidate manifest has no outputs.png record: {candidate_path}")
        return
    try:
        png_path = _resolve_media(candidate_path, png.get("path"), "candidate PNG")
        actual_hash = _check_file_record(
            path=png_path,
            record=png,
            label="candidate PNG",
            errors=errors,
        )
    except BatchCompletionError as exc:
        errors.append(str(exc))
        return
    if not isinstance(expected_hash, str) or actual_hash != expected_hash:
        errors.append(f"batch candidate hash drift: {png_path}")
    source_validation = manifest.get("source_validation")
    if (
        not isinstance(source_validation, Mapping)
        or source_validation.get("input_fingerprint") != validation_fingerprint
    ):
        errors.append(f"candidate was packaged from stale validation: {candidate_path}")
    elif isinstance(source_validation.get("path"), str):
        source_validation_path = _resolve_media(
            candidate_path, source_validation["path"], "candidate source validation"
        )
        if source_validation_path != validation_path:
            errors.append(f"candidate points to another validation report: {candidate_path}")
    else:
        errors.append(f"candidate source validation path is missing: {candidate_path}")
    source_atlas = manifest.get("source_atlas")
    atlas_path = run_dir / "sprite-sheet-alpha.png"
    if isinstance(source_atlas, Mapping) and atlas_path.is_file():
        if source_atlas.get("sha256") != _sha256(atlas_path):
            errors.append(f"candidate was packaged from a stale source atlas: {candidate_path}")
        if isinstance(source_atlas.get("path"), str):
            packaged_atlas_path = _resolve_media(
                candidate_path, source_atlas["path"], "candidate source atlas"
            )
            if packaged_atlas_path != atlas_path:
                errors.append(f"candidate points to another source atlas: {candidate_path}")
        else:
            errors.append(f"candidate source atlas path is missing: {candidate_path}")
    elif isinstance(source_atlas, Mapping):
        errors.append(f"candidate source atlas is missing: {atlas_path}")
    else:
        errors.append(f"candidate manifest has no source_atlas record: {candidate_path}")


def _audit_entry(
    *,
    repo_root: Path,
    entry: Mapping[str, Any],
    identity: str,
    required_states: Sequence[str],
    quota_sealed: bool,
    expected_videos: int | None,
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    try:
        run_dir = _resolve_under(repo_root, entry.get("run"), f"{identity} run")
    except BatchCompletionError as exc:
        return {"identity": identity, "ok": False, "errors": [str(exc)], "warnings": []}

    states = entry.get("states")
    if not isinstance(states, Mapping):
        errors.append("entry.states must be an object")
        states = {}
    for state in required_states:
        if states.get(state) != "reviewed":
            errors.append(f"state {state!r} is not reviewed")

    review = entry.get("review")
    if not isinstance(review, Mapping):
        errors.append("entry.review must be an object")
        review = {}
    if review.get("status") != "pass":
        errors.append("entry review status is not pass")

    try:
        identity_source = _resolve_under(
            repo_root, entry.get("source"), f"{identity} approved identity source"
        )
        if not identity_source.is_file():
            errors.append(f"approved identity source is missing: {identity_source}")
        elif entry.get("source_sha256") != _sha256(identity_source):
            errors.append(f"approved identity source SHA-256 drift: {identity_source}")
    except BatchCompletionError as exc:
        errors.append(str(exc))

    try:
        request = _load_json(run_dir / "sprite-request.json", "sprite request")
        request_states = request.get("states")
        if not isinstance(request_states, Mapping):
            errors.append("sprite request states must be an object")
            request_states = {}
    except BatchCompletionError as exc:
        errors.append(str(exc))
        request_states = {}
    try:
        frames = _load_json(run_dir / "frames" / "frames-manifest.json", "frames manifest")
        if frames.get("ok") is not True:
            errors.append("frames manifest is not ok")
        rows = frames.get("rows")
        rows_by_state = {
            row.get("state"): row for row in rows if isinstance(row, Mapping)
        } if isinstance(rows, list) else {}
    except BatchCompletionError as exc:
        errors.append(str(exc))
        rows_by_state = {}
    for state in required_states:
        contract = request_states.get(state)
        row = rows_by_state.get(state)
        if not isinstance(contract, Mapping):
            errors.append(f"sprite request is missing required state {state!r}")
            continue
        if not isinstance(row, Mapping):
            errors.append(f"frames manifest is missing required state {state!r}")
            continue
        expected_frames = contract.get("frames")
        files = row.get("files")
        if (
            not isinstance(expected_frames, int)
            or expected_frames < 1
            or not isinstance(files, list)
            or len(files) != expected_frames
        ):
            errors.append(f"extracted frame count does not match request for {state!r}")

    provenance_result = validate_provenance(
        run_dir, allow_imported=True, allow_fixture=False
    )
    if provenance_result.exit_code != 0:
        errors.extend(f"provenance: {message}" for message in provenance_result.errors)
    warnings.extend(f"provenance: {message}" for message in provenance_result.warnings)
    try:
        provenance = _load_json(run_dir / "source-provenance.json", "source provenance")
    except BatchCompletionError as exc:
        errors.append(str(exc))
        provenance = {}
    accepted = provenance.get("accepted_sources")
    accepted_entries = [item for item in accepted if isinstance(item, Mapping)] if isinstance(accepted, list) else []
    accepted_by_state: dict[str, list[Mapping[str, Any]]] = {state: [] for state in required_states}
    for source in accepted_entries:
        source_states = source.get("states")
        if isinstance(source_states, list):
            for state in required_states:
                if state in source_states:
                    accepted_by_state[state].append(source)
    reviewed_sources = review.get("state_sources")
    reviewed_sources = reviewed_sources if isinstance(reviewed_sources, Mapping) else {}
    accepted_types: list[str] = []
    for state in required_states:
        matches = accepted_by_state[state]
        if len(matches) != 1:
            errors.append(f"expected exactly one accepted source for {state!r}")
            continue
        source = matches[0]
        source_type = source.get("source_type", provenance.get("source_type"))
        if isinstance(source_type, str):
            accepted_types.append(source_type)
        reviewed = reviewed_sources.get(state)
        if not isinstance(reviewed, Mapping):
            errors.append(f"batch review is missing state source for {state!r}")
        elif any(reviewed.get(key) != source.get(key) for key in ("path", "sha256")) or (
            reviewed.get("source_type") != source_type
        ):
            errors.append(f"batch review source drift for {state!r}")

    validation_fingerprint = ""
    validation_path: Path | None = None
    try:
        validation_path = _resolve_under(
            repo_root, review.get("validation"), f"{identity} validation"
        )
        expected_validation_path = run_dir / "qa" / "run-validation-report.json"
        if validation_path != expected_validation_path:
            errors.append(
                f"batch review points to another run validation report: {validation_path}"
            )
        validation = _load_json(validation_path, "run validation report")
        validation_fingerprint = str(validation.get("input_fingerprint") or "")
        if (
            validation.get("ok") is not True
            or validation.get("status") != "pass"
            or validation.get("stage") != "pre-package"
        ):
            errors.append(f"run validation is not a passing pre-package report: {validation_path}")
        if review.get("validation_fingerprint") != validation_fingerprint:
            errors.append(f"batch validation fingerprint drift: {validation_path}")
    except BatchCompletionError as exc:
        errors.append(str(exc))
    if validation_fingerprint and validation_path is not None:
        _audit_candidate(
            repo_root=repo_root,
            run_dir=run_dir,
            review=review,
            validation_fingerprint=validation_fingerprint,
            validation_path=validation_path,
            errors=errors,
        )

    _audit_workbench(run_dir, required_states, errors)

    all_reports = sorted((run_dir / "provider").glob("**/video-source.json"))
    quota_records: list[dict[str, Any]] = []
    selected_reports: set[Path] = set()
    if quota_sealed:
        for state in required_states:
            report_path, selection = _quota_report_for_state(
                run_dir, entry, state, all_reports, errors
            )
            if report_path is None:
                continue
            selected_reports.add(report_path.resolve())
            record = _audit_quota_report(
                run_dir=run_dir,
                state=state,
                report_path=report_path,
                errors=errors,
            )
            record["selection"] = selection
            quota_records.append(record)
            reviewed_indices = review.get("selected_indices")
            if isinstance(reviewed_indices, Mapping) and state in reviewed_indices:
                if reviewed_indices.get(state) != record.get("selected_indices"):
                    errors.append(f"batch selected indices drift for {state!r}")

    unique_video_hashes = {
        record["video_sha256"]
        for record in quota_records
        if isinstance(record.get("video_sha256"), str)
    }
    if quota_sealed and expected_videos is not None:
        if len(quota_records) != expected_videos:
            errors.append(
                f"quota video count is {len(quota_records)}; expected {expected_videos}"
            )
        if len(unique_video_hashes) != expected_videos:
            errors.append(
                f"unique quota video count is {len(unique_video_hashes)}; expected {expected_videos}"
            )
    archived_reports = [
        str(path) for path in all_reports if path.resolve() not in selected_reports
    ]
    if archived_reports:
        warnings.append(
            f"{len(archived_reports)} additional video source report(s) are archived, not quota"
        )

    repairs = _completed_repair_states(run_dir, errors)
    for state, matches in accepted_by_state.items():
        if len(matches) != 1:
            continue
        source_type = matches[0].get("source_type", provenance.get("source_type"))
        if quota_sealed and source_type == "imagegen" and state not in repairs:
            errors.append(
                f"quota-sealed Imagegen source for {state!r} has no completed repair plan"
            )
        if quota_sealed and source_type == "imagegen" and state in repairs:
            if matches[0].get("upstream_report") != "qa/quota-sealed-repair-plan.json":
                errors.append(
                    f"quota-sealed Imagegen source for {state!r} is not linked to its repair plan"
                )
            result = repairs[state]
            if result is not None and result != matches[0].get("path"):
                errors.append(f"repair result path drift for {state!r}")

    return {
        "identity": identity,
        "run": str(run_dir),
        "ok": not errors,
        "accepted_source_types": dict(sorted(Counter(accepted_types).items())),
        "quota_videos": quota_records,
        "unique_quota_videos": len(unique_video_hashes),
        "completed_repairs": sorted(repairs),
        "archived_video_reports": archived_reports,
        "errors": errors,
        "warnings": warnings,
    }


def _positive_int(value: Any, label: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise BatchCompletionError(f"{label} must be a positive integer")
    return value


def audit_batch(
    *,
    manifest_path: Path,
    repo_root: Path,
    states_override: str | None,
    identity_fields_override: str | None,
    expected_identities_override: int | None,
    expected_videos_override: int | None,
) -> dict[str, Any]:
    manifest = _load_json(manifest_path, "batch manifest")
    entries = manifest.get("entries")
    if not isinstance(entries, list) or not entries:
        raise BatchCompletionError("batch manifest entries must be a non-empty array")
    if any(not isinstance(entry, Mapping) for entry in entries):
        raise BatchCompletionError("every batch entry must be a JSON object")
    required_states = _states_for_batch(manifest, states_override)
    identity_fields = _identity_fields(manifest, identity_fields_override)
    policy = manifest.get("generation_policy")
    policy = policy if isinstance(policy, Mapping) else {}
    quota_sealed = policy.get("quota_sealed") is True
    expected_identities = expected_identities_override
    if expected_identities is None:
        expected_identities = _positive_int(policy.get("expected_identities"), "expected_identities")
    expected_videos = expected_videos_override
    if expected_videos is None:
        expected_videos = _positive_int(
            policy.get("max_provider_videos_per_identity"),
            "max_provider_videos_per_identity",
        )
    if quota_sealed and expected_videos is None:
        expected_videos = len(required_states)

    identities = [_identity(entry, identity_fields) for entry in entries]
    duplicate_identities = sorted(
        identity for identity, count in Counter(identities).items() if count > 1
    )
    global_errors = [
        f"duplicate batch identity: {identity}" for identity in duplicate_identities
    ]
    if expected_identities is not None and len(entries) != expected_identities:
        global_errors.append(
            f"batch entry count is {len(entries)}; expected {expected_identities}"
        )
    results = [
        _audit_entry(
            repo_root=repo_root,
            entry=entry,
            identity=identity,
            required_states=required_states,
            quota_sealed=quota_sealed,
            expected_videos=expected_videos,
        )
        for entry, identity in zip(entries, identities, strict=True)
    ]
    entry_errors = [
        f"{result['identity']}: {message}"
        for result in results
        for message in result["errors"]
    ]
    warnings = [
        f"{result['identity']}: {message}"
        for result in results
        for message in result["warnings"]
    ]
    accepted_counts: Counter[str] = Counter()
    for result in results:
        accepted_counts.update(result["accepted_source_types"])
    quota_video_count = sum(len(result["quota_videos"]) for result in results)
    quota_hashes = {
        record["video_sha256"]
        for result in results
        for record in result["quota_videos"]
        if isinstance(record.get("video_sha256"), str)
    }
    repair_count = sum(len(result["completed_repairs"]) for result in results)
    archived_count = sum(len(result["archived_video_reports"]) for result in results)
    errors = global_errors + entry_errors
    return {
        "version": 1,
        "kind": "sprite-animation-batch-completion-report",
        "ok": not errors,
        "status": "pass" if not errors else "fail",
        "repo_root": str(repo_root),
        "batch_manifest": str(manifest_path),
        "quota_sealed": quota_sealed,
        "required_states": required_states,
        "identity_fields": identity_fields,
        "counts": {
            "entries": len(results),
            "passing_entries": sum(bool(result["ok"]) for result in results),
            "failing_entries": sum(not result["ok"] for result in results),
            "quota_video_records": quota_video_count,
            "unique_quota_videos": len(quota_hashes),
            "completed_repairs": repair_count,
            "archived_video_reports": archived_count,
            "accepted_source_types": dict(sorted(accepted_counts.items())),
        },
        "errors": errors,
        "warnings": warnings,
        "entries": results,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-manifest", required=True, type=Path)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="root used to resolve run, validation, source, and candidate paths",
    )
    parser.add_argument("--states", help="comma-separated required state names")
    parser.add_argument(
        "--identity-fields",
        help="comma-separated entry keys used when id/identity is absent",
    )
    parser.add_argument("--expected-identities", type=int)
    parser.add_argument("--expected-videos-per-identity", type=int)
    parser.add_argument(
        "--report",
        type=Path,
        help="output JSON; defaults beside the batch manifest",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest_path = args.batch_manifest.expanduser().resolve()
    repo_root = args.repo_root.expanduser().resolve()
    report_path = (
        args.report.expanduser().resolve()
        if args.report is not None
        else manifest_path.parent / "batch-completion-report.json"
    )
    if args.expected_identities is not None and args.expected_identities < 1:
        print("--expected-identities must be a positive integer", file=sys.stderr)
        return 3
    if (
        args.expected_videos_per_identity is not None
        and args.expected_videos_per_identity < 1
    ):
        print("--expected-videos-per-identity must be a positive integer", file=sys.stderr)
        return 3
    try:
        report = audit_batch(
            manifest_path=manifest_path,
            repo_root=repo_root,
            states_override=args.states,
            identity_fields_override=args.identity_fields,
            expected_identities_override=args.expected_identities,
            expected_videos_override=args.expected_videos_per_identity,
        )
        report_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(
            report_path,
            json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        )
    except (BatchCompletionError, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 3
    summary = {key: report[key] for key in ("ok", "status", "counts", "errors", "warnings")}
    summary["report"] = str(report_path)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
