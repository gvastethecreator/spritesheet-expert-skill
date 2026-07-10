from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
RECORDER = (
    REPO_ROOT
    / "SKILLS"
    / "spritesheet-expert"
    / "scripts"
    / "record_visual_review.py"
)
ARTIFACT_SHA256 = "504f86a1a931126d79ea2a3a20bb13aebcf014f4e27b54aa3f52c87407dfc86a"
INPUT_FINGERPRINT = "sha256:f9ad1f8da18923121fc0b5cd4ae27a7bf9fe0a81ddb7e463b7bf85a0796a5446"


def review_draft() -> dict:
    return {
        "version": 999,
        "kind": "caller-controlled-kind",
        "reviewer_kind": "human",
        "scope": "run",
        "stage": "final",
        "status": "pass",
        "reviewed_artifacts": [
            {
                "path": "frames/idle/frame-0.png",
                "sha256": "0" * 64,
                "size_bytes": 999,
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
        "reviewed_at": "2000-01-01T00:00:00Z",
        "input_fingerprint": "sha256:" + "0" * 64,
    }


def test_recorder_hashes_artifacts_and_writes_a_valid_atomic_review(
    tmp_path: Path,
) -> None:
    from spritecore.visual_review import load_visual_review

    run_dir = tmp_path / "run"
    artifact = run_dir / "frames" / "idle" / "frame-0.png"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"sprite-frame")
    draft_path = tmp_path / "review-draft.json"
    draft_path.write_text(json.dumps(review_draft()), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(RECORDER),
            "--run-dir",
            str(run_dir),
            "--review",
            str(draft_path),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    output = run_dir / "qa" / "visual-review.json"
    recorded = json.loads(output.read_text(encoding="utf-8"))
    assert recorded["version"] == 1
    assert recorded["kind"] == "sprite-visual-review"
    assert recorded["reviewed_artifacts"] == [
        {
            "path": "frames/idle/frame-0.png",
            "sha256": ARTIFACT_SHA256,
            "size_bytes": 12,
        }
    ]
    assert recorded["input_fingerprint"] == INPUT_FINGERPRINT
    assert recorded["reviewed_at"].endswith("Z")
    assert recorded["reviewed_at"] != review_draft()["reviewed_at"]
    assert load_visual_review(output, run_dir=run_dir) == recorded
    assert list(output.parent.glob(".visual-review.json.*.tmp")) == []


@pytest.mark.parametrize(
    "artifact_path",
    ["missing.png", "../outside.png", "C:/outside.png", r"\\server\share\outside.png"],
)
def test_recorder_refuses_missing_or_unsafe_artifacts_without_replacing_output(
    tmp_path: Path, artifact_path: str
) -> None:
    run_dir = tmp_path / "run"
    output = run_dir / "qa" / "visual-review.json"
    output.parent.mkdir(parents=True)
    output.write_text("preserve-existing-review\n", encoding="utf-8")
    draft = review_draft()
    draft["reviewed_artifacts"][0]["path"] = artifact_path
    draft_path = tmp_path / "review-draft.json"
    draft_path.write_text(json.dumps(draft), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(RECORDER),
            "--run-dir",
            str(run_dir),
            "--review",
            str(draft_path),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert not result.stdout.strip()
    assert result.stderr.strip()
    assert output.read_text(encoding="utf-8") == "preserve-existing-review\n"
    assert list(output.parent.glob(".visual-review.json.*.tmp")) == []
