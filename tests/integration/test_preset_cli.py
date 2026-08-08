from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
CONVERTER = REPO_ROOT / "SKILLS" / "spritesheet-expert" / "scripts" / "preset_to_request.py"
PRESETS = REPO_ROOT / "SKILLS" / "spritesheet-expert" / "references" / "presets.json"
VALIDATOR = REPO_ROOT / "SKILLS" / "spritesheet-expert" / "scripts" / "validate_preset.py"
WORKFLOW_IDS = {
    "idle-breath",
    "fighting-stance-idle",
    "gesture-loop",
    "sideview-locomotion",
    "topdown-locomotion",
    "combat-quick-strike",
    "combat-power-strike",
    "topdown-weapon-attack",
    "responsive-jump",
    "hit-reaction-knockdown",
    "run-gun-layered-motion",
    "vfx-buildup-peak-decay",
    "water-loop",
    "wind-ambient-loop",
    "pickup-feedback",
    "tiny-motion",
}
PRESET_SEMANTICS = {
    "codex-pet": "animation",
    "platformer-character": "animation",
    "topdown-character": "animation",
    "isometric-character": "animation",
    "combat-character": "animation",
    "fighting-game-character": "animation",
    "rpg-monster": "animation",
    "ui-avatar": "animation",
    "tileset-topdown": "tiles",
    "tileset-platformer": "tiles",
    "texture-pack": "seamless-textures",
    "asset-pack": "still-assets",
}


