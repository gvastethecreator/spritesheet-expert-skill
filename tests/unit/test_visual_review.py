from __future__ import annotations

import json
from pathlib import Path

import pytest


ARTIFACT_SHA256 = "504f86a1a931126d79ea2a3a20bb13aebcf014f4e27b54aa3f52c87407dfc86a"
INPUT_FINGERPRINT = "sha256:f9ad1f8da18923121fc0b5cd4ae27a7bf9fe0a81ddb7e463b7bf85a0796a5446"


def valid_visual_review() -> dict:
    return {
        "version": 1,
        "kind": "sprite-visual-review",
        "reviewer_kind": "human",
        "scope": "run",
        "stage": "final",
        "status": "pass",
        "reviewed_artifacts": [
            {
                "path": "frames/idle/frame-0.png",
                "sha256": ARTIFACT_SHA256,
                "size_bytes": 12,
            }
        ],
        "rubric": [
            {
                "id": "identity-consistency",
                "answer": "pass",
                "score": 5,
                "notes": "Silhouette, palette, and costume details match the approved anchor.",
            }
        ],
        "failures": [],
        "waivers": [],
        "reviewed_at": "2026-07-10T15:00:00Z",
        "input_fingerprint": INPUT_FINGERPRINT,
    }


def failed_visual_review() -> dict:
    review = valid_visual_review()
    review["status"] = "fail"
    review["rubric"][0].update(
        {
            "answer": "fail",
            "score": 1,
            "notes": "The second pose loses the approved shoulder marking.",
        }
    )
    review["failures"] = [
        {
            "id": "identity-drift",
            "rubric_id": "identity-consistency",
            "message": "The second pose loses the approved shoulder marking.",
            "artifact_path": "frames/idle/frame-0.png",
        }
    ]
    review["waivers"] = [
        {
            "failure_id": "identity-drift",
            "owner": "qa",
            "reason": "Approved only for this internal animation timing prototype.",
            "expires_at": "2026-08-01T00:00:00Z",
        }
    ]
    return review


def create_reviewed_artifact(run_dir: Path) -> Path:
    artifact = run_dir / "frames" / "idle" / "frame-0.png"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"sprite-frame")
    return artifact


def test_validate_visual_review_accepts_a_hash_bound_review(tmp_path: Path) -> None:
    from spritecore.visual_review import validate_visual_review

    run_dir = tmp_path / "run"
    create_reviewed_artifact(run_dir)
    review = valid_visual_review()

    validated = validate_visual_review(review, run_dir=run_dir)

    assert validated == review
    assert validated is not review


def test_validate_visual_review_rejects_an_artifact_changed_after_review(
    tmp_path: Path,
) -> None:
    from spritecore.visual_review import (
        VisualReviewValidationError,
        validate_visual_review,
    )

    run_dir = tmp_path / "run"
    artifact = create_reviewed_artifact(run_dir)
    review = valid_visual_review()
    artifact.write_bytes(b"changed-sprite-frame")

    with pytest.raises(VisualReviewValidationError, match="artifact changed"):
        validate_visual_review(review, run_dir=run_dir)


def test_validate_visual_review_rejects_a_different_input_fingerprint(
    tmp_path: Path,
) -> None:
    from spritecore.visual_review import (
        VisualReviewValidationError,
        validate_visual_review,
    )

    run_dir = tmp_path / "run"
    create_reviewed_artifact(run_dir)
    review = valid_visual_review()
    review["input_fingerprint"] = "sha256:" + "0" * 64

    with pytest.raises(VisualReviewValidationError, match="input_fingerprint"):
        validate_visual_review(review, run_dir=run_dir)


@pytest.mark.parametrize("artifact_path", ["missing.png", "../outside.png"])
def test_validate_visual_review_refuses_missing_or_unsafe_artifacts(
    tmp_path: Path, artifact_path: str
) -> None:
    from spritecore.visual_review import (
        VisualReviewValidationError,
        validate_visual_review,
    )

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    review = valid_visual_review()
    review["reviewed_artifacts"][0]["path"] = artifact_path

    with pytest.raises(VisualReviewValidationError, match="missing|traversal"):
        validate_visual_review(review, run_dir=run_dir)


def test_visual_review_requires_at_least_one_visual_artifact(tmp_path: Path) -> None:
    from spritecore.visual_review import (
        VisualReviewValidationError,
        compute_input_fingerprint,
        snapshot_review_artifact,
        validate_visual_review,
    )

    run_dir = tmp_path / "run"
    artifact = run_dir / "qa" / "metrics.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"sprite-frame")
    snapshot = snapshot_review_artifact(run_dir, "qa/metrics.json")
    review = valid_visual_review()
    review["reviewed_artifacts"] = [snapshot]
    review["input_fingerprint"] = compute_input_fingerprint([snapshot])

    with pytest.raises(VisualReviewValidationError, match="visual artifact"):
        validate_visual_review(review, run_dir=run_dir)


