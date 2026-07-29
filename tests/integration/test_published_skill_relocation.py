from __future__ import annotations

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
