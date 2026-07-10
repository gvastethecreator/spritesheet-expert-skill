from __future__ import annotations

import pytest

from spritecore.results import CheckResult


def test_passing_check_has_zero_exit_and_canonical_output() -> None:
    result = CheckResult(
        id="generation-provenance",
        applicable=True,
        checked_items=["source-provenance.json"],
        errors=[],
        warnings=["accepted imported source"],
        evidence={"source_type": "imported"},
        input_fingerprint="sha256:abc123",
        complete=True,
        status="pass",
    )

    assert result.exit_code == 0
    assert result.to_dict() == {
        "id": "generation-provenance",
        "applicable": True,
        "checked_items": ["source-provenance.json"],
        "errors": [],
        "warnings": ["accepted imported source"],
        "evidence": {"source_type": "imported"},
        "input_fingerprint": "sha256:abc123",
        "complete": True,
        "status": "pass",
    }


@pytest.mark.parametrize(
    ("status", "applicable", "complete", "errors", "expected_exit"),
    [
        ("fail", True, True, ["quality contract failed"], 1),
        ("blocked", True, False, ["required input is missing"], 2),
        ("operational-error", True, False, ["could not read input"], 3),
        ("skipped", False, True, [], 0),
    ],
)
def test_check_status_has_deterministic_exit_semantics(
    status: str,
    applicable: bool,
    complete: bool,
    errors: list[str],
    expected_exit: int,
) -> None:
    result = CheckResult(
        id="frame-alignment",
        applicable=applicable,
        errors=errors,
        complete=complete,
        status=status,
    )

    assert result.exit_code == expected_exit


@pytest.mark.parametrize(
    "overrides",
    [
        {"status": "pass", "errors": ["hidden failure"]},
        {"status": "fail", "errors": []},
        {"status": "blocked", "complete": True, "errors": ["missing input"]},
        {
            "status": "operational-error",
            "complete": True,
            "errors": ["I/O failed"],
        },
        {"status": "skipped", "applicable": True},
    ],
)
def test_status_cannot_contradict_outcome_facts(overrides: dict[str, object]) -> None:
    values: dict[str, object] = {
        "id": "frame-alignment",
        "applicable": True,
        "errors": [],
        "complete": True,
        "status": "pass",
    }
    values.update(overrides)

    with pytest.raises(ValueError, match="status"):
        CheckResult(**values)


def test_check_result_rejects_non_json_evidence() -> None:
    with pytest.raises(TypeError, match="JSON-compatible"):
        CheckResult(
            id="asset-slots",
            applicable=True,
            evidence={"bad": {"unordered", "set"}},
            status="pass",
        )


def test_check_result_requires_evidence_to_be_a_mapping() -> None:
    with pytest.raises(TypeError, match="evidence.*mapping"):
        CheckResult(
            id="asset-slots",
            applicable=True,
            evidence=["not", "a", "mapping"],  # type: ignore[arg-type]
            status="pass",
        )


def test_check_result_rejects_a_bare_string_as_an_item_sequence() -> None:
    with pytest.raises(TypeError, match="checked_items.*sequence"):
        CheckResult(
            id="generation-provenance",
            applicable=True,
            checked_items="source-provenance.json",  # type: ignore[arg-type]
            status="pass",
        )


def test_check_result_detaches_and_deeply_freezes_evidence() -> None:
    source = {"z": {"files": ["b.png", "a.png"]}, "a": True}
    result = CheckResult(
        id="asset-slots",
        applicable=True,
        evidence=source,
        status="pass",
    )

    source["z"]["files"].append("later.png")
    detached = result.to_dict()
    detached["evidence"]["z"]["files"].append("detached.png")

    assert list(result.evidence) == ["a", "z"]
    assert result.to_dict()["evidence"]["z"]["files"] == ["b.png", "a.png"]
    with pytest.raises(TypeError):
        result.evidence["new"] = True


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"id": "Frame Alignment"}, "id"),
        ({"applicable": 1}, "applicable"),
        ({"complete": 1}, "complete"),
        ({"input_fingerprint": 123}, "input_fingerprint"),
    ],
)
def test_check_result_rejects_noncanonical_scalar_fields(
    overrides: dict[str, object], message: str
) -> None:
    values: dict[str, object] = {
        "id": "frame-alignment",
        "applicable": True,
        "complete": True,
        "status": "pass",
    }
    values.update(overrides)

    with pytest.raises((TypeError, ValueError), match=message):
        CheckResult(**values)


def test_spritecore_exports_the_result_and_policy_contracts() -> None:
    from spritecore import (
        CheckResult as ExportedCheckResult,
        CheckStatus,
        GateDecision,
        GatePolicy,
        GatePolicyError,
        derive_gate_policy,
    )

    assert ExportedCheckResult is CheckResult
    assert CheckStatus.PASS.value == "pass"
    assert GateDecision.__name__ == "GateDecision"
    assert GatePolicy.__name__ == "GatePolicy"
    assert issubclass(GatePolicyError, ValueError)
    assert callable(derive_gate_policy)
