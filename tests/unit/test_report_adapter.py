from __future__ import annotations

from spritecore.reporting import check_result_from_report


def test_exit_zero_cannot_hide_report_ok_false() -> None:
    result = check_result_from_report(
        "frame-alignment",
        {"ok": False, "errors": ["drift"], "rows": [{"state": "idle"}]},
        process_exit_code=0,
        expected_items=("idle",),
        report_path="qa/frame-alignment-report.json",
    )

    assert result.status == "fail"
    assert result.exit_code == 1
    assert "drift" in result.errors


def test_missing_or_malformed_report_fails_even_when_process_says_success() -> None:
    missing = check_result_from_report(
        "identity-consistency",
        None,
        process_exit_code=0,
        expected_items=("idle",),
        report_path="qa/identity-consistency-report.json",
    )
    malformed = check_result_from_report(
        "identity-consistency",
        ["not", "an", "object"],  # type: ignore[arg-type]
        process_exit_code=0,
        expected_items=("idle",),
        report_path="qa/identity-consistency-report.json",
    )

    assert missing.exit_code == 1
    assert malformed.exit_code == 1
    assert any("missing" in error for error in missing.errors)
    assert any("object" in error for error in malformed.errors)


def test_zero_checked_items_or_partial_expected_coverage_fails() -> None:
    zero = check_result_from_report(
        "motion-variation",
        {"ok": True, "checked_states": [], "errors": [], "warnings": []},
        process_exit_code=0,
        expected_items=("run",),
        report_path="qa/motion-variation-report.json",
    )
    partial = check_result_from_report(
        "frame-alignment",
        {"ok": True, "rows": [{"state": "idle"}], "errors": [], "warnings": []},
        process_exit_code=0,
        expected_items=("idle", "run"),
        report_path="qa/frame-alignment-report.json",
    )

    assert zero.exit_code == 1
    assert partial.exit_code == 1
    assert any("zero" in error for error in zero.errors)
    assert any("run" in error for error in partial.errors)


def test_process_exit_two_and_three_keep_blocked_and_operational_semantics() -> None:
    blocked = check_result_from_report(
        "segmentation-diagnostic",
        {"ok": False, "warnings": ["review boxes"]},
        process_exit_code=2,
        expected_items=(),
        report_path="qa/segmentation-report.json",
    )
    operational = check_result_from_report(
        "asset-slots",
        None,
        process_exit_code=3,
        expected_items=("terrain",),
        report_path="qa/asset-slot-review.json",
        stderr="dependency unavailable",
    )

    assert blocked.status == "blocked"
    assert blocked.exit_code == 2
    assert operational.status == "operational-error"
    assert operational.exit_code == 3


def test_native_check_result_report_is_accepted_only_when_consistent() -> None:
    result = check_result_from_report(
        "generation-provenance",
        {
            "id": "generation-provenance",
            "applicable": True,
            "checked_items": ["idle"],
            "errors": [],
            "warnings": [],
            "evidence": {"source_type": "imagegen"},
            "input_fingerprint": "abc",
            "complete": True,
            "status": "pass",
        },
        process_exit_code=0,
        expected_items=("idle",),
        report_path="qa/generation-provenance-report.json",
    )

    assert result.exit_code == 0
    assert result.checked_items == ("idle",)
