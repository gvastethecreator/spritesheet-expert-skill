from __future__ import annotations

from copy import deepcopy
import json

import pytest

from spritecore.contracts import (
    ContractValidationError,
    derive_sampling_policy,
    load_contract,
    load_manifest,
    load_provenance,
    load_report,
    normalize_contract,
    validate_contract,
)
from spritecore.models import ContractKind, STATE_SLUG_PATTERN, is_state_slug


def _valid_v2_request() -> dict:
    return {
        "version": 2,
        "kind": "sprite-gen-request",
        "asset_kind": "sprite",
        "frame_semantics": "animation",
        "extraction_mode": "components",
        "raw_layout_policy": "compact-body-grids",
        "cell": {"width": 32, "height": 32},
        "states": {
            "idle": {
                "frames": 4,
                "fps": 6,
                "loop": True,
                "raw_layout": {
                    "kind": "strip",
                    "columns": 4,
                    "rows": 1,
                    "order": "left-to-right",
                    "delivery": "compose-runtime-row",
                },
            },
        },
        "sampling_policy": {
            "filter": "nearest",
            "wrap": "clamp-to-edge",
            "mipmaps": False,
            "pixel_snap": True,
        },
    }


def _valid_vfx_request() -> dict:
    request = _valid_v2_request()
    request["asset_kind"] = "vfx"
    request["frame_semantics"] = "effects"
    request["states"]["idle"] = {
        "frames": 4,
        "fps": 12,
        "loop": False,
        "raw_layout": {
            "kind": "strip",
            "columns": 4,
            "rows": 1,
            "order": "left-to-right",
            "delivery": "compose-runtime-row",
        },
        "vfx": {
            "pivot": {"role": "emitter", "x": 0.5, "y": 0.75},
            "blend_mode": "additive",
            "phase_sequence": ["buildup", "peak", "decay", "hold"],
            "loop_behavior": "hold-last",
            "compositing_backgrounds": ["#101018", "#F4F1E8"],
        },
    }
    return request


def _replace(document: dict, path: tuple[str, ...], value: object) -> None:
    target = document
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value


def test_state_slug_helper_defines_kebab_case_with_64_character_limit() -> None:
    assert STATE_SLUG_PATTERN
    assert is_state_slug("walk-left")
    assert is_state_slug("a" * 64)
    assert not is_state_slug("walk_left")
    assert not is_state_slug("walk-")
    assert not is_state_slug("a" * 65)


def test_sprite_request_rejects_a_state_id_with_a_trailing_newline() -> None:
    request = _valid_v2_request()
    request["states"] = {"idle\n": request["states"]["idle"]}

    with pytest.raises(ContractValidationError, match="idle"):
        validate_contract(request)


def test_state_slug_rejects_unicode_normalization_and_confusable_spellings() -> None:
    hostile_spellings = (
        "caf\N{LATIN SMALL LETTER E WITH ACUTE}",
        "cafe\N{COMBINING ACUTE ACCENT}",
        "w\N{CYRILLIC SMALL LETTER A}lk",
        "walk\N{HYPHEN}left",
        "\N{FULLWIDTH LATIN SMALL LETTER W}alk",
    )

    assert is_state_slug("walk-left")
    assert all(not is_state_slug(spelling) for spelling in hostile_spellings)


def test_state_slug_boundary_rejects_1000_deterministic_hostile_ids() -> None:
    hostile_patterns = (
        lambda index: f"../state-{index}",
        lambda index: f"state_{index}",
        lambda index: f"State-{index}",
        lambda index: f"state-{index}-",
        lambda index: f"state-{index}\N{CYRILLIC SMALL LETTER A}",
        lambda index: f"state-{index}\N{COMBINING ACUTE ACCENT}",
        lambda index: f"state-{index}\n",
        lambda index: f"state-{index}.png",
        lambda index: f"state--{index}",
        lambda index: f"state-{index}/escape",
    )
    hostile_ids = [
        hostile_patterns[index % len(hostile_patterns)](index)
        for index in range(1000)
    ]

    assert len(set(hostile_ids)) == 1000
    assert all(not is_state_slug(state_id) for state_id in hostile_ids)


