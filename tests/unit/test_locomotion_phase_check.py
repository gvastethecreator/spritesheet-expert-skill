from __future__ import annotations

from argparse import Namespace

from PIL import Image, ImageDraw

from check_animation_contracts import (
    LOCOMOTION_WORKFLOWS,
    WORKFLOW_CONTRACTS,
    contact_phase_check as contract_phase_check,
    ordered_workflows,
)
from check_motion_variation import (
    contact_phase_check as motion_phase_check,
    support_balance,
    support_side,
)


def _pose(*, lifted_left: int) -> Image.Image:
    image = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((10, 3, 22, 19), fill=(80, 180, 120, 255))
    draw.rectangle((17, 18, 21, 31), fill=(80, 180, 120, 255))
    draw.rectangle((lifted_left, 17, lifted_left + 8, 21), fill=(80, 180, 120, 255))
    return image


def _args() -> Namespace:
    return Namespace(
        lower_body_start=0.45,
        min_contact_balance_abs=0.012,
        min_contact_opposition=0.035,
        min_opposite_contact_pose_diff=0.08,
    )


def test_distinct_contact_poses_can_share_screen_side_balance() -> None:
    contact_a = _pose(lifted_left=7)
    contact_b = _pose(lifted_left=3)
    frames = [contact_a, _pose(lifted_left=5), contact_b, _pose(lifted_left=9)]

    first_side = support_side(support_balance(contact_a), 0.012)
    opposite_side = support_side(support_balance(contact_b), 0.012)
    assert first_side == opposite_side

    for check in (motion_phase_check, contract_phase_check):
        result = check(frames, _args())
        assert result is not None
        assert result["ok"] is True
        assert result["screen_side_is_diagnostic_only"] is True
        assert result["anatomical_leg_alternation_requires_visual_review"] is True


def test_duplicated_opposite_contact_pose_fails_closed() -> None:
    contact = _pose(lifted_left=7)
    frames = [contact, _pose(lifted_left=4), contact.copy(), _pose(lifted_left=10)]

    for check in (motion_phase_check, contract_phase_check):
        result = check(frames, _args())
        assert result is not None
        assert result["ok"] is False
        assert result["opposite_contact_pose_diff"] == 0.0
        assert "duplicated" in result["reason"]


def test_shared_idle_cycle_compares_active_phases() -> None:
    idle = _pose(lifted_left=7)
    phase_a = _pose(lifted_left=3)
    phase_b = _pose(lifted_left=10)
    frames = [idle, phase_a, idle.copy(), phase_b]

    for check in (motion_phase_check, contract_phase_check):
        result = check(frames, _args(), shared_idle=True)
        assert result is not None
        assert result["ok"] is True
        assert result["phase_layout"] == "idle-phase-a-idle-phase-b"
        assert result["first_contact_index"] == 1
        assert result["opposite_contact_index"] == 3


def test_front_fps_creature_locomotion_is_a_first_class_contract() -> None:
    workflow = "front-fps-creature-locomotion"

    assert ordered_workflows([workflow]) == [workflow]
    assert workflow in LOCOMOTION_WORKFLOWS
    assert WORKFLOW_CONTRACTS[workflow]["min_frames"] == 4
    assert any(
        "not a generic biped" in check
        for check in WORKFLOW_CONTRACTS[workflow]["visual_checks"]
    )
