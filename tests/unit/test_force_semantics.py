from __future__ import annotations

import subprocess
import sys
import json
from pathlib import Path

from PIL import Image
from spritecore.paths import create_run_marker


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


def test_smoke_force_refuses_a_reference_inside_its_generated_rows(tmp_path: Path) -> None:
    out_dir = tmp_path / "output"
    reference = out_dir / "custom-atlas/raw/idle.png"
    reference.parent.mkdir(parents=True)
    Image.new("RGBA", (128, 128), (180, 120, 60, 255)).save(reference)
    before = reference.read_bytes()
    result = run_script(
        "smoke_presets_from_reference.py", "--reference", str(reference),
        "--out-dir", str(out_dir), "--source-grid", "1x1", "--preset", "custom-atlas", "--force",
    )
    assert result.returncode == 2
    assert "reference must stay outside" in result.stderr
    assert reference.read_bytes() == before
    assert not (out_dir / ".sprite-gen-run.json").exists()


def test_smoke_force_runs_static_fixtures_with_current_prepare_flags(tmp_path: Path) -> None:
    reference = tmp_path / "reference.png"
    Image.new("RGBA", (128, 128), (180, 120, 60, 255)).save(reference)
    out_dir = tmp_path / "output"
    out_dir.mkdir()
    create_run_marker(out_dir, run_id="preset-smoke")
    sentinel = out_dir / "keep-me.txt"
    sentinel.write_text("caller context", encoding="utf-8")
    before = reference.read_bytes()
    result = run_script(
        "smoke_presets_from_reference.py", "--reference", str(reference),
        "--out-dir", str(out_dir), "--source-grid", "1x1",
        "--preset", "custom-asset-atlas", "--preset", "custom-asset-atlas", "--force",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    summary = json.loads((out_dir / "summary.json").read_text())
    assert summary["fixture"] is summary["ok"] is True
    assert list(summary["presets"]) == ["custom-asset-atlas"]
    assert summary["presets"]["custom-asset-atlas"]["states"] == ["props", "pickups"]
    assert sentinel.read_text(encoding="utf-8") == "caller context"
    assert reference.read_bytes() == before


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

    invalid_image = tmp_path / "invalid.png"
    invalid_image.write_bytes(b"not an image")
    result = run_script("prepare_sprite_run.py", "--out-dir", str(run_dir), "--character-id", "hero",
                        "--base-image", str(invalid_image))
    assert result.returncode != 0
    assert not run_dir.exists()


def test_prepare_force_removes_stale_known_outputs_but_preserves_unknown_files(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    source = tmp_path / "source.png"
    Image.new("RGBA", (32, 32), (180, 80, 40, 255)).save(source)
    source_bytes = source.read_bytes()
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
        "--base-image",
        str(source),
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
        "--base-image",
        str(run_dir / "base-source.png"),
        "--request-json",
        json.dumps(second_request),
        "--force",
    )

    assert second.returncode == 0, second.stderr
    assert sentinel.read_text(encoding="utf-8") == "keep"
    assert (run_dir / "base-source.png").read_bytes() == source_bytes
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