def test_sampling_policy_derivation_covers_request_and_manifest_defaults() -> None:
    assert derive_sampling_policy("sprite", pixel_art=None) == {
        "filter": "nearest",
        "wrap": "clamp-to-edge",
        "mipmaps": False,
        "pixel_snap": True,
    }
    assert derive_sampling_policy("texture", pixel_art=False) == {
        "filter": "linear",
        "wrap": "repeat",
        "mipmaps": False,
        "pixel_snap": False,
    }


def test_vfx_request_requires_per_state_runtime_metadata() -> None:
    request = _valid_vfx_request()
    del request["states"]["idle"]["vfx"]

    with pytest.raises(ContractValidationError, match="vfx.*required"):
        validate_contract(request)


def test_vfx_phase_sequence_must_align_with_frame_count() -> None:
    request = _valid_vfx_request()
    request["states"]["idle"]["vfx"]["phase_sequence"] = [
        "buildup",
        "peak",
        "decay",
    ]

    with pytest.raises(ContractValidationError, match="phase_sequence.*4 frames"):
        validate_contract(request)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("blend_mode", "normal", "blend_mode"),
        ("pivot", {"role": "emitter", "x": 1.1, "y": 0.5}, "pivot.x"),
    ],
)
def test_vfx_metadata_rejects_invalid_blend_and_normalized_pivot(
    field: str, value: object, message: str
) -> None:
    request = _valid_vfx_request()
    request["states"]["idle"]["vfx"][field] = value

    with pytest.raises(ContractValidationError, match=message):
        validate_contract(request)


@pytest.mark.parametrize(
    ("loop", "loop_behavior"),
    [(False, "loop"), (True, "once")],
)
def test_vfx_loop_behavior_must_match_runtime_loop(
    loop: bool, loop_behavior: str
) -> None:
    request = _valid_vfx_request()
    request["states"]["idle"]["loop"] = loop
    request["states"]["idle"]["vfx"]["loop_behavior"] = loop_behavior

    with pytest.raises(ContractValidationError, match="loop_behavior.*loop"):
        validate_contract(request)


def test_load_contract_normalizes_v1_sprite_request_without_mutating_input() -> None:
    legacy = {
        "version": 1,
        "kind": "sprite-gen-request",
        "engine": "component-row",
        "character": {"id": "hero", "description": "test hero", "base_image": None},
        "cell": {"width": 32, "height": 32, "safe_margin": 4},
        "states": {
            "idle": {"frames": 4, "fps": 6, "loop": True, "action": "idle loop"},
        },
        "style_preset": "pixel-art",
    }
    original = deepcopy(legacy)

    contract = load_contract(legacy)

    assert legacy == original
    assert contract.kind is ContractKind.SPRITE_REQUEST
    assert contract.version == 2
    assert contract.data["asset_kind"] == "sprite"
    assert contract.data["frame_semantics"] == "animation"
    assert contract.data["extraction_mode"] == "components"
    assert contract.data["grid_segmentation"] == "adaptive"
    assert contract.data["states"]["idle"]["raw_layout"] == {
        "kind": "strip",
        "columns": 4,
        "rows": 1,
        "order": "left-to-right",
        "delivery": "compose-runtime-row",
    }
    assert contract.data["sampling_policy"] == {
        "filter": "nearest",
        "wrap": "clamp-to-edge",
        "mipmaps": False,
        "pixel_snap": True,
    }


def test_deprecated_v1_request_requires_the_normalizing_load_boundary() -> None:
    legacy = {
        "version": 1,
        "kind": "sprite-gen-request",
        "cell": {"width": 32, "height": 32},
        "states": {"idle": {"frames": 2, "fps": 4}},
        "style_preset": "pixel-art",
    }
    original = deepcopy(legacy)

    normalized = load_contract(legacy)

    assert normalized.version == 2
    assert legacy == original
    with pytest.raises(ContractValidationError, match="expected version 2, got 1"):
        validate_contract(legacy)
    assert legacy == original


