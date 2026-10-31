from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

import pytest
import sync_imagegen_repair_provenance as repair_sync
from spritecore.provenance import validate_provenance

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (
    REPO_ROOT
    / "SKILLS"
    / "spritesheet-expert"
    / "scripts"
    / "sync_imagegen_repair_provenance.py"
)


def _write_run(run_dir: Path, *, repair_status: str = "completed") -> bytes:
    (run_dir / "raw").mkdir(parents=True)
    (run_dir / "qa").mkdir()
    request = {
        "version": 2,
        "kind": "sprite-gen-request",
        "asset_kind": "sprite",
        "frame_semantics": "animation",
        "extraction_mode": "components",
        "cell": {"width": 32, "height": 32, "safe_margin": 2},
        "states": {
            "idle-step": {"frames": 4, "fps": 8, "loop": True},
            "attack": {"frames": 4, "fps": 8, "loop": False},
        },
    }
    (run_dir / "sprite-request.json").write_text(
        json.dumps(request), encoding="utf-8"
    )
    idle_bytes = b"grok-idle-sheet"
    attack_bytes = b"imagegen-attack-sheet"
    (run_dir / "raw" / "idle-step.png").write_bytes(idle_bytes)
    (run_dir / "raw" / "attack.png").write_bytes(attack_bytes)
    provenance = {
        "version": 2,
        "kind": "sprite-source-provenance",
        "source_type": "grok-imagine-video",
        "art_engine": "grok-imagine",
        "fixture": False,
        "verification_status": "verified",
        "accepted_sources": [
            {
                "path": "raw/idle-step.png",
                "sha256": sha256(idle_bytes).hexdigest(),
                "size_bytes": len(idle_bytes),
                "states": ["idle-step"],
                "source_type": "grok-imagine-video",
                "art_engine": "grok-imagine",
                "upstream_report": "provider/grok-imagine/idle-step/video-source.json",
            },
            {
                "path": "raw/attack.png",
                "sha256": "0" * 64,
                "size_bytes": 1,
                "states": ["attack"],
                "source_type": "grok-imagine-video",
                "art_engine": "grok-imagine",
                "upstream_report": "provider/grok-imagine/attack/video-source.json",
            },
        ],
        "state_coverage": ["idle-step", "attack"],
        "license": "xAI-provider-terms",
    }
    (run_dir / "source-provenance.json").write_text(
        json.dumps(provenance), encoding="utf-8"
    )
    plan = {
        "version": 1,
        "status": "completed",
        "repairs": [
            {
                "state": "attack",
                "status": repair_status,
                "method": "imagegen-isolated-frame-edit",
                "result": "raw/attack.png",
            }
        ],
    }
    (run_dir / "qa" / "quota-sealed-repair-plan.json").write_text(
        json.dumps(plan), encoding="utf-8"
    )
    return attack_bytes


def test_syncs_completed_repair_bytes_and_mixed_provenance(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    attack_bytes = _write_run(run_dir)
    provenance_path = run_dir / "source-provenance.json"
    prior = json.loads(provenance_path.read_text())
    prior.update(verification_status="legacy-unverified", notes="Operator evidence", license="Operator license terms")
    provenance_path.write_text(json.dumps(prior), encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--run-dir", str(run_dir)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    response = json.loads(completed.stdout)
    assert response["updated_states"][0]["state"] == "attack"
    provenance = json.loads(
        (run_dir / "source-provenance.json").read_text(encoding="utf-8")
    )
    assert provenance["source_type"] == "mixed"
    assert provenance["art_engine"] == "mixed"
    entries = {entry["states"][0]: entry for entry in provenance["accepted_sources"]}
    assert entries["idle-step"]["source_type"] == "grok-imagine-video"
    assert entries["attack"]["source_type"] == "imagegen"
    assert entries["attack"]["art_engine"] == "imagegen"
    assert entries["attack"]["sha256"] == sha256(attack_bytes).hexdigest()
    assert entries["attack"]["size_bytes"] == len(attack_bytes)
    assert entries["attack"]["upstream_report"] == (
        "qa/quota-sealed-repair-plan.json"
    )
    assert provenance["license"] == prior["license"]
    assert provenance["notes"] == prior["notes"]
    assert provenance["verification_status"] == "legacy-unverified"


def test_rejects_plan_without_completed_repair_state(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _write_run(run_dir, repair_status="pending")
    before = (run_dir / "source-provenance.json").read_bytes()

    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--run-dir", str(run_dir)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 1
    assert "no completed states" in completed.stderr
    assert (run_dir / "source-provenance.json").read_bytes() == before


def test_rejects_a_repair_result_for_another_file_without_writing(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _write_run(run_dir)
    provenance_path = run_dir / "source-provenance.json"
    before = provenance_path.read_bytes()
    plan_path = run_dir / repair_sync.DEFAULT_PLAN
    plan = json.loads(plan_path.read_text())
    plan["repairs"][0]["result"] = "raw/another-file.png"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--run-dir", str(run_dir)],
        cwd=REPO_ROOT, capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 1
    assert "does not match raw/attack.png" in completed.stderr
    assert provenance_path.read_bytes() == before


def test_completed_nonvideo_plan_is_accepted_by_the_provenance_gate(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _write_run(run_dir)
    request_path = run_dir / "sprite-request.json"
    request = json.loads(request_path.read_text())
    request["states"] = {"attack": request["states"]["attack"]}
    request_path.write_text(json.dumps(request), encoding="utf-8")
    provenance_path = run_dir / "source-provenance.json"
    provenance = json.loads(provenance_path.read_text())
    provenance["accepted_sources"] = [provenance["accepted_sources"][1]]
    provenance["state_coverage"] = ["attack"]
    provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--run-dir", str(run_dir)],
        cwd=REPO_ROOT, capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = validate_provenance(run_dir)
    assert result.exit_code == 0, result.errors


def test_sync_preserves_provenance_when_its_plan_changes_during_work(tmp_path: Path, monkeypatch) -> None:
    run_dir = tmp_path / "run"
    _write_run(run_dir)
    provenance_path = run_dir / "source-provenance.json"
    before = provenance_path.read_bytes()
    plan_path = run_dir / repair_sync.DEFAULT_PLAN
    plan_bytes = plan_path.read_bytes()
    plan = json.loads(plan_bytes)
    original_normalize = repair_sync.normalize_contract

    def change_plan(document, **kwargs):
        result = original_normalize(document, **kwargs)
        if document.get("source_type") == "mixed":
            plan_path.write_text(json.dumps({**plan, "status": "pending"}), encoding="utf-8")
        return result

    monkeypatch.setattr(repair_sync, "normalize_contract", change_plan)
    with pytest.raises(repair_sync.RepairProvenanceError, match="input changed during synchronization"):
        repair_sync._sync(
            run_dir=run_dir, plan_path=plan_path, plan_bytes=plan_bytes,
            completed=repair_sync._completed_repairs(plan), states=["attack"],
        )
    assert provenance_path.read_bytes() == before
