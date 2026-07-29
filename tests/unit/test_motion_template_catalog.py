from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKER = (
    REPO_ROOT
    / "SKILLS"
    / "spritesheet-expert"
    / "scripts"
    / "check_motion_template_library.py"
)
CATALOG = (
    REPO_ROOT
    / "SKILLS"
    / "spritesheet-expert"
    / "assets"
    / "motion-reference-templates"
)


def run_checker(root: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CHECKER), "--template-root", str(root), *extra],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_pending_motion_slots_are_honest_and_structurally_valid() -> None:
    result = run_checker(CATALOG, "--allow-pending")

    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["ok"] is True
    assert report["ready"] is False
    assert len(report["pending_templates"]) == 5


def test_release_ready_motion_gate_rejects_pending_slots() -> None:
    result = run_checker(CATALOG)

    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert report["ok"] is False
    assert report["ready"] is False
    assert len(report["pending_templates"]) == 0


def test_pending_slot_rejects_an_unapproved_png(tmp_path: Path) -> None:
    copied = tmp_path / "templates"
    shutil.copytree(CATALOG, copied)
    manifest = json.loads((copied / "manifest.json").read_text(encoding="utf-8"))
    first = next(iter(manifest["templates"].values()))
    (copied / first["asset"]).write_bytes(b"not-approved")

    result = run_checker(copied, "--allow-pending")

    assert result.returncode == 1
    assert "must not bundle an unapproved master PNG" in result.stdout
