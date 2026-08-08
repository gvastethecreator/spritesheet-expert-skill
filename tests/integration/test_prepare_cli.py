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
    assert written["background_removal"]["method"] == "lucida"
    assert written["grid_segmentation"] == "adaptive"


def test_prepare_preserves_creature_motion_and_adds_anatomy_prompt(tmp_path: Path) -> None:
    run_dir = tmp_path / "creature"
    request = {
        "states": {
            "idle-step": {
                "frames": 4,
                "fps": 8,
                "loop": True,
                "action": "frontal step cycle",
            },
            "attack": {
                "frames": 4,
                "fps": 10,
                "loop": False,
                "action": "bilateral grab attack",
            },
        },
        "creature_motion": {
            "anatomy": "biped",
            "locomotion": "walk",
            "camera": "front-fps",
            "registration_anchor": "body-bottom",
            "shared_idle": True,
            "screen_side_labels": True,
            "movement_source": "alternating legs with opposite arm swing",
            "attack_source": "both hands",
            "preserve": ["head size", "torso volume"],
            "reject": ["knee-only motion", "one-hand generic strike"],
        },
    }

    result = subprocess.run(
        [
            sys.executable,
            str(PREPARE),
            "--out-dir",
            str(run_dir),
            "--character-id",
            "frontal-shadow",
            "--request-json",
            json.dumps(request),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    written = json.loads((run_dir / "sprite-request.json").read_text(encoding="utf-8"))
    assert written["creature_motion"] == request["creature_motion"]

    movement_prompt = (run_dir / "prompts" / "idle-step.txt").read_text(encoding="utf-8")
    attack_prompt = (run_dir / "prompts" / "attack.txt").read_text(encoding="utf-8")
    assert "Anatomy class: biped" in movement_prompt
    assert "exact idle, phase A, exact idle, phase B" in movement_prompt
    assert "complete alternating steps" in movement_prompt
    assert "Primary attack source" not in movement_prompt
    assert "Primary attack source: both hands" in attack_prompt
    assert "exact idle, anticipation, active contact, exact idle" in attack_prompt
    assert "complete alternating steps" not in attack_prompt


@pytest.mark.parametrize(
    ("anatomy", "locomotion", "state", "expected", "forbidden"),
    [
        ("winged", "fly", "flight", "Animate both wings", "complete alternating steps"),
        (
            "multi-legged",
            "crawl",
            "crawl",
            "Declare the alternating leg groups",
            "complete alternating steps",
        ),
        (
            "hovering",
            "hover",
            "hover",
            "Animate the lower shroud",
            "complete alternating steps",
        ),
        (
            "amorphous",
            "pulse",
            "pulse",
            "Use localized material pulses",
            "complete alternating steps",
        ),
    ],
)
def test_prepare_uses_anatomy_specific_creature_motion(
    tmp_path: Path,
    anatomy: str,
    locomotion: str,
    state: str,
    expected: str,
    forbidden: str,
) -> None:
    run_dir = tmp_path / anatomy
    request = {
        "states": {
            state: {
                "frames": 4,
                "fps": 8,
                "loop": True,
                "action": f"frontal {state} cycle",
            }
        },
        "creature_motion": {
            "anatomy": anatomy,
            "locomotion": locomotion,
            "camera": "front-fps",
            "registration_anchor": (
                "center" if anatomy in {"winged", "hovering"} else "body-bottom"
            ),
            "shared_idle": True,
            "movement_source": f"{anatomy} motion anatomy",
            "attack_source": "declared natural weapon",
        },
    }

    result = subprocess.run(
        [
            sys.executable,
            str(PREPARE),
            "--out-dir",
            str(run_dir),
            "--character-id",
            f"{anatomy}-creature",
            "--request-json",
            json.dumps(request),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    prompt = (run_dir / "prompts" / f"{state}.txt").read_text(encoding="utf-8")
    assert expected in prompt
    assert forbidden not in prompt


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


def test_prepare_preserves_license_bindings_for_provider_intake(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    request = {
        "states": {
            "idle": {"frames": 1, "fps": 1, "loop": True, "action": "idle"},
        },
        "licenses": [
            {
                "id": "imagegen-generated",
                "status": "generated",
                "reference": "accepted Imagegen provider output",
            }
        ],
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
    assert written["licenses"] == request["licenses"]


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


def test_prepare_routes_character_wave_to_gesture_loop(tmp_path: Path) -> None:
    run_dir = tmp_path / "character-wave"
    request = {
        "asset_kind": "sprite",
        "frame_semantics": "animation",
        "cell": {"width": 192, "height": 192, "safe_margin": 12},
        "states": {
            "wave": {
                "frames": 6,
                "fps": 6,
                "loop": True,
                "action": "friendly planted hand wave gesture",
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
            "gesture-routing",
            "--request-json",
            json.dumps(request),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    summary = json.loads(
        (run_dir / "references" / "art-direction.json").read_text(encoding="utf-8")
    )
    workflows = summary["rows"]["wave"]["animation_workflows"]
    assert "gesture-loop" in workflows
    assert "water-loop" not in workflows
    prompt = (run_dir / "prompts" / "wave.txt").read_text(encoding="utf-8").lower()
    assert "pelvis, both legs, knees, ankles, feet, and contact footprint" in prompt
    assert "only the gesturing shoulder, arm, wrist, and hand" in prompt


@pytest.mark.parametrize(
    ("preset_id", "camera", "expected_workflow", "prompt_fragment"),
    [
        (
            "topdown-character",
            "topdown",
            "topdown-direction-set",
            "visible crown and top surfaces",
        ),
        (
            "isometric-character",
            "isometric",
            "isometric-direction-set",
            "2:1 dimetric screen axes",
        ),
    ],
)
def test_prepare_records_static_direction_workflows_and_projection_contracts(
    tmp_path: Path,
    preset_id: str,
    camera: str,
    expected_workflow: str,
    prompt_fragment: str,
) -> None:
    run_dir = tmp_path / preset_id
    labels = [
        "north-contact-a",
        "north-contact-b",
        "east-contact-a",
        "east-contact-b",
        "south-contact-a",
        "south-contact-b",
        "west-contact-a",
        "west-contact-b",
    ]
    request = {
        "asset_kind": "sprite",
        "frame_semantics": "variants",
        "preset": {"id": preset_id, "camera": camera},
        "states": {
            "direction-keys": {
                "frames": 8,
                "fps": 1,
                "loop": False,
                "action": "four directional keys with opposite contact pairs",
                "asset_labels": labels,
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
            "projection-contract",
            "--request-json",
            json.dumps(request),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    summary = json.loads(
        (run_dir / "references" / "art-direction.json").read_text(encoding="utf-8")
    )
    production_workflows = summary["rows"]["direction-keys"]["production_workflows"]
    assert production_workflows == ["character-pose-set", expected_workflow]
    prompt = (run_dir / "prompts" / "direction-keys.txt").read_text(encoding="utf-8").lower()
    assert prompt_fragment in prompt
    assert "slot 1: north-contact-a" in prompt
    assert "slot 8: west-contact-b" in prompt


@pytest.mark.parametrize(
    ("asset_kind", "frame_semantics", "expected_workflow", "prompt_fragment"),
    [
        ("tileset", "tiles", "tileset-adjacency", "repeat_mode"),
        ("texture", "seamless-textures", "seamless-material-set", "opposite edge strips"),
    ],
)
def test_prepare_records_repeat_workflows_and_full_bleed_contracts(
    tmp_path: Path,
    asset_kind: str,
    frame_semantics: str,
    expected_workflow: str,
    prompt_fragment: str,
) -> None:
    run_dir = tmp_path / asset_kind
    request = {
        "asset_kind": asset_kind,
        "frame_semantics": frame_semantics,
        "extraction_mode": "slots",
        "cell": {"width": 64, "height": 64, "safe_margin": 0},
        "states": {
            "surfaces": {
                "frames": 2,
                "fps": 1,
                "loop": False,
                "action": "runtime surface samples",
                "asset_labels": ["moss-surface", "stone-surface"],
            }
        },
        "asset_catalog": {
            "items": {
                "moss-surface": {
                    "category": "surface",
                    "pivot": [32, 32],
                    "tile_role": "base",
                    "repeat_mode": "self" if asset_kind == "texture" else "adjacency",
                },
                "stone-surface": {
                    "category": "surface",
                    "pivot": [32, 32],
                    "tile_role": "base",
                    "repeat_mode": "self" if asset_kind == "texture" else "adjacency",
                },
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
            "repeat-contract",
            "--request-json",
            json.dumps(request),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    summary = json.loads(
        (run_dir / "references" / "art-direction.json").read_text(encoding="utf-8")
    )
    assert summary["rows"]["surfaces"]["production_workflows"] == [expected_workflow]
    prompt = (run_dir / "prompts" / "surfaces.txt").read_text(encoding="utf-8").lower()
    assert prompt_fragment in prompt
    assert "fill each runtime cell edge-to-edge" in prompt


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
