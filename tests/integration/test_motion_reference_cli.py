from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from PIL import Image


REPO_ROOT = Path(__file__).resolve().parents[2]
CHECK = REPO_ROOT / "SKILLS" / "spritesheet-expert" / "scripts" / "check_motion_references.py"


def write_plan(run_dir: Path) -> None:
    path = run_dir / "references" / "motion-reference-plan.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "kind": "imagegen-motion-reference-plan",
                "rows": {
                    "walk": {
                        "expected_output": "references/motion-references/walk.png",
                    }
                },
            }
        ),
        encoding="utf-8",
    )


def run_check(run_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CHECK), "--run-dir", str(run_dir)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_motion_reference_gate_fails_closed_when_imagegen_artifact_is_missing(tmp_path: Path) -> None:
    run_dir = tmp_path / "missing"
    write_plan(run_dir)

    result = run_check(run_dir)

    assert result.returncode == 1
    report = json.loads((run_dir / "qa" / "motion-reference-report.json").read_text(encoding="utf-8"))
    assert report["ok"] is False
    assert "missing Image Gen motion reference" in report["references"][0]["errors"][0]


def test_motion_reference_gate_accepts_large_image_with_bound_imagegen_provenance(tmp_path: Path) -> None:
    run_dir = tmp_path / "valid"
    write_plan(run_dir)
    reference = run_dir / "references" / "motion-references" / "walk.png"
    reference.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (1024, 1024), "white").save(reference)
    reference.with_suffix(".provenance.json").write_text(
        json.dumps(
            {
                "art_engine": "imagegen",
                "state": "walk",
                "selected_source": "generated_images/walk-reference.png",
            }
        ),
        encoding="utf-8",
    )

    result = run_check(run_dir)

    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads((run_dir / "qa" / "motion-reference-report.json").read_text(encoding="utf-8"))
    assert report["ok"] is True
    assert report["references"][0]["size"] == [1024, 1024]
