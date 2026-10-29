"""Aggregate every applicable sprite QA gate into one honest decision."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping, Sequence

from spritecore.contracts import ContractError, load_provenance, load_sprite_request
from spritecore.policy import GATE_IDS, GatePolicy, GatePolicyError, derive_gate_policy
from spritecore.provenance import validate_provenance
from spritecore.reporting import check_result_from_report
from spritecore.results import CheckResult, CheckStatus
from spritecore.runtime_preview import RuntimePreviewError, load_screenshot_evidence
from spritecore.visual_review import VisualReviewError, load_visual_review


STAGES = ("preflight", "post-extract", "pre-package")
_STAGE_INDEX = {stage: index for index, stage in enumerate(STAGES)}
_GATE_STAGE = {
    "generation-provenance": "preflight",
    "animation-contracts": "post-extract",
    "frame-alignment": "post-extract",
    "identity-consistency": "post-extract",
    "motion-variation": "post-extract",
    "asset-slots": "post-extract",
    "isometric-tiles": "post-extract",
    "segmentation-diagnostic": "post-extract",
    "frame-registration": "post-extract",
    "runtime-preview": "pre-package",
}
_GATE_SCRIPTS = {
    "animation-contracts": "check_animation_contracts.py",
    "frame-alignment": "check_frame_alignment.py",
    "identity-consistency": "check_identity_consistency.py",
    "motion-variation": "check_motion_variation.py",
    "asset-slots": "check_asset_slots.py",
    "isometric-tiles": "check_isometric_tiles.py",
}
_REPORT_PATHS = {
    "generation-provenance": "qa/generation-provenance-report.json",
    "animation-contracts": "qa/animation-contract-report.json",
    "frame-alignment": "qa/frame-alignment-report.json",
    "identity-consistency": "qa/identity-consistency-report.json",
    "motion-variation": "qa/motion-variation-report.json",
    "asset-slots": "qa/asset-slot-review.json",
    "isometric-tiles": "qa/isometric-tile-review.json",
    "segmentation-diagnostic": "qa/segmentation-report.json",
    "frame-registration": "qa/registration-report.json",
}
_LOCOMOTION_WORKFLOWS = {
    "front-fps-creature-locomotion",
    "sideview-locomotion",
    "topdown-locomotion",
    "run-gun-layered-motion",
}


def _skipped(gate_id: str, reason: str) -> CheckResult:
    return CheckResult(
        id=gate_id,
        applicable=False,
        warnings=(reason,),
        complete=True,
        status=CheckStatus.SKIPPED,
    )


def _request_failure(message: str) -> CheckResult:
    return CheckResult(
        id="request-contract",
        applicable=True,
        errors=(message,),
        complete=True,
        status=CheckStatus.FAIL,
    )


def _expected_items(gate_id: str, request: Mapping[str, Any]) -> tuple[str, ...]:
    states = request.get("states") if isinstance(request.get("states"), Mapping) else {}
    if gate_id == "motion-variation":
        top = request.get("animation_workflows")
        top_workflows = set(top) if isinstance(top, (list, tuple)) else set()
        selected: list[str] = []
        for state, entry in states.items():
            workflows = set(top_workflows)
            if isinstance(entry, Mapping) and isinstance(
                entry.get("animation_workflows"), (list, tuple)
            ):
                workflows.update(entry["animation_workflows"])
            if workflows & _LOCOMOTION_WORKFLOWS:
                selected.append(str(state))
        return tuple(sorted(selected))
    return tuple(sorted(str(state) for state in states))


def _read_report(path: Path) -> Mapping[str, Any] | Any | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return ["malformed-report"]


def _execute_script_gate(
    gate_id: str,
    run_dir: Path,
    expected_items: Sequence[str],
) -> CheckResult:
    scripts_dir = Path(__file__).resolve().parent.parent
    process = subprocess.run(
        [
            sys.executable,
            str(scripts_dir / _GATE_SCRIPTS[gate_id]),
            "--run-dir",
            str(run_dir),
        ],
        cwd=scripts_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    relative_report = _REPORT_PATHS[gate_id]
    return check_result_from_report(
        gate_id,
        _read_report(run_dir / relative_report),
        process_exit_code=process.returncode,
        expected_items=expected_items,
        report_path=relative_report,
        stdout=process.stdout,
        stderr=process.stderr,
    )


def _execute_report_gate(
    gate_id: str,
    run_dir: Path,
    expected_items: Sequence[str],
) -> CheckResult:
    relative_report = _REPORT_PATHS[gate_id]
    report = _read_report(run_dir / relative_report)
    if gate_id == "segmentation-diagnostic" and isinstance(report, Mapping):
        process_exit_code = 2 if report.get("diagnostic") is True else 1
    else:
        process_exit_code = 0
    return check_result_from_report(
        gate_id,
        report,
        process_exit_code=process_exit_code,
        expected_items=expected_items,
        report_path=relative_report,
    )


def _visual_review_result(run_dir: Path) -> CheckResult:
    relative = "qa/visual-review.json"
    path = run_dir / relative
    if not path.is_file():
        return CheckResult(
            id="visual-review",
            applicable=True,
            errors=("required pre-package visual review is missing",),
            evidence={"review_path": relative},
            complete=False,
            status=CheckStatus.BLOCKED,
        )
    try:
        review = load_visual_review(path, run_dir=run_dir)
    except VisualReviewError as exc:
        return CheckResult(
            id="visual-review",
            applicable=True,
            errors=(str(exc),),
            evidence={"review_path": relative},
            complete=True,
            status=CheckStatus.FAIL,
        )
    errors: list[str] = []
    if review["stage"] != "pre-package":
        errors.append(
            f"visual review stage must be pre-package, got {review['stage']!r}"
        )
    if review["status"] != "pass":
        errors.append("visual review status is not pass")
    artifacts = tuple(item["path"] for item in review["reviewed_artifacts"])
    return CheckResult(
        id="visual-review",
        applicable=True,
        checked_items=artifacts,
        errors=errors,
        evidence={
            "review_path": relative,
            "reviewer_kind": review["reviewer_kind"],
            "input_fingerprint": review["input_fingerprint"],
        },
        input_fingerprint=review["input_fingerprint"],
        complete=True,
        status=CheckStatus.FAIL if errors else CheckStatus.PASS,
    )


def _runtime_preview_result(run_dir: Path, request: Mapping[str, Any]) -> CheckResult:
    states = request.get("states")
    expected = tuple(sorted(states)) if isinstance(states, Mapping) else ()
    if not expected:
        return CheckResult(
            id="runtime-preview",
            applicable=True,
            errors=("runtime preview has no expected states",),
            complete=True,
            status=CheckStatus.FAIL,
        )
    errors: list[str] = []
    checked: list[str] = []
    fingerprints: dict[str, str] = {}
    for state in expected:
        relative = f"qa/runtime-preview/{state}-playback.evidence.json"
        path = run_dir / relative
        if not path.is_file():
            errors.append(f"state {state}: required runtime playback evidence is missing")
            continue
        try:
            evidence = load_screenshot_evidence(
                path,
                run_dir=run_dir,
                expected_kind="runtime-playback",
                expected_state=state,
            )
        except RuntimePreviewError as exc:
            errors.append(f"state {state}: {exc}")
            continue
        expected_frames = request["states"][state]["frames"]
        if evidence["frames"] != list(range(expected_frames)):
            errors.append(f"state {state}: runtime playback does not cover every frame")
            continue
        checked.append(state)
        fingerprints[state] = evidence["input_fingerprint"]
    if errors:
        return CheckResult(
            id="runtime-preview",
            applicable=True,
            checked_items=tuple(checked),
            errors=tuple(errors),
            evidence={"fingerprints": fingerprints},
            complete=bool(checked) and len(checked) == len(expected),
            status=CheckStatus.BLOCKED,
        )
    aggregate = sha256(
        json.dumps(fingerprints, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return CheckResult(
        id="runtime-preview",
        applicable=True,
        checked_items=tuple(checked),
        evidence={"fingerprints": fingerprints},
        input_fingerprint=f"sha256:{aggregate}",
        complete=True,
        status=CheckStatus.PASS,
    )


def _aggregate_fingerprint(
    policy: GatePolicy | None, results: Sequence[CheckResult]
) -> str:
    payload = {
        "policy": policy.to_dict() if policy else None,
        "results": [result.to_dict() for result in results],
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _overall_status(
    results: Sequence[CheckResult], *, partial: bool
) -> tuple[CheckStatus, int, bool]:
    statuses = {result.status for result in results}
    if CheckStatus.OPERATIONAL_ERROR in statuses:
        return CheckStatus.OPERATIONAL_ERROR, 3, False
    if CheckStatus.FAIL in statuses:
        return CheckStatus.FAIL, 1, True
    if CheckStatus.BLOCKED in statuses or partial:
        return CheckStatus.BLOCKED, 2, False
    return CheckStatus.PASS, 0, True


def validate_run(
    run_dir: Path,
    *,
    stage: str,
    workflow: str = "production",
    selectors: Sequence[str] | None = None,
    allow_imported: bool = False,
    allow_fixture: bool = False,
) -> tuple[dict[str, Any], int]:
    """Execute every policy-required gate scheduled through ``stage``."""

    if stage not in STAGES:
        result = _request_failure(
            f"unknown stage {stage!r}; expected one of {', '.join(STAGES)}"
        )
        return _build_report(
            run_dir,
            stage=stage,
            workflow=workflow,
            policy=None,
            results=[result],
            partial=False,
        )

    run_root = Path(run_dir).expanduser().resolve()
    try:
        request_document = load_sprite_request(run_root / "sprite-request.json")
    except ContractError as exc:
        result = _request_failure(f"sprite request is missing or invalid: {exc}")
        return _build_report(
            run_root,
            stage=stage,
            workflow=workflow,
            policy=None,
            results=[result],
            partial=False,
        )

    request = request_document.to_dict()
    if request.get("source_type") is None:
        try:
            request["source_type"] = load_provenance(
                run_root / "source-provenance.json"
            ).data["source_type"]
        except ContractError:
            pass
    try:
        policy = derive_gate_policy(
            request, workflow=workflow, selectors=selectors
        )
    except GatePolicyError as exc:
        result = _request_failure(str(exc))
        return _build_report(
            run_root,
            stage=stage,
            workflow=workflow,
            policy=None,
            results=[result],
            partial=False,
        )

    results: list[CheckResult] = []
    for decision in policy.decisions:
        gate_id = decision.id
        if not decision.applied:
            results.append(_skipped(gate_id, decision.reason))
            continue
        if _STAGE_INDEX[_GATE_STAGE[gate_id]] > _STAGE_INDEX[stage]:
            results.append(
                _skipped(
                    gate_id,
                    f"deferred until {_GATE_STAGE[gate_id]}; policy reason: {decision.reason}",
                )
            )
            continue
        expected = _expected_items(gate_id, request)
        if gate_id == "generation-provenance":
            results.append(
                validate_provenance(
                    run_root,
                    allow_imported=allow_imported,
                    allow_fixture=allow_fixture,
                )
            )
        elif gate_id == "runtime-preview":
            results.append(_runtime_preview_result(run_root, request))
        elif gate_id in _GATE_SCRIPTS:
            results.append(_execute_script_gate(gate_id, run_root, expected))
        else:
            results.append(_execute_report_gate(gate_id, run_root, expected))

    if stage == "pre-package":
        results.append(_visual_review_result(run_root))
    partial = selectors is not None
    return _build_report(
        run_root,
        stage=stage,
        workflow=workflow,
        policy=policy,
        results=results,
        partial=partial,
    )


def _build_report(
    run_dir: Path,
    *,
    stage: str,
    workflow: str,
    policy: GatePolicy | None,
    results: Sequence[CheckResult],
    partial: bool,
) -> tuple[dict[str, Any], int]:
    status, exit_code, complete = _overall_status(results, partial=partial)
    provenance_result = next(
        (result for result in results if result.id == "generation-provenance"),
        None,
    )
    source_type = (
        provenance_result.evidence.get("source_type")
        if provenance_result is not None
        else None
    )
    provenance_verified = bool(
        provenance_result is not None
        and provenance_result.status is CheckStatus.PASS
        and source_type
    )
    representative = bool(
        workflow == "production"
        and provenance_verified
        and source_type != "fixture"
    )
    blockers = [
        f"{result.id}: {error}"
        for result in results
        for error in result.errors
    ]
    if partial:
        blockers.append("partial gate selection cannot satisfy aggregate final validation")
    checked_items = sorted(
        {item for result in results for item in result.checked_items}
    )
    report = {
        "version": 1,
        "kind": "sprite-run-validation-report",
        "run_dir": str(Path(run_dir).expanduser().resolve()),
        "stage": stage,
        "workflow": workflow,
        "ok": status is CheckStatus.PASS,
        "status": status.value,
        "complete": complete,
        "exit_code": exit_code,
        "input_fingerprint": _aggregate_fingerprint(policy, results),
        "evidence": {
            "production_media": {
                "representative": representative,
                "provenance_verified": provenance_verified,
                "source_types": [source_type] if isinstance(source_type, str) else [],
            }
        },
        "policy": policy.to_dict() if policy else None,
        "checked_items": checked_items,
        "results": [result.to_dict() for result in results],
        "blockers": blockers,
    }
    return report, exit_code


__all__ = ["STAGES", "validate_run"]