def test_sprite_request_rejects_unsafe_state_slug() -> None:
    legacy = {
        "version": 1,
        "kind": "sprite-gen-request",
        "cell": {"width": 32, "height": 32},
        "states": {"Walk Left": {"frames": 4, "fps": 8}},
        "style_preset": "pixel-art",
    }

    with pytest.raises(ContractValidationError, match="Walk Left"):
        load_contract(legacy)


def test_sprite_request_schema_enforces_state_slug_length() -> None:
    request = _valid_v2_request()
    request["states"] = {"a" * 65: request["states"]["idle"]}

    with pytest.raises(ContractValidationError, match="too long"):
        validate_contract(request)


def test_sprite_request_accepts_compact_layout_reason_emitted_by_preparer() -> None:
    request = _valid_v2_request()
    request["states"]["idle"]["raw_layout"]["reason"] = "body-animation-anti-drift"

    contract = validate_contract(request)

    assert contract.data["states"]["idle"]["raw_layout"]["reason"] == "body-animation-anti-drift"


def test_request_migration_completes_partial_legacy_raw_layout() -> None:
    legacy = {
        "version": 1,
        "kind": "sprite-gen-request",
        "cell": {"width": 32, "height": 32},
        "states": {
            "walk": {
                "frames": 4,
                "fps": 8,
                "raw_layout": {"columns": 2, "rows": 2},
            }
        },
        "style_preset": "pixel-art",
    }

    contract = load_contract(legacy)

    assert contract.data["states"]["walk"]["raw_layout"] == {
        "kind": "compact-grid",
        "columns": 2,
        "rows": 2,
        "order": "row-major",
        "delivery": "compose-runtime-row",
    }


def test_request_policy_off_keeps_raw_layout_absent() -> None:
    legacy = {
        "version": 1,
        "kind": "sprite-gen-request",
        "raw_layout_policy": "off",
        "cell": {"width": 32, "height": 32},
        "states": {"idle": {"frames": 4, "fps": 8}},
        "style_preset": "pixel-art",
    }

    contract = load_contract(legacy)

    assert contract.data["raw_layout_policy"] == "off"
    assert "raw_layout" not in contract.data["states"]["idle"]
    assert contract.data["grid_segmentation"] == "fixed"


def test_adaptive_grid_segmentation_requires_component_extraction() -> None:
    request = _valid_v2_request()
    request["extraction_mode"] = "slots"
    request["grid_segmentation"] = "adaptive"

    with pytest.raises(
        ContractValidationError,
        match="adaptive requires extraction_mode components",
    ):
        validate_contract(request)


def test_creature_motion_contract_accepts_anatomy_and_runtime_anchor() -> None:
    request = _valid_v2_request()
    request["creature_motion"] = {
        "anatomy": "multi-legged",
        "locomotion": "crawl",
        "camera": "front-fps",
        "registration_anchor": "body-bottom",
        "shared_idle": True,
        "screen_side_labels": True,
        "movement_source": "alternating diagonal leg groups",
        "attack_source": "mandibles and front legs",
        "preserve": ["abdomen center"],
        "reject": ["alignment from one leg tip"],
    }

    contract = validate_contract(request)

    assert contract.data["creature_motion"]["anatomy"] == "multi-legged"
    assert contract.data["creature_motion"]["registration_anchor"] == "body-bottom"


def test_creature_motion_contract_rejects_unknown_anatomy() -> None:
    request = _valid_v2_request()
    request["creature_motion"] = {
        "anatomy": "generic-monster",
        "locomotion": "walk",
        "camera": "front-fps",
        "registration_anchor": "body-bottom",
        "shared_idle": True,
    }

    with pytest.raises(ContractValidationError, match="creature_motion.anatomy"):
        validate_contract(request)


def test_creature_motion_contract_rejects_non_sprite_asset() -> None:
    request = _valid_v2_request()
    request["asset_kind"] = "prop"
    request["frame_semantics"] = "still-assets"
    request["creature_motion"] = {
        "anatomy": "custom",
        "locomotion": "none",
        "camera": "front-fps",
        "registration_anchor": "center",
        "shared_idle": False,
    }

    with pytest.raises(ContractValidationError, match="requires asset_kind sprite"):
        validate_contract(request)


