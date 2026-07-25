from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image


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


def test_prepare_emits_imagegen_motion_reference_contract_without_drawing_stick_figures(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "walk-reference"
    request = {
        "asset_kind": "sprite",
        "states": {
            "walk": {
                "frames": 8,
                "fps": 10,
                "loop": True,
                "action": "side-view walk cycle facing right",
            }
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
    contract = json.loads(
        (run_dir / "references" / "motion-reference-contracts" / "walk.json").read_text(
            encoding="utf-8"
        )
    )
    plan = json.loads(
        (run_dir / "references" / "motion-reference-plan.json").read_text(encoding="utf-8")
    )
    motion_prompt = (run_dir / "prompts" / "motion-references" / "walk.txt").read_text(
        encoding="utf-8"
    )
    row_prompt = (run_dir / "prompts" / "walk.txt").read_text(encoding="utf-8")

    assert contract["art_engine"] == "imagegen"
    assert contract["required_before_row_generation"] is True
    assert contract["expected_output"] == "references/motion-references/walk.png"
    assert [phase["name"] for phase in contract["phase_sequence"]] == [
        "contact",
        "down",
        "passing",
        "up",
        "opposite_contact",
        "opposite_down",
        "opposite_passing",
        "opposite_up",
    ]
    assert plan["rows"]["walk"] == contract
    assert "anatomical_left_arm: flat coral red" in motion_prompt
    assert "anatomical_right_leg: flat leaf green" in motion_prompt
    assert "scientific-educational" in motion_prompt
    assert "references/motion-references/walk.png" in row_prompt
    assert "not an identity or style reference" in row_prompt

    with Image.open(run_dir / "references" / "layout-guides" / "walk.png") as guide:
        colors = set(guide.convert("RGB").get_flattened_data())
    assert (239, 68, 68) not in colors
    assert (37, 99, 235) not in colors


def test_prepare_reuses_approved_eight_frame_template_for_four_frame_left_walk(
    tmp_path: Path,
) -> None:
    template_root = tmp_path / "templates"
    template_root.mkdir()
    master_path = template_root / "side-right.png"
    master = Image.new("RGB", (1024, 512), "white")
    for index in range(8):
        column = index % 4
        row = index // 4
        color = (20 + index * 20, 40 + index * 10, 60 + index * 5)
        Image.new("RGB", (256, 256), color).save(template_root / f"cell-{index}.png")
        master.paste(color, (column * 256, row * 256, (column + 1) * 256, (row + 1) * 256))
    master.save(master_path)
    digest = hashlib.sha256(master_path.read_bytes()).hexdigest()
    (template_root / "manifest.json").write_text(
        json.dumps(
            {
                "templates": {
                    "side-right": {
                        "status": "approved",
                        "view": "side",
                        "facing": "right",
                        "frames": 8,
                        "grid": {"columns": 4, "rows": 2},
                        "asset": "side-right.png",
                        "sha256": digest,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    run_dir = tmp_path / "run"

    result = subprocess.run(
        [
            sys.executable,
            str(PREPARE),
            "--out-dir",
            str(run_dir),
            "--character-id",
            "hero",
            "--motion-template-root",
            str(template_root),
            "--request-json",
            json.dumps(
                {
                    "states": {
                        "walk-left": {
                            "frames": 4,
                            "fps": 8,
                            "loop": True,
                            "action": "side-view walk left",
                        }
                    }
                }
            ),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    contract = json.loads(
        (run_dir / "references" / "motion-reference-contracts" / "walk-left.json").read_text(
            encoding="utf-8"
        )
    )
    assert contract["source"] == {
        "mode": "approved-template",
        "template_id": "side-right",
        "mirrored": True,
        "derived_frames": [0, 2, 4, 6],
    }
    output_path = run_dir / "references" / "motion-references" / "walk-left.png"
    with Image.open(output_path) as output:
        assert output.size == (512, 512)
    provenance = json.loads(output_path.with_suffix(".provenance.json").read_text(encoding="utf-8"))
    assert provenance["art_engine"] == "imagegen"
    assert provenance["selected_source"] == "template:side-right"
