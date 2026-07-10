from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATE = REPO_ROOT / "SKILLS" / "spritesheet-expert" / "scripts" / "migrate_run_contract.py"


def _legacy_request() -> dict:
    return {
        "version": 1,
        "kind": "sprite-gen-request",
        "engine": "component-row",
        "cell": {"width": 32, "height": 32, "safe_margin": 4},
        "states": {
            "idle": {"frames": 2, "fps": 4, "loop": True, "action": "idle"},
        },
        "style_preset": "pixel-art",
    }


def test_migrate_contract_is_dry_run_by_default(tmp_path: Path) -> None:
    source = tmp_path / "sprite-request.json"
    original = _legacy_request()
    source.write_text(json.dumps(original, indent=2) + "\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(MIGRATE), str(source), "--kind", "sprite-request"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(source.read_text(encoding="utf-8")) == original
    report = json.loads(result.stdout)
    assert report["changed"] is True
    assert report["written"] is False
    assert report["contract"]["version"] == 2


def test_migrate_contract_write_keeps_the_original_backup(tmp_path: Path) -> None:
    source = tmp_path / "sprite-request.json"
    original = _legacy_request()
    source.write_text(json.dumps(original, indent=2) + "\n", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(MIGRATE),
            str(source),
            "--kind",
            "sprite-request",
            "--write",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    migrated = json.loads(source.read_text(encoding="utf-8"))
    backup = source.with_name(source.name + ".v1.bak")
    assert migrated["version"] == 2
    assert json.loads(backup.read_text(encoding="utf-8")) == original