def test_normalize_contract_rejects_declared_kind_mismatch() -> None:
    request = _valid_v2_request()
    request["kind"] = "sprite-source-provenance"

    with pytest.raises(ContractValidationError, match="declared kind.*provenance.*expected.*sprite-request"):
        normalize_contract(request, expected_kind=ContractKind.SPRITE_REQUEST)


def test_normalize_contract_rejects_future_version() -> None:
    request = _valid_v2_request()
    request["version"] = 3

    with pytest.raises(ContractValidationError, match="unsupported version 3"):
        normalize_contract(request, expected_kind=ContractKind.SPRITE_REQUEST)


def test_contract_document_data_is_deeply_immutable_and_to_dict_is_detached() -> None:
    request = _valid_v2_request()
    request["states"]["idle"]["durations_ms"] = [100, 100, 100, 100]
    contract = validate_contract(request)

    with pytest.raises(TypeError):
        contract.data["version"] = 99
    with pytest.raises(TypeError):
        contract.data["states"]["idle"]["fps"] = 99
    with pytest.raises(TypeError):
        contract.data["states"]["idle"]["durations_ms"][0] = 99

    detached = contract.to_dict()
    detached["states"]["idle"]["fps"] = 99
    assert contract.data["states"]["idle"]["fps"] == 6


def test_sprite_request_rejects_durations_count_different_from_frames() -> None:
    request = _valid_v2_request()
    request["states"]["idle"]["durations_ms"] = [100, 100]

    with pytest.raises(ContractValidationError, match="durations_ms.*4 frames"):
        validate_contract(request)


def test_sprite_request_rejects_background_until_a_background_leaf_exists() -> None:
    request = _valid_v2_request()
    request["asset_kind"] = "background"
    request["frame_semantics"] = "background-layers"

    with pytest.raises(ContractValidationError, match="asset_kind"):
        validate_contract(request)


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("states",), {}, "states"),
        (("states", "idle", "frames"), 0, "frames"),
        (("states", "idle", "fps"), 0, "fps"),
        (("asset_kind",), "mesh", "asset_kind"),
        (("frame_semantics",), "cinematic", "frame_semantics"),
        (("sampling_policy", "filter"), "cubic", "sampling_policy.filter"),
        (("states", "idle", "raw_layout", "columns"), 1, "capacity"),
    ],
)
def test_validate_sprite_request_rejects_invalid_core_invariants(
    path: tuple[str, ...], value: object, message: str
) -> None:
    request = _valid_v2_request()
    _replace(request, path, value)

    with pytest.raises(ContractValidationError, match=message):
        validate_contract(request)


def test_load_provenance_migrates_only_explicit_imagegen_evidence() -> None:
    legacy = {
        "version": 1,
        "kind": "sprite-source-provenance",
        "art_engine": "imagegen",
        "source_images": ["raw/idle.png", "raw/run.png"],
        "notes": "accepted generated rows",
    }

    contract = load_provenance(legacy)

    assert contract.kind is ContractKind.PROVENANCE
    assert contract.data == {
        "version": 2,
        "kind": "sprite-source-provenance",
        "source_type": "imagegen",
        "art_engine": "imagegen",
        "fixture": False,
        "verification_status": "legacy-unverified",
        "accepted_sources": [
            {"path": "raw/idle.png", "sha256": None, "size_bytes": None, "states": []},
            {"path": "raw/run.png", "sha256": None, "size_bytes": None, "states": []},
        ],
        "state_coverage": [],
        "notes": "accepted generated rows",
    }


def test_provenance_migration_refuses_to_invent_source_type() -> None:
    ambiguous = {
        "version": 1,
        "kind": "sprite-source-provenance",
        "source_images": ["raw/idle.png"],
    }

    with pytest.raises(ContractValidationError, match="refusing to invent provenance"):
        load_provenance(ambiguous)


