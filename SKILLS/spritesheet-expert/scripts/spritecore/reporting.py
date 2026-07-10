"""Normalize legacy JSON reports and process exits into canonical check results."""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Any, Mapping, Sequence

from spritecore.results import CheckResult, CheckStatus


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _checked_items(report: Mapping[str, Any]) -> list[str]:
    for key in ("checked_items", "checked_states"):
        direct = _string_list(report.get(key))
        if direct or key in report:
            return direct
    for key in ("rows", "results", "records"):
        entries = report.get(key)
        if not isinstance(entries, (list, tuple)):
            continue
        found: list[str] = []
        for entry in entries:
            if not isinstance(entry, Mapping):
                continue
            item = next(
                (
                    entry.get(name)
                    for name in ("state", "id", "name", "label")
                    if isinstance(entry.get(name), str) and entry.get(name)
                ),
                None,
            )
            if item is not None and item not in found:
                found.append(item)
        return found
    return []


def _report_fingerprint(report: Mapping[str, Any]) -> str:
    payload = json.dumps(
        dict(report), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def check_result_from_report(
    gate_id: str,
    report: Mapping[str, Any] | None,
    *,
    process_exit_code: int,
    expected_items: Sequence[str] = (),
    report_path: str,
    stdout: str = "",
    stderr: str = "",
) -> CheckResult:
    """Fail closed when process exit, report facts, and coverage disagree."""

    errors: list[str] = []
    warnings: list[str] = []
    checked: list[str] = []
    fingerprint: str | None = None
    evidence: dict[str, Any] = {
        "report_path": report_path,
        "process_exit_code": process_exit_code,
    }
    if stdout:
        evidence["stdout_tail"] = stdout[-4000:]
    if stderr:
        evidence["stderr_tail"] = stderr[-4000:]

    if report is None:
        errors.append(f"mandatory report is missing: {report_path}")
    elif not isinstance(report, Mapping):
        errors.append(f"mandatory report must be a JSON object: {report_path}")
        report = None
    else:
        fingerprint = _report_fingerprint(report)
        evidence["report_sha256"] = fingerprint
        checked = _checked_items(report)
        errors.extend(_string_list(report.get("errors")))
        warnings.extend(_string_list(report.get("warnings")))
        if report.get("ok") is False:
            errors.append("report declared ok:false")
        declared_status = report.get("status")
        if isinstance(declared_status, str):
            evidence["declared_status"] = declared_status
            if declared_status in {"fail", "blocked", "operational-error"}:
                errors.append(f"report declared status:{declared_status}")
            elif declared_status not in {"pass", "skipped"}:
                errors.append(f"report has unknown status:{declared_status}")
        if report.get("id") not in {None, gate_id}:
            errors.append(
                f"report id {report.get('id')!r} does not match gate {gate_id!r}"
            )

    expected = tuple(dict.fromkeys(expected_items))
    missing = sorted(set(expected) - set(checked))
    if expected and not checked:
        errors.append("zero expected items were checked")
    if missing:
        errors.append(f"report did not check expected items: {', '.join(missing)}")

    if process_exit_code == 2:
        errors.append("gate reported blocked/incomplete execution")
        status = CheckStatus.BLOCKED
        complete = False
    elif process_exit_code >= 3 or process_exit_code < 0:
        errors.append(f"gate operational failure (exit {process_exit_code})")
        status = CheckStatus.OPERATIONAL_ERROR
        complete = False
    elif process_exit_code == 1:
        if not errors:
            errors.append("gate process reported a contract or quality failure")
        status = CheckStatus.FAIL
        complete = True
    elif process_exit_code != 0:
        errors.append(f"gate returned unsupported exit code {process_exit_code}")
        status = CheckStatus.OPERATIONAL_ERROR
        complete = False
    elif errors:
        status = CheckStatus.FAIL
        complete = True
    else:
        status = CheckStatus.PASS
        complete = True

    return CheckResult(
        id=gate_id,
        applicable=True,
        checked_items=checked,
        errors=errors,
        warnings=warnings,
        evidence=evidence,
        input_fingerprint=fingerprint,
        complete=complete,
        status=status,
    )


__all__ = ["check_result_from_report"]
