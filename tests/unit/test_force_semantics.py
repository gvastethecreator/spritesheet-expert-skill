from __future__ import annotations

import subprocess
import sys
import json
from pathlib import Path

from PIL import Image


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "SKILLS" / "spritesheet-expert" / "scripts"


def run_script(name: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / name), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_smoke_force_validates_reference_before_mutating_output(tmp_path: Path) -> None:
    out_dir = tmp_path / "existing-output"
    out_dir.mkdir()
    sentinel = out_dir / "keep-me.txt"
    sentinel.write_text("owned by caller", encoding="utf-8")

    result = run_script(
        "smoke_presets_from_reference.py",
        "--reference",
        str(tmp_path / "missing.png"),
        "--out-dir",
        str(out_dir),
        "--force",
    )

    assert result.returncode != 0
    assert sentinel.read_text(encoding="utf-8") == "owned by caller"


def test_smoke_force_preserves_unknown_files(tmp_path: Path) -> None:
    reference = tmp_path / "reference.png"
    image = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    for y in range(4, 12):
        for x in range(5, 11):
            image.putpixel((x, y), (220, 70, 70, 255))
    image.save(reference)

    out_dir = tmp_path / "existing-output"
    out_dir.mkdir()
    sentinel = out_dir / "keep-me.txt"
    sentinel.write_text("owned by caller", encoding="utf-8")

    result = run_script(
        "smoke_presets_from_reference.py",
        "--reference",
        str(reference),
        "--out-dir",
        str(out_dir),
        "--source-grid",
        "1x1",
        "--preset",
        "custom-atlas",
        "--force",
    )

    assert result.returncode in {0, 1}
    assert sentinel.read_text(encoding="utf-8") == "owned by caller"


def test_smoke_clean_refuses_an_unowned_output_directory(tmp_path: Path) -> None:
    reference = tmp_path / "reference.png"
    Image.new("RGBA", (8, 8), (200, 60, 60, 255)).save(reference)
    out_dir = tmp_path / "existing-output"
    out_dir.mkdir()
    sentinel = out_dir / "keep-me.txt"
    sentinel.write_text("owned by caller", encoding="utf-8")

    result = run_script(
        "smoke_presets_from_reference.py",
        "--reference",
        str(reference),
        "--out-dir",
        str(out_dir),
        "--source-grid",
        "1x1",
        "--clean",
    )

    assert result.returncode != 0
    assert "marker" in (result.stdout + result.stderr).lower()
    assert sentinel.read_text(encoding="utf-8") == "owned by caller"


def test_smoke_clean_restores_owned_output_when_regeneration_fails(tmp_path: Path) -> None:
    reference = tmp_path / "too-small-reference.png"
    Image.new("RGBA", (1, 1), (200, 60, 60, 255)).save(reference)
    out_dir = tmp_path / "existing-output"
    out_dir.mkdir()
    (out_dir / ".sprite-gen-run.json").write_text(
        json.dumps({"version": 1, "kind": "sprite-run", "run_id": "preset-smoke"}) + "\n",
        encoding="utf-8",
    )
    sentinel = out_dir / "keep-me.txt"
    sentinel.write_text("original owned output", encoding="utf-8")

    result = run_script(
        "smoke_presets_from_reference.py",
        "--reference",
        str(reference),
        "--out-dir",
        str(out_dir),
        "--source-grid",
        "1x1",
        "--preset",
        "custom-atlas",
        "--clean",
    )

    assert result.returncode != 0
    assert sentinel.read_text(encoding="utf-8") == "original owned output"
    assert not list(tmp_path.glob(".existing-output.backup-*"))
    assert not list(tmp_path.glob(".existing-output.rollback-*"))


def test_prepare_rejects_state_paths_before_writing(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    request = {
        "states": {
            "../../../escaped": {
                "frames": 1,
                "fps": 1,
                "loop": False,
                "action": "invalid state path",
            }
        }
    }

    result = run_script(
        "prepare_sprite_run.py",
        "--out-dir",
        str(run_dir),
        "--character-id",
        "hero",
        "--request-json",
        json.dumps(request),
    )

    assert result.returncode != 0
    assert not (tmp_path / "escaped.txt").exists()
    assert not (tmp_path / "escaped.png").exists()


def test_prepare_validates_base_image_before_creating_output(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"

    result = run_script(
        "prepare_sprite_run.py",
        "--out-dir",
        str(run_dir),
        "--character-id",
        "hero",
        "--base-image",
        str(tmp_path / "missing.png"),
    )

    assert result.returncode != 0
    assert not run_dir.exists()


def test_prepare_force_removes_stale_known_outputs_but_preserves_unknown_files(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    first_request = {
        "states": {
            "idle": {"frames": 1, "fps": 1, "loop": True, "action": "idle"},
            "run": {"frames": 1, "fps": 1, "loop": True, "action": "run"},
        }
    }
    second_request = {
        "states": {
            "idle": {"frames": 1, "fps": 1, "loop": True, "action": "idle"},
        }
    }

    first = run_script(
        "prepare_sprite_run.py",
        "--out-dir",
        str(run_dir),
        "--character-id",
        "hero",
        "--request-json",
        json.dumps(first_request),
    )
    assert first.returncode == 0, first.stderr
    sentinel = run_dir / "caller-note.txt"
    sentinel.write_text("keep", encoding="utf-8")

    second = run_script(
        "prepare_sprite_run.py",
        "--out-dir",
        str(run_dir),
        "--character-id",
        "hero",
        "--request-json",
        json.dumps(second_request),
        "--force",
    )

    assert second.returncode == 0, second.stderr
    assert sentinel.read_text(encoding="utf-8") == "keep"
    assert not (run_dir / "prompts" / "run.txt").exists()
    assert not (run_dir / "references" / "layout-guides" / "run.png").exists()


def test_prepare_rejects_explicit_empty_states(tmp_path: Path) -> None:
    result = run_script(
        "prepare_sprite_run.py",
        "--out-dir",
        str(tmp_path / "run"),
        "--character-id",
        "hero",
        "--request-json",
        json.dumps({"states": {}}),
    )

    assert result.returncode != 0
    assert "states" in (result.stdout + result.stderr).lower()


def test_prepare_rejects_non_positive_fps(tmp_path: Path) -> None:
    request = {
        "states": {
            "idle": {"frames": 1, "fps": 0, "loop": True, "action": "idle"},
        }
    }

    result = run_script(
        "prepare_sprite_run.py",
        "--out-dir",
        str(tmp_path / "run"),
        "--character-id",
        "hero",
        "--request-json",
        json.dumps(request),
    )

    assert result.returncode != 0
    assert "fps" in (result.stdout + result.stderr).lower()
