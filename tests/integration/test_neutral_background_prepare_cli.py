from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PREPARE = REPO_ROOT / "SKILLS" / "spritesheet-expert" / "scripts" / "prepare_sprite_run.py"


def test_prepare_defaults_sprite_runs_to_black_lucida_and_adaptive_segmentation(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    request = {
        "states": {
            "idle": {"frames": 2, "fps": 4, "loop": True, "action": "quiet idle"},
        }
    }

    completed = subprocess.run(
        [
            sys.executable,
            str(PREPARE),
            "--out-dir",
            str(run_dir),
            "--character-id",
            "hero",
            "--request-json",
            json.dumps(request),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    written = json.loads((run_dir / "sprite-request.json").read_text(encoding="utf-8"))
    background = written["generation_background"]
    assert background["family"] == "neutral"
    assert background["hex"] == "#000000"
    assert background["selection"] == "fallback"
    assert written["background_removal"]["source_family"] == "neutral"
    assert written["background_removal"]["method"] == "lucida"
    assert written["background_removal"]["model"] == "egeorcun/lucida"
    assert written["background_removal"]["revision"] == (
        "6ee11122534c8de59402a589d2293c198cfbf848"
    )
    assert written["background_removal"]["alpha_mode"] == "hard"
    assert written["background_removal"]["hard_alpha_threshold"] == 64
    assert written["grid_segmentation"] == "adaptive"

    prompt = (run_dir / "prompts" / "idle.txt").read_text(encoding="utf-8")
    lowered = prompt.lower()
    assert "flat pure neutral" in lowered
    assert "chroma-key" not in lowered
    assert "#00ff00" not in lowered
    assert "#004dff" not in lowered
    assert "#ff00ff" not in lowered
    assert "do not use #808080" not in lowered
    assert "white backgrounds" not in lowered
    assert "black backgrounds" not in lowered


def test_prepare_can_choose_an_explicit_white_neutral_background(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"

    completed = subprocess.run(
        [
            sys.executable,
            str(PREPARE),
            "--out-dir",
            str(run_dir),
            "--character-id",
            "hero",
            "--request-json",
            json.dumps(
                {
                    "states": {
                        "idle": {
                            "frames": 1,
                            "fps": 1,
                            "loop": True,
                            "action": "idle",
                        }
                    }
                }
            ),
            "--generation-background",
            "#FFFFFF",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    written = json.loads((run_dir / "sprite-request.json").read_text(encoding="utf-8"))
    assert written["generation_background"] == {
        "family": "neutral",
        "name": "white",
        "hex": "#FFFFFF",
        "rgb": [255, 255, 255],
        "selection": "manual",
    }