def test_validate_visual_review_rejects_pass_with_failures(tmp_path: Path) -> None:
    from spritecore.visual_review import (
        VisualReviewValidationError,
        validate_visual_review,
    )

    run_dir = tmp_path / "run"
    create_reviewed_artifact(run_dir)
    review = valid_visual_review()
    review["failures"] = [
        {
            "id": "identity-drift",
            "rubric_id": "identity-consistency",
            "message": "The second pose loses the approved shoulder marking.",
            "artifact_path": "frames/idle/frame-0.png",
        }
    ]

    with pytest.raises(VisualReviewValidationError, match="failures"):
        validate_visual_review(review, run_dir=run_dir)


def test_validate_visual_review_accepts_a_failure_with_an_owned_expiring_waiver(
    tmp_path: Path,
) -> None:
    from spritecore.visual_review import validate_visual_review

    run_dir = tmp_path / "run"
    create_reviewed_artifact(run_dir)
    review = failed_visual_review()

    assert validate_visual_review(review, run_dir=run_dir) == review


def test_validate_visual_review_rejects_a_waiver_for_an_unknown_failure(
    tmp_path: Path,
) -> None:
    from spritecore.visual_review import (
        VisualReviewValidationError,
        validate_visual_review,
    )

    run_dir = tmp_path / "run"
    create_reviewed_artifact(run_dir)
    review = failed_visual_review()
    review["waivers"][0]["failure_id"] = "missing-failure"

    with pytest.raises(VisualReviewValidationError, match="unknown failure"):
        validate_visual_review(review, run_dir=run_dir)


def test_load_visual_review_reads_and_revalidates_a_recorded_file(
    tmp_path: Path,
) -> None:
    from spritecore.visual_review import load_visual_review

    run_dir = tmp_path / "run"
    create_reviewed_artifact(run_dir)
    review = valid_visual_review()
    source = run_dir / "qa" / "visual-review.json"
    source.parent.mkdir(parents=True)
    source.write_text(json.dumps(review), encoding="utf-8")

    assert load_visual_review(source, run_dir=run_dir) == review


def test_load_visual_review_uses_the_canonical_run_location_by_default(
    tmp_path: Path,
) -> None:
    from spritecore.visual_review import load_visual_review

    run_dir = tmp_path / "run"
    create_reviewed_artifact(run_dir)
    review = valid_visual_review()
    source = run_dir / "qa" / "visual-review.json"
    source.parent.mkdir(parents=True)
    source.write_text(json.dumps(review), encoding="utf-8")

    assert load_visual_review(run_dir=run_dir) == review


def test_load_visual_review_reports_a_missing_required_review(tmp_path: Path) -> None:
    from spritecore.visual_review import VisualReviewLoadError, load_visual_review

    run_dir = tmp_path / "run"
    run_dir.mkdir()

    with pytest.raises(VisualReviewLoadError, match="could not load visual review"):
        load_visual_review(run_dir=run_dir)


def test_visual_review_requires_supported_reviewer_concrete_notes_and_utc(
    tmp_path: Path,
) -> None:
    from spritecore.visual_review import (
        VisualReviewValidationError,
        validate_visual_review,
    )

    run_dir = tmp_path / "run"
    create_reviewed_artifact(run_dir)

    invalid_reviewer = valid_visual_review()
    invalid_reviewer["reviewer_kind"] = "script"
    with pytest.raises(VisualReviewValidationError, match="reviewer_kind"):
        validate_visual_review(invalid_reviewer, run_dir=run_dir)

    vague_notes = valid_visual_review()
    vague_notes["rubric"][0]["notes"] = "looks ok"
    with pytest.raises(VisualReviewValidationError, match="notes"):
        validate_visual_review(vague_notes, run_dir=run_dir)

    non_utc_timestamp = valid_visual_review()
    non_utc_timestamp["reviewed_at"] = "2026-07-10T12:00:00-03:00"
    with pytest.raises(VisualReviewValidationError, match="reviewed_at"):
        validate_visual_review(non_utc_timestamp, run_dir=run_dir)


def test_visual_review_rejects_rubric_answer_score_contradictions(tmp_path: Path) -> None:
    from spritecore.visual_review import (
        VisualReviewValidationError,
        validate_visual_review,
    )

    run_dir = tmp_path / "run"
    create_reviewed_artifact(run_dir)
    review = valid_visual_review()
    review["rubric"][0]["score"] = 1

    with pytest.raises(VisualReviewValidationError, match="score"):
        validate_visual_review(review, run_dir=run_dir)


def test_visual_review_requires_waiver_owner_reason_and_utc_expiry(
    tmp_path: Path,
) -> None:
    from spritecore.visual_review import (
        VisualReviewValidationError,
        validate_visual_review,
    )

    run_dir = tmp_path / "run"
    create_reviewed_artifact(run_dir)
    review = failed_visual_review()
    del review["waivers"][0]["owner"]

    with pytest.raises(VisualReviewValidationError, match="owner"):
        validate_visual_review(review, run_dir=run_dir)


def test_visual_review_rejects_a_waiver_expiring_before_the_review(
    tmp_path: Path,
) -> None:
    from spritecore.visual_review import (
        VisualReviewValidationError,
        validate_visual_review,
    )

    run_dir = tmp_path / "run"
    create_reviewed_artifact(run_dir)
    review = failed_visual_review()
    review["waivers"][0]["expires_at"] = "2026-07-01T00:00:00Z"

    with pytest.raises(VisualReviewValidationError, match="after reviewed_at"):
        validate_visual_review(review, run_dir=run_dir)
