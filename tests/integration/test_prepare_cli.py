from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
PREPARE = REPO_ROOT / "SKILLS" / "spritesheet-expert" / "scripts" / "prepare_sprite_run.py"


def test_prepare_writes_a_valid_v2_request(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    request = {
        "states": {
            "idle": {"frames": 2, "fps": 4, "loop": True, "action": "idle"},
        }
    }

    result = subprocess.run(
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

    assert result.returncode == 0, result.stderr
    written = json.loads((run_dir / "sprite-request.json").read_text(encoding="utf-8"))
    assert written["version"] == 2
    assert written["frame_semantics"] == "animation"
    assert written["sampling_policy"]["filter"] == "nearest"
    assert written["states"]["idle"]["raw_layout"]["columns"] == 2


def test_prepare_rejects_a_declared_non_request_contract(tmp_path: Path) -> None:
    request = {
        "version": 2,
        "kind": "sprite-source-provenance",
        "asset_kind": "sprite",
        "frame_semantics": "animation",
        "extraction_mode": "components",
        "cell": {"width": 64, "height": 64, "safe_margin": 4},
        "states": {
            "idle": {
                "frames": 1,
                "fps": 1,
                "loop": True,
                "raw_layout": {
                    "kind": "strip",
                    "columns": 1,
                    "rows": 1,
                    "order": "left-to-right",
                    "delivery": "compose-runtime-row",
                },
            }
        },
        "sampling_policy": {
            "filter": "nearest",
            "wrap": "clamp-to-edge",
            "mipmaps": False,
            "pixel_snap": True,
        },
    }

    result = subprocess.run(
        [
            sys.executable,
            str(PREPARE),
            "--out-dir",
            str(tmp_path / "run"),
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

    assert result.returncode != 0
    assert "kind" in (result.stdout + result.stderr).lower()


def test_prepare_rejects_a_future_request_version(tmp_path: Path) -> None:
    request = {
        "version": 99,
        "kind": "sprite-gen-request",
        "states": {
            "idle": {"frames": 1, "fps": 1, "loop": True, "action": "idle"},
        },
    }

    result = subprocess.run(
        [
            sys.executable,
            str(PREPARE),
            "--out-dir",
            str(tmp_path / "run"),
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

    assert result.returncode != 0
    assert "version 99" in (result.stdout + result.stderr).lower()


def test_prepare_preserves_explicit_v2_semantics_and_sampling(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    request = {
        "version": 2,
        "kind": "sprite-gen-request",
        "asset_kind": "sprite",
        "frame_semantics": "variants",
        "extraction_mode": "components",
        "cell": {"width": 64, "height": 64, "safe_margin": 4},
        "states": {
            "idle": {
                "frames": 1,
                "fps": 1,
                "loop": False,
                "raw_layout": {
                    "kind": "strip",
                    "columns": 1,
                    "rows": 1,
                    "order": "left-to-right",
                    "delivery": "compose-runtime-row",
                },
            }
        },
        "sampling_policy": {
            "filter": "linear",
            "wrap": "clamp-to-edge",
            "mipmaps": True,
            "pixel_snap": False,
        },
    }

    result = subprocess.run(
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

    assert result.returncode == 0, result.stderr
    written = json.loads((run_dir / "sprite-request.json").read_text(encoding="utf-8"))
    assert written["frame_semantics"] == "variants"
    assert written["sampling_policy"] == request["sampling_policy"]


@pytest.mark.parametrize(
    ("frame_semantics", "declared_workflows", "expected_workflows"),
    [
        ("still-assets", None, []),
        ("tiles", None, []),
        ("seamless-textures", None, []),
        ("animation", ["water-loop"], ["water-loop"]),
        ("effects", ["vfx-buildup-peak-decay"], ["vfx-buildup-peak-decay"]),
    ],
)
def test_prepare_routes_workflows_from_semantics_not_static_nouns(
    tmp_path: Path,
    frame_semantics: str,
    declared_workflows: list[str] | None,
    expected_workflows: list[str],
) -> None:
    run_dir = tmp_path / frame_semantics
    state = {
        "frames": 4,
        "fps": 4,
        "loop": frame_semantics in {"animation", "effects"},
        "action": "water wind pickup sparkle effect variants",
    }
    if declared_workflows is not None:
        state["animation_workflows"] = declared_workflows
    request = {
        "asset_kind": "sprite",
        "frame_semantics": frame_semantics,
        "states": {"water-pickups": state},
    }

    result = subprocess.run(
        [
            sys.executable,
            str(PREPARE),
            "--out-dir",
            str(run_dir),
            "--character-id",
            "semantic-routing",
            "--request-json",
            json.dumps(request),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    summary = json.loads(
        (run_dir / "references" / "art-direction.json").read_text(encoding="utf-8")
    )
    assert summary["rows"]["water-pickups"]["animation_workflows"] == expected_workflows


def test_prepare_rejects_temporal_workflow_on_static_semantics(tmp_path: Path) -> None:
    request = {
        "asset_kind": "sprite",
        "frame_semantics": "still-assets",
        "states": {
            "water-pickups": {
                "frames": 2,
                "fps": 1,
                "loop": False,
                "action": "water pickup variants",
                "animation_workflows": ["water-loop"],
            }
        },
    }

    result = subprocess.run(
        [
            sys.executable,
            str(PREPARE),
            "--out-dir",
            str(tmp_path / "run"),
            "--character-id",
            "static-workflow-error",
            "--request-json",
            json.dumps(request),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "static frame_semantics" in (result.stdout + result.stderr)