def convert_preset(tmp_path: Path, preset_id: str, *extra: str) -> subprocess.CompletedProcess[str]:
    output = tmp_path / f"{preset_id}.json"
    return subprocess.run(
        [sys.executable, str(CONVERTER), preset_id, "--out", str(output), *extra],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_preset_converter_writes_a_valid_v2_contract(tmp_path: Path) -> None:
    output = tmp_path / "request.json"

    result = subprocess.run(
        [sys.executable, str(CONVERTER), "platformer-character", "--out", str(output)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    request = json.loads(output.read_text(encoding="utf-8"))
    assert request["version"] == 2
    assert request["kind"] == "sprite-gen-request"
    assert request["frame_semantics"] == "animation"
    assert request["sampling_policy"]["filter"] == "nearest"
    assert request["grid_segmentation"] == "adaptive"
    assert request["states"]["run"]["raw_layout"]["columns"] >= 1


@pytest.mark.parametrize("preset_id", PRESET_SEMANTICS)
def test_every_builtin_preset_emits_complete_family_contract(
    tmp_path: Path, preset_id: str
) -> None:
    completed = convert_preset(tmp_path, preset_id)

    assert completed.returncode == 0, completed.stderr
    request = json.loads((tmp_path / f"{preset_id}.json").read_text(encoding="utf-8"))
    expected_semantics = PRESET_SEMANTICS[preset_id]
    assert request["version"] == 2
    assert request["kind"] == "sprite-gen-request"
    assert request["frame_semantics"] == expected_semantics
    assert request["output"]["frame_semantics"] == expected_semantics
    assert set(request["sampling_policy"]) == {
        "filter",
        "wrap",
        "mipmaps",
        "pixel_snap",
    }
    assert request["grid_segmentation"] == (
        "adaptive" if request["asset_kind"] == "sprite" else "fixed"
    )

    for state, entry in request["states"].items():
        assert entry["label"], state
        assert set(entry["animation_workflows"]) <= WORKFLOW_IDS
        if expected_semantics in {
            "variants",
            "tiles",
            "still-assets",
            "seamless-textures",
        }:
            assert entry["loop"] is False
            assert entry["animation_workflows"] == []

    if request["extraction_mode"] == "slots":
        labels = [
            label
            for entry in request["states"].values()
            for label in entry["asset_labels"]
        ]
        assert all(
            len(entry["asset_labels"]) == entry["frames"]
            for entry in request["states"].values()
        )
        catalog = request["asset_catalog"]["items"]
        assert set(catalog) == set(labels)
        for label in labels:
            assert catalog[label]["category"]
            assert len(catalog[label]["pivot"]) == 2
            if request["asset_kind"] == "tileset":
                assert catalog[label].get("tile_role") or catalog[label].get(
                    "edge_role"
                )
                assert catalog[label]["collision"]
                assert catalog[label]["repeat_mode"] in {
                    "self",
                    "adjacency",
                    "overlay",
                }
            if request["asset_kind"] == "texture":
                assert catalog[label]["repeat_mode"] == "self"
            if request["asset_kind"] == "asset":
                assert catalog[label]["strategy_class"]
        adjacency_roles = [
            catalog[label]["tile_role"]
            for label in labels
            if catalog[label].get("repeat_mode") == "adjacency"
        ]
        assert len(adjacency_roles) == len(set(adjacency_roles))


def test_builtin_preset_catalog_passes_semantic_validation() -> None:
    completed = subprocess.run(
        [sys.executable, str(VALIDATOR), str(PRESETS)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize("preset_id", ["custom-atlas", "custom-asset-atlas"])
def test_custom_presets_require_explicit_state_input(
    tmp_path: Path, preset_id: str
) -> None:
    completed = convert_preset(tmp_path, preset_id)

    assert completed.returncode != 0
    message = completed.stdout + completed.stderr
    assert "--states-json" in message
    assert "--states-file" in message


def test_custom_preset_rejects_unknown_workflow(tmp_path: Path) -> None:
    completed = convert_preset(
        tmp_path,
        "custom-atlas",
        "--states-json",
        json.dumps(
            {
                "idle": {
                    "frames": 2,
                    "fps": 4,
                    "loop": True,
                    "animation_workflows": ["typo-workflow"],
                }
            }
        ),
    )

    assert completed.returncode != 0
    assert "unknown animation workflow" in (completed.stdout + completed.stderr)


def test_custom_asset_preset_requires_labels_and_catalog_metadata(
    tmp_path: Path,
) -> None:
    incomplete = convert_preset(
        tmp_path,
        "custom-asset-atlas",
        "--states-json",
        json.dumps(
            {
                "pickups": {
                    "frames": 2,
                    "fps": 1,
                    "loop": False,
                    "action": "coin and water pickup variants",
                }
            }
        ),
    )
    assert incomplete.returncode != 0
    assert "asset_labels" in (incomplete.stdout + incomplete.stderr)

    complete = convert_preset(
        tmp_path,
        "custom-asset-atlas",
        "--states-json",
        json.dumps(
            {
                "pickups": {
                    "frames": 2,
                    "fps": 1,
                    "loop": False,
                    "action": "coin and water pickup variants",
                    "asset_labels": ["gold-coin", "water-flask"],
                    "catalog": {
                        "category": "pickups",
                        "pivot": [32, 60],
                        "strategy_class": "compact_prop",
                    },
                }
            }
        ),
    )

    assert complete.returncode == 0, complete.stderr
    request = json.loads(
        (tmp_path / "custom-asset-atlas.json").read_text(encoding="utf-8")
    )
    assert request["states"]["pickups"]["label"] == "Pickups"
    assert set(request["asset_catalog"]["items"]) == {"gold-coin", "water-flask"}
    assert request["states"]["pickups"]["animation_workflows"] == []


@pytest.mark.parametrize(
    ("mutate", "expected_error"),
    [
        (
            lambda data: data["presets"]["platformer-character"][
                "row_workflows"
            ].__setitem__("idle", ["typo-workflow"]),
            "unknown animation workflow",
        ),
        (
            lambda data: data["presets"]["asset-pack"]["rows"][0].pop(
                "asset_labels"
            ),
            "asset_labels",
        ),
    ],
    ids=["unknown-workflow", "missing-asset-labels"],
)
def test_preset_validator_rejects_incomplete_family_metadata(
    tmp_path: Path, mutate, expected_error: str
) -> None:
    data = json.loads(PRESETS.read_text(encoding="utf-8"))
    mutate(data)
    invalid = tmp_path / "presets.json"
    invalid.write_text(json.dumps(data), encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, str(VALIDATOR), str(invalid)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert expected_error in (completed.stdout + completed.stderr)
