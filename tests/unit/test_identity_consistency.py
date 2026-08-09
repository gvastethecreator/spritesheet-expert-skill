from __future__ import annotations

from check_identity_consistency import unreliable_identity_proxies


def test_narrow_faceless_proxies_are_not_used_as_identity_width_gates() -> None:
    manifest = {
        "sprite_registration": {
            "reference_head_width": 10,
            "reference_upper_width": 15,
            "reference_body_mass_width_80": 180,
        }
    }

    assert unreliable_identity_proxies(manifest) == {
        "head_width_vs_reference",
        "upper_width_vs_reference",
    }


def test_normal_reference_proxies_remain_gated() -> None:
    manifest = {
        "sprite_registration": {
            "reference_head_width": 80,
            "reference_upper_width": 120,
            "reference_body_mass_width_80": 180,
        }
    }

    assert unreliable_identity_proxies(manifest) == set()


def test_hovering_jaw_colony_does_not_use_top_pod_as_head_width_gate() -> None:
    manifest = {
        "sprite_registration": {
            "reference_head_width": 30,
            "reference_upper_width": 120,
            "reference_body_mass_width_80": 180,
        }
    }
    request = {
        "creature_motion": {
            "anatomy": "hovering",
            "movement_source": "staggered hover of six jaw pods",
            "attack_source": "all six jaw pods",
        }
    }

    assert unreliable_identity_proxies(manifest, request) == {
        "head_width_vs_reference"
    }


def test_amorphous_maw_attack_does_not_treat_open_mouth_as_head_growth() -> None:
    manifest = {
        "sprite_registration": {
            "reference_head_width": 176,
            "reference_upper_width": 334,
            "reference_body_mass_width_80": 294,
        }
    }
    request = {
        "creature_motion": {
            "anatomy": "amorphous",
            "attack_source": "only the exact circular central maw",
        }
    }

    assert unreliable_identity_proxies(manifest, request) == {
        "head_width_vs_reference"
    }


def test_biped_with_declared_extra_long_arm_uses_body_mass_for_identity() -> None:
    manifest = {
        "sprite_registration": {
            "reference_head_width": 176,
            "reference_upper_width": 334,
            "reference_body_mass_width_80": 294,
        }
    }
    request = {
        "creature_motion": {
            "anatomy": "biped",
            "movement_source": (
                "two long legs in a normal alternating biped walk with subtle "
                "torso incline and restrained counter-settling of the asymmetric arms"
            ),
            "attack_source": "the single exact extra-long screen-right clawed arm",
        }
    }

    assert unreliable_identity_proxies(manifest, request) == {
        "head_width_vs_reference",
        "upper_width_vs_reference"
    }


def test_long_arm_faceless_biped_does_not_treat_shoulder_bob_as_head_growth() -> None:
    manifest = {
        "sprite_registration": {
            "reference_head_width": 95,
            "reference_upper_width": 78,
            "reference_body_mass_width_80": 202,
        }
    }
    request = {
        "creature_motion": {
            "anatomy": "biped",
            "movement_source": (
                "normal alternating biped strides with subtle torso incline "
                "and restrained long-arm counter-swing"
            ),
            "attack_source": "both exact long clawed hands in one bilateral low frontal maul",
        }
    }

    assert unreliable_identity_proxies(manifest, request) == {
        "head_width_vs_reference",
        "upper_width_vs_reference",
    }


def test_bilateral_long_arm_cross_attack_does_not_gate_elbow_pose_as_scale() -> None:
    manifest = {
        "sprite_registration": {
            "reference_head_width": 84,
            "reference_upper_width": 87,
            "reference_body_mass_width_80": 132,
        }
    }
    request = {
        "creature_motion": {
            "anatomy": "biped",
            "movement_source": "complete heavy biped strides",
            "attack_source": (
                "both exact elongated three-finger hands in one bilateral "
                "inward X-shaped claw slash"
            ),
        }
    }

    assert unreliable_identity_proxies(manifest, request) == {
        "upper_width_vs_reference"
    }
