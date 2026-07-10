from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_ROOTS = (
    REPO_ROOT / "SKILLS" / "spritesheet-expert" / "scripts",
    REPO_ROOT / "SKILLS" / "produce-2d-assets" / "scripts",
    REPO_ROOT / "SKILLS" / "compose-asset-mockups" / "scripts",
    REPO_ROOT / "SKILLS" / "build-static-game-assets" / "scripts",
    REPO_ROOT / "SKILLS" / "build-game-backgrounds" / "scripts",
    REPO_ROOT / "SKILLS" / "build-game-ui-kits" / "scripts",
)

for script_root in reversed(SCRIPT_ROOTS):
    sys.path.insert(0, str(script_root))