def test_provenance_rejects_art_engine_that_identifies_another_source_type() -> None:
    provenance = {
        "version": 2,
        "kind": "sprite-source-provenance",
        "source_type": "imagegen",
        "art_engine": "fixture",
        "fixture": False,
        "verification_status": "verified",
        "accepted_sources": [
            {"path": "raw/idle.png", "sha256": "0" * 64, "size_bytes": 1, "states": ["idle"]}
        ],
        "state_coverage": ["idle"],
    }

    with pytest.raises(ContractValidationError, match="not valid under any"):
        validate_contract(provenance, expected_kind=ContractKind.PROVENANCE)


def test_load_manifest_migrates_legacy_runtime_layout_from_path(tmp_path) -> None:
    legacy = {
        "characterId": "hero",
        "engine": "component-row",
        "sprite_sheet_alpha": "sprite-sheet-alpha.png",
        "cell": {"width": 32, "height": 32},
        "frame_layout": {
            "sheetWidth": 64,
            "sheetHeight": 32,
            "cellWidth": 32,
            "cellHeight": 32,
            "rows": {
                "idle": [
                    {"x": 0, "y": 0, "w": 32, "h": 32},
                    {"x": 32, "y": 0, "w": 32, "h": 32},
                ],
            },
        },
    }
    source = tmp_path / "manifest.json"
    source.write_text(json.dumps(legacy), encoding="utf-8")

    contract = load_manifest(source)

    assert contract.kind is ContractKind.MANIFEST
    assert contract.source == source.resolve()
    assert contract.data["version"] == 2
    assert contract.data["kind"] == "sprite-atlas-manifest"
    assert contract.data["asset_kind"] == "sprite"
    assert contract.data["frame_semantics"] == "animation"
    assert contract.data["atlas"] == {
        "path": "sprite-sheet-alpha.png",
        "width": 64,
        "height": 32,
    }
    assert contract.data["sampling_policy"]["filter"] == "nearest"


def test_sprite_manifest_rejects_a_state_id_with_a_trailing_newline() -> None:
    legacy = {
        "characterId": "hero",
        "sprite_sheet_alpha": "sprite-sheet-alpha.png",
        "cell": {"width": 32, "height": 32},
        "frame_layout": {
            "sheetWidth": 32,
            "sheetHeight": 32,
            "cellWidth": 32,
            "cellHeight": 32,
            "rows": {
                "idle\n": [{"x": 0, "y": 0, "w": 32, "h": 32}],
            },
        },
    }

    with pytest.raises(ContractValidationError, match="idle"):
        load_manifest(legacy)


def test_load_report_migrates_basic_legacy_qa_result() -> None:
    legacy = {
        "ok": False,
        "engine": "frame-alignment",
        "errors": ["idle baseline drifts"],
        "warnings": [],
        "metrics": {"baseline_drift_px": 5},
        "overlay": "qa/idle-onion.png",
    }

    contract = load_report(legacy)

    assert contract.kind is ContractKind.REPORT
    assert contract.data["version"] == 2
    assert contract.data["kind"] == "sprite-qa-report"
    assert contract.data["report_type"] == "frame-alignment"
    assert contract.data["ok"] is False
    assert contract.data["errors"] == ["idle baseline drifts"]
    assert contract.data["metrics"] == {"baseline_drift_px": 5}


def test_qa_report_rejects_errors_when_ok_is_true() -> None:
    report = {
        "version": 2,
        "kind": "sprite-qa-report",
        "report_type": "frame-alignment",
        "ok": True,
        "errors": ["idle baseline drifts"],
        "warnings": [],
        "metrics": {},
    }

    with pytest.raises(ContractValidationError, match="errors"):
        validate_contract(report, expected_kind=ContractKind.REPORT)


def test_qa_report_requires_errors_when_ok_is_false() -> None:
    report = {
        "version": 2,
        "kind": "sprite-qa-report",
        "report_type": "frame-alignment",
        "ok": False,
        "errors": [],
        "warnings": [],
        "metrics": {},
    }

    with pytest.raises(ContractValidationError, match="errors"):
        validate_contract(report, expected_kind=ContractKind.REPORT)
