from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "SKILLS" / "spritesheet-expert" / "scripts" / "check_workflow_workbenches.py"
DEFAULT_WORKBENCHES = ROOT / "SKILLS" / "spritesheet-expert" / "assets" / "workflow-workbenches"


def run_checker(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_repository_workbench_catalog_is_complete() -> None:
    result = run_checker(DEFAULT_WORKBENCHES)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["ok"] is True
    assert report["active"] == ["sideview-walk"]
    assert report["contract_count"] == 8


def test_checker_rejects_contract_without_review_gates(tmp_path: Path) -> None:
    (tmp_path / "broken").mkdir()
    (tmp_path / "catalog.json").write_text(
        json.dumps(
            {
                "kind": "spritesheet-workflow-workbench-catalog",
                "workbenches": {
                    "broken": {
                        "status": "active",
                        "family": "test",
                        "contract": "broken/contract.json",
                        "candidate_root": "candidates/broken",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "broken" / "contract.json").write_text(
        json.dumps(
            {
                "version": 1,
                "workflow": "broken",
                "asset_kind": "sprite",
                "output_kind": "loop",
                "views": ["side"],
                "frame_count": 4,
                "generation_order": [1, 2, 3, 4],
                "required_templates": ["anchor"],
                "candidate_policy": "test",
                "promotion": "never without review",
            }
        ),
        encoding="utf-8",
    )
    result = run_checker(tmp_path)
    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert report["ok"] is False
    assert any("review_artifacts" in error for error in report["errors"])
    assert any("hard_gates" in error for error in report["errors"])

