from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_ROOT = REPO_ROOT / "SKILLS"
PUBLIC_CLIS = {
    "spritesheet-expert": ("scripts/preset_to_request.py", "--help"),
    "build-game-backgrounds": ("scripts/validate_background_pack.py", "--help"),
    "build-game-ui-kits": ("scripts/validate_ui_kit.py", "--help"),
    "build-static-game-assets": ("scripts/validate_static_pack.py", "--help"),
    "compose-asset-mockups": ("scripts/prepare_presentation.py", "--help"),
    "produce-2d-assets": ("scripts/validate_asset_pack.py", "--help"),
}
REQUIREMENTS = {
    "spritesheet-expert": "scripts/requirements-core.txt",
    "build-game-backgrounds": "requirements-runtime.txt",
    "build-game-ui-kits": "requirements-runtime.txt",
    "build-static-game-assets": "requirements-runtime.txt",
    "compose-asset-mockups": "requirements-runtime.txt",
    "produce-2d-assets": "requirements-runtime.txt",
}
REQUEST_FLAGS = {
    "build-game-backgrounds": "--pack",
    "build-game-ui-kits": "--kit",
    "build-static-game-assets": "--pack",
    "compose-asset-mockups": "--presentation",
    "produce-2d-assets": "--pack",
}


def _strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for item in value.values() for text in _strings(item)]
    if isinstance(value, list):
        return [text for item in value for text in _strings(item)]
    return []


@pytest.mark.parametrize("skill", sorted(PUBLIC_CLIS))
def test_published_skill_cli_runs_after_isolated_copy(
    tmp_path: Path, skill: str
) -> None:
    destination = tmp_path / skill
    shutil.copytree(SKILLS_ROOT / skill, destination)
    relative_cli, argument = PUBLIC_CLIS[skill]

    result = subprocess.run(
        [sys.executable, str(destination / relative_cli), argument],
        cwd=destination,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "usage:" in result.stdout.lower()


@pytest.mark.parametrize("skill", sorted(REQUIREMENTS))
def test_published_skill_ships_an_installable_runtime_recovery(
    tmp_path: Path, skill: str
) -> None:
    destination = tmp_path / skill
    shutil.copytree(SKILLS_ROOT / skill, destination)
    requirements = destination / REQUIREMENTS[skill]

    assert requirements.is_file()
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--dry-run",
            "--no-deps",
            "-r",
            str(requirements),
        ],
        cwd=destination,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("skill", sorted(REQUEST_FLAGS))
def test_relocated_leaf_executes_a_real_contract_request(
    tmp_path: Path, skill: str
) -> None:
    destination = tmp_path / skill
    shutil.copytree(SKILLS_ROOT / skill, destination)
    artifact = tmp_path / "artifact"
    artifact.mkdir()
    document = artifact / "request.json"
    document.write_text("{}", encoding="utf-8")
    relative_cli, _ = PUBLIC_CLIS[skill]

    result = subprocess.run(
        [
            sys.executable,
            str(destination / relative_cli),
            REQUEST_FLAGS[skill],
            str(document),
            "--root" if skill != "produce-2d-assets" else "--pack-root",
            str(artifact),
        ],
        cwd=destination,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert "missing runtime dependency" not in result.stdout


@pytest.mark.parametrize("skill", sorted(REQUEST_FLAGS))
def test_relocated_leaf_missing_dependency_points_to_its_own_requirements(
    tmp_path: Path, skill: str
) -> None:
    destination = tmp_path / skill
    shutil.copytree(SKILLS_ROOT / skill, destination)
    artifact = tmp_path / "artifact"
    artifact.mkdir()
    document = artifact / "request.json"
    document.write_text("{}", encoding="utf-8")
    relative_cli, _ = PUBLIC_CLIS[skill]
    requirements = destination / REQUIREMENTS[skill]

    result = subprocess.run(
        [
            sys.executable,
            "-S",
            str(destination / relative_cli),
            REQUEST_FLAGS[skill],
            str(document),
            "--root" if skill != "produce-2d-assets" else "--pack-root",
            str(artifact),
        ],
        cwd=destination,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 3, result.stdout + result.stderr
    assert "missing runtime dependency" in result.stdout
    payload = json.loads(result.stdout)
    assert any(str(requirements) in text for text in _strings(payload))


def test_relocated_main_skill_doctor_uses_bundled_requirements(tmp_path: Path) -> None:
    destination = tmp_path / "spritesheet-expert"
    shutil.copytree(SKILLS_ROOT / "spritesheet-expert", destination)
    doctor = destination / "scripts" / "check_python_env.py"
    requirements = destination / REQUIREMENTS["spritesheet-expert"]

    result = subprocess.run(
        [sys.executable, "-S", str(doctor)],
        cwd=destination,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert str(requirements) in payload["install"]


def test_relocated_main_skill_runs_deterministic_smoke(tmp_path: Path) -> None:
    destination = tmp_path / "spritesheet-expert"
    shutil.copytree(SKILLS_ROOT / "spritesheet-expert", destination)

    result = subprocess.run(
        [sys.executable, str(destination / "scripts" / "smoke_pipeline.py")],
        cwd=destination,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
