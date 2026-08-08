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
