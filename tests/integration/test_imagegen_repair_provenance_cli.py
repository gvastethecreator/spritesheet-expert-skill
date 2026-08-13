from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys


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
    assert provenance["license"] == "mixed-provider-terms"


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
