from __future__ import annotations

from typing import Any

import pytest

from spritecore.policy import GatePolicyError, derive_gate_policy


def _normalized_request(**overrides: Any) -> dict[str, Any]:
    request: dict[str, Any] = {
        "version": 2,
        "kind": "sprite-gen-request",
        "asset_kind": "sprite",
        "frame_semantics": "animation",
        "extraction_mode": "components",
        "source_type": "imagegen",
        "states": {
            "walk": {
                "frames": 4,
                "fps": 8,
                "animation_workflows": ["sideview-locomotion"],
            }
        },
    }
    request.update(overrides)
    return request


def test_production_policy_applies_generated_animated_sprite_gates() -> None:
    policy = derive_gate_policy(_normalized_request(), workflow="production")

    assert policy.categories == ("animated", "generated")
    assert policy.required_gate_ids == (
        "generation-provenance",
        "animation-contracts",
        "frame-alignment",
        "identity-consistency",
        "motion-variation",
        "runtime-preview",
    )
    assert "source_type=imagegen" in policy.applied_reasons["generation-provenance"]
    assert "sideview-locomotion" in policy.applied_reasons["motion-variation"]
    assert "extraction_mode=components" in policy.skipped_reasons["asset-slots"]


def test_front_fps_creature_locomotion_requires_motion_variation_gate() -> None:
    request = _normalized_request()
    request["states"]["walk"]["animation_workflows"] = [
        "front-fps-creature-locomotion"
    ]

    policy = derive_gate_policy(request, workflow="production")

    assert "motion-variation" in policy.required_gate_ids
    assert "front-fps-creature-locomotion" in policy.applied_reasons[
        "motion-variation"
    ]


@pytest.mark.parametrize("source_type", ["grok-imagine-image", "grok-imagine-video", "mixed"])
def test_production_policy_treats_grok_and_mixed_sources_as_generated(
    source_type: str,
) -> None:
    policy = derive_gate_policy(
        _normalized_request(source_type=source_type),
        workflow="production",
    )

    assert policy.categories == ("animated", "generated")
    assert "generation-provenance" in policy.required_gate_ids


def test_isometric_tileset_policy_uses_structured_projection_fact() -> None:
    request = _normalized_request(
        asset_kind="tileset",
        frame_semantics="tiles",
        extraction_mode="slots",
        source_type="imported",
        projection="isometric",
        states={
            "terrain": {
                "frames": 8,
                "fps": 1,
                "action": "static words about animation must not select animation gates",
            }
        },
    )

    policy = derive_gate_policy(request, workflow="production")

    assert policy.categories == ("static", "tileset")
    assert policy.required_gate_ids == (
        "generation-provenance",
        "asset-slots",
        "isometric-tiles",
    )
    assert "projection=isometric" in policy.applied_reasons["isometric-tiles"]
    assert "frame_semantics=tiles" in policy.skipped_reasons["animation-contracts"]


def test_texture_policy_applies_slot_review_without_animation_gates() -> None:
    policy = derive_gate_policy(
        _normalized_request(
            asset_kind="texture",
            frame_semantics="seamless-textures",
            extraction_mode="slots",
            source_type="imported",
            states={"stone": {"frames": 4, "fps": 1}},
        ),
        workflow="production",
    )

    assert policy.categories == ("static", "texture")
    assert policy.required_gate_ids == ("generation-provenance", "asset-slots")
    assert "asset_kind=texture" in policy.applied_reasons["asset-slots"]


def test_static_multiframe_sprite_variants_require_identity_consistency() -> None:
    policy = derive_gate_policy(
        _normalized_request(
            frame_semantics="variants",
            extraction_mode="components",
            states={"poses": {"frames": 9, "fps": 1, "loop": False}},
        ),
        workflow="production",
    )

    assert policy.categories == ("static", "generated")
    assert policy.required_gate_ids == (
        "generation-provenance",
        "identity-consistency",
    )
    assert "multi-frame static" in policy.applied_reasons["identity-consistency"]


def test_single_static_sprite_reference_does_not_require_identity_sequence_gate() -> None:
    policy = derive_gate_policy(
        _normalized_request(
            frame_semantics="variants",
            extraction_mode="components",
            states={"anchor": {"frames": 1, "fps": 1, "loop": False}},
        ),
        workflow="production",
    )

    assert "identity-consistency" not in policy.required_gate_ids


def test_static_identity_policy_ignores_non_numeric_frame_facts() -> None:
    policy = derive_gate_policy(
        _normalized_request(
            frame_semantics="variants",
            extraction_mode="components",
            states={"anchor": {"frames": "unknown", "fps": 1}},
        ),
        workflow="production",
    )

    assert "identity-consistency" not in policy.required_gate_ids


def test_import_diagnostic_uses_report_gates_not_production_gates() -> None:
    policy = derive_gate_policy(
        _normalized_request(source_type="imported"),
        workflow="import-diagnostic",
    )

    assert policy.categories == ("animated", "import-diagnostic")
    assert policy.required_gate_ids == (
        "segmentation-diagnostic",
        "frame-registration",
    )
    assert "does not assert production provenance" in policy.skipped_reasons[
        "generation-provenance"
    ]
    assert "workflow=import-diagnostic" in policy.skipped_reasons[
        "animation-contracts"
    ]
    assert "asset_kind=sprite" in policy.applied_reasons["frame-registration"]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"workflow": "best-effort"}, "unknown workflow"),
        (
            {"workflow": "production", "selectors": ["looks-good-to-me"]},
            "unknown gate selector",
        ),
    ],
)
def test_policy_rejects_unknown_workflow_or_selector(
    kwargs: dict[str, Any], message: str
) -> None:
    with pytest.raises(GatePolicyError, match=message):
        derive_gate_policy(_normalized_request(), **kwargs)


def test_known_selectors_form_a_canonical_gate_allowlist() -> None:
    policy = derive_gate_policy(
        _normalized_request(),
        workflow="production",
        selectors=["frame-alignment", "generation-provenance", "frame-alignment"],
    )

    assert policy.selectors == ("generation-provenance", "frame-alignment")
    assert policy.required_gate_ids == ("generation-provenance", "frame-alignment")
    assert "not selected" in policy.skipped_reasons["animation-contracts"]


def test_policy_rejects_unknown_normalized_source_type() -> None:
    with pytest.raises(GatePolicyError, match="source_type"):
        derive_gate_policy(
            _normalized_request(source_type="AI-ish"),
            workflow="production",
        )


def test_policy_rejects_a_mapping_that_is_not_a_normalized_request() -> None:
    request = _normalized_request()
    del request["frame_semantics"]

    with pytest.raises(GatePolicyError, match="normalized.*frame_semantics"):
        derive_gate_policy(request, workflow="production")
