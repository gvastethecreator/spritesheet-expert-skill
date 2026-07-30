from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

from PIL import Image


REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATE_RUN = (
    REPO_ROOT / "SKILLS" / "spritesheet-expert" / "scripts" / "validate_run.py"
)
RECORD_REVIEW = (
    REPO_ROOT
    / "SKILLS"
    / "spritesheet-expert"
    / "scripts"
    / "record_visual_review.py"
)


def _run(run_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VALIDATE_RUN), "--run-dir", str(run_dir), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _static_request(*, source_type: str = "imagegen") -> dict:
    return {
        "version": 2,
        "kind": "sprite-gen-request",
        "asset_kind": "prop",
        "frame_semantics": "variants",
        "extraction_mode": "components",
        "raw_layout_policy": "off",
        "source_type": source_type,
        "cell": {"width": 32, "height": 32},
        "states": {
            "barrel": {"frames": 1, "fps": 1, "loop": False},
        },
        "sampling_policy": {
            "filter": "nearest",
            "wrap": "clamp-to-edge",
            "mipmaps": False,
            "pixel_snap": True,
        },
    }


def _write_valid_provenance(run_dir: Path, *, source_type: str = "imagegen") -> None:
    raw = run_dir / "raw"
    raw.mkdir(parents=True)
    source = raw / "barrel.bin"
    source.write_bytes(b"approved barrel source")
    provenance = {
        "version": 2,
        "kind": "sprite-source-provenance",
        "source_type": source_type,
        "art_engine": source_type,
        "fixture": source_type == "fixture",
        "verification_status": "verified",
        "accepted_sources": [
            {
                "path": "raw/barrel.bin",
                "sha256": sha256(source.read_bytes()).hexdigest(),
                "size_bytes": source.stat().st_size,
                "states": ["barrel"],
            }
        ],
        "state_coverage": ["barrel"],
    }
    (run_dir / "source-provenance.json").write_text(
        json.dumps(provenance), encoding="utf-8"
    )


def _write_static_run(run_dir: Path) -> None:
    run_dir.mkdir()
    (run_dir / "sprite-request.json").write_text(
        json.dumps(_static_request()), encoding="utf-8"
    )
    _write_valid_provenance(run_dir)


def test_empty_run_fails_and_writes_machine_readable_decision(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    result = _run(run_dir, "--stage", "preflight")

    assert result.returncode == 1
    report = json.loads((run_dir / "qa" / "run-validation-report.json").read_text())
    assert report["ok"] is False
    assert report["status"] == "fail"
    assert report["blockers"]


def test_preflight_derives_gates_and_skips_animation_for_static_variants(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    _write_static_run(run_dir)

    result = _run(run_dir, "--stage", "preflight")

    assert result.returncode == 0, result.stderr
    report = json.loads((run_dir / "qa" / "run-validation-report.json").read_text())
    decisions = {item["id"]: item for item in report["policy"]["decisions"]}
    assert decisions["generation-provenance"]["applied"] is True
    assert decisions["animation-contracts"]["applied"] is False
    assert decisions["identity-consistency"]["applied"] is False
    assert report["checked_items"] == ["barrel"]
    assert report["evidence"]["production_media"] == {
        "representative": True,
        "provenance_verified": True,
        "source_types": ["imagegen"],
    }


def test_generated_preflight_fails_when_provenance_is_missing(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "sprite-request.json").write_text(
        json.dumps(_static_request()), encoding="utf-8"
    )

    result = _run(run_dir, "--stage", "preflight")

    assert result.returncode == 1
    report = json.loads((run_dir / "qa" / "run-validation-report.json").read_text())
    provenance = next(
        item for item in report["results"] if item["id"] == "generation-provenance"
    )
    assert provenance["status"] == "fail"
    assert provenance["errors"]
    assert report["evidence"]["production_media"]["representative"] is False


def test_prepackage_is_blocked_when_required_visual_review_is_missing(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    _write_static_run(run_dir)

    result = _run(run_dir, "--stage", "pre-package")

    assert result.returncode == 2
    report = json.loads((run_dir / "qa" / "run-validation-report.json").read_text())
    visual = next(item for item in report["results"] if item["id"] == "visual-review")
    assert visual["status"] == "blocked"
    assert report["complete"] is False


def test_prepackage_passes_with_a_current_hash_bound_visual_review(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _write_static_run(run_dir)
    preview = run_dir / "qa" / "barrel-preview.png"
    preview.parent.mkdir(parents=True)
    Image.new("RGBA", (16, 16), (120, 80, 40, 255)).save(preview)
    draft = tmp_path / "review-draft.json"
    draft.write_text(
        json.dumps(
            {
                "reviewer_kind": "human",
                "scope": "run",
                "stage": "pre-package",
                "status": "pass",
                "reviewed_artifacts": ["qa/barrel-preview.png"],
                "rubric": [
                    {
                        "id": "target-readability",
                        "answer": "pass",
                        "score": 4,
                        "notes": "The barrel silhouette and material bands remain readable at target size.",
                    }
                ],
                "failures": [],
                "waivers": [],
            }
        ),
        encoding="utf-8",
    )
    recorded = subprocess.run(
        [
            sys.executable,
            str(RECORD_REVIEW),
            "--run-dir",
            str(run_dir),
            "--review",
            str(draft),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert recorded.returncode == 0, recorded.stderr

    result = _run(run_dir, "--stage", "pre-package")

    assert result.returncode == 0, result.stderr
    report = json.loads((run_dir / "qa" / "run-validation-report.json").read_text())
    assert report["ok"] is True
    assert report["status"] == "pass"


def test_unknown_or_partial_gate_selection_cannot_produce_a_final_green(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    _write_static_run(run_dir)

    unknown = _run(run_dir, "--stage", "preflight", "--gate", "typo-gate")
    partial = _run(
        run_dir,
        "--stage",
        "pre-package",
        "--gate",
        "generation-provenance",
    )

    assert unknown.returncode == 1
    assert partial.returncode == 2
    report = json.loads((run_dir / "qa" / "run-validation-report.json").read_text())
    assert report["complete"] is False
    assert any("partial" in blocker for blocker in report["blockers"])
