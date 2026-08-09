from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw

from check_animation_contracts import (
    infer_workflows,
    inspect_action,
    inspect_locomotion,
    normalized_visual_pair_diff,
)
from check_frame_alignment import row_kind
from extract_sprite_row_frames import (
    exact_idle_copy_pairs,
    inferred_pose_geometry,
    restore_source_foreground_regions,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "SKILLS" / "spritesheet-expert" / "scripts"


def _run(name: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / name), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_pose_geometry_ignores_forbidden_pose_words() -> None:
    assert inferred_pose_geometry(
        "attack",
        {"action": "Remain airborne; never stand, squat, land, walk, or grow."},
    ) is None
    assert inferred_pose_geometry(
        "crouch",
        {"action": "Never rotate or zoom."},
    )["kind"] == "crouch"


def test_alignment_fails_when_manifest_is_missing_and_zero_rows_are_checked(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "sprite-request.json").write_text(
        json.dumps({"states": {"idle": {"frames": 1, "fps": 1}}}),
        encoding="utf-8",
    )

    result = _run("check_frame_alignment.py", "--run-dir", str(run_dir))

    assert result.returncode != 0
    report = json.loads((run_dir / "qa" / "frame-alignment-report.json").read_text())
    assert report["ok"] is False
    assert report["rows"] == []
    assert report["errors"]


def test_winged_flight_idle_step_is_not_treated_as_grounded() -> None:
    request = {
        "creature_motion": {"anatomy": "winged", "locomotion": "fly"},
        "states": {"idle-step": {"frames": 4, "fps": 8}},
    }

    assert row_kind("idle-step", {"state": "idle-step"}, request) == "airborne"


def test_amorphous_pulse_uses_declared_motion_thresholds_without_weakening_default() -> None:
    frames = []
    for active_side in (None, "left", None, "right"):
        frame = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(frame)
        draw.rectangle((10, 12, 54, 58), fill=(150, 150, 150, 255))
        if active_side == "left":
            draw.rectangle((3, 44, 12, 58), fill=(150, 150, 150, 255))
        elif active_side == "right":
            draw.rectangle((52, 44, 61, 58), fill=(150, 150, 150, 255))
        frames.append(frame)
    args = SimpleNamespace(
        lower_body_start=0.45,
        min_average_lower_diff=0.10,
        min_pair_lower_diff=0.04,
        min_support_range=0.045,
        min_contact_balance_abs=0.012,
        min_contact_opposition=0.035,
        min_opposite_contact_pose_diff=0.08,
        min_center_range=0.015,
    )

    default_errors, _, _ = inspect_locomotion([], frames, [], args, shared_idle=True)
    pulse_errors, _, pulse_metrics = inspect_locomotion(
        [],
        frames,
        [],
        args,
        shared_idle=True,
        creature_motion={"anatomy": "amorphous", "locomotion": "pulse"},
    )

    assert default_errors
    assert pulse_errors == []
    assert pulse_metrics["threshold_policy"] == "amorphous-pulse"
    assert pulse_metrics["min_average_lower_diff"] == 0.05


def test_action_peak_extent_uses_full_bbox_area_for_wide_creatures() -> None:
    metrics = [
        {"width": 0.9, "height": 0.4, "center_x": 0.5, "center_y": 0.5, "alpha_area": 100},
        {"width": 0.9, "height": 0.5, "center_x": 0.5, "center_y": 0.48, "alpha_area": 120},
        {"width": 0.9, "height": 0.65, "center_x": 0.5, "center_y": 0.45, "alpha_area": 150},
        {"width": 0.9, "height": 0.4, "center_x": 0.5, "center_y": 0.5, "alpha_area": 100},
    ]
    args = SimpleNamespace(min_action_motion_range=0.045, min_action_pair_diff=0.055)

    _, warnings, action_metrics = inspect_action(
        ["front-fps-creature-attack"], metrics, [0.2, 0.3, 0.4], args
    )

    assert action_metrics["peak_extent_frame"] == 3
    assert not any("strongest extent" in warning for warning in warnings)


def test_action_visual_diff_detects_internal_mouth_change_with_static_silhouette() -> None:
    idle = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    active = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    for frame in (idle, active):
        ImageDraw.Draw(frame).ellipse((8, 8, 56, 56), fill=(90, 90, 90, 255))
    ImageDraw.Draw(idle).ellipse((27, 27, 37, 37), fill=(20, 20, 20, 255))
    ImageDraw.Draw(active).ellipse((24, 20, 40, 44), fill=(210, 210, 210, 255))

    visual_diff = normalized_visual_pair_diff(idle, active)

    assert visual_diff > 0.003


def test_source_foreground_recovery_restores_black_torso_not_matte_hole() -> None:
    source = Image.new("RGBA", (64, 64), (128, 128, 128, 255))
    source_draw = ImageDraw.Draw(source)
    source_draw.rectangle((8, 8, 30, 42), fill=(18, 18, 20, 255))
    source_draw.rectangle((38, 8, 58, 42), fill=(128, 128, 128, 255))
    cutout = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    cutout_draw = ImageDraw.Draw(cutout)
    cutout_draw.rectangle((7, 7, 31, 43), outline=(40, 40, 42, 255), width=2)
    cutout_draw.rectangle((37, 7, 59, 43), outline=(40, 40, 42, 255), width=2)

    restored, count = restore_source_foreground_regions(
        source,
        cutout,
        [(128, 128, 128)],
        min_source_pixels=32,
    )

    assert count > 400
    assert restored.getpixel((18, 20)) == (18, 18, 20, 255)
    assert restored.getpixel((48, 20))[3] == 0


def test_source_foreground_recovery_handles_black_void_open_between_horns() -> None:
    source = Image.new("RGBA", (64, 64), (128, 128, 128, 255))
    source_draw = ImageDraw.Draw(source)
    source_draw.polygon(
        [(16, 0), (24, 18), (40, 18), (48, 0), (48, 52), (16, 52)],
        fill=(12, 12, 14, 255),
    )
    cutout = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    cutout_draw = ImageDraw.Draw(cutout)
    cutout_draw.line([(16, 0), (24, 18), (16, 52)], fill=(30, 30, 32, 255), width=3)
    cutout_draw.line([(48, 0), (40, 18), (48, 52)], fill=(30, 30, 32, 255), width=3)

    restored, count = restore_source_foreground_regions(
        source,
        cutout,
        [(128, 128, 128)],
        min_source_pixels=32,
    )

    assert count > 600
    assert restored.getpixel((32, 24)) == (12, 12, 14, 255)


def test_source_foreground_recovery_accepts_separate_void_bounded_by_model() -> None:
    source = Image.new("RGBA", (64, 64), (128, 128, 128, 255))
    source_draw = ImageDraw.Draw(source)
    source_draw.rectangle((22, 16, 42, 46), fill=(8, 8, 10, 255))
    source_draw.rectangle((17, 11, 47, 51), outline=(42, 42, 44, 255), width=2)
    cutout = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    ImageDraw.Draw(cutout).rectangle(
        (17, 11, 47, 51), outline=(42, 42, 44, 255), width=2
    )

    restored, count = restore_source_foreground_regions(
        source,
        cutout,
        [(128, 128, 128)],
        min_source_pixels=32,
    )

    assert count > 500
    assert restored.getpixel((32, 30)) == (8, 8, 10, 255)


def test_source_foreground_recovery_can_retain_a_reviewed_separate_appendage() -> None:
    source = Image.new("RGBA", (96, 64), (0, 0, 0, 255))
    source_draw = ImageDraw.Draw(source)
    source_draw.rectangle((34, 16, 60, 52), fill=(90, 100, 112, 255))
    source_draw.rectangle((3, 8, 15, 20), fill=(180, 190, 204, 255))
    cutout = Image.new("RGBA", (96, 64), (0, 0, 0, 0))
    cutout_draw = ImageDraw.Draw(cutout)
    cutout_draw.rectangle((34, 16, 60, 52), fill=(90, 100, 112, 255))
    cutout_draw.point((0, 63), fill=(1, 1, 1, 255))
    cutout_draw.point((95, 0), fill=(1, 1, 1, 255))

    default_restored, default_count = restore_source_foreground_regions(
        source,
        cutout,
        [(0, 0, 0)],
        min_source_pixels=16,
    )
    reviewed_restored, reviewed_count = restore_source_foreground_regions(
        source,
        cutout,
        [(0, 0, 0)],
        min_source_pixels=16,
        near_radius=24,
    )

    assert default_count == 0
    assert default_restored.getpixel((10, 12))[3] == 0
    assert reviewed_count > 150
    assert reviewed_restored.getpixel((10, 12)) == (180, 190, 204, 255)

    detached_restored, detached_count = restore_source_foreground_regions(
        source,
        cutout,
        [(0, 0, 0)],
        min_source_pixels=16,
        accept_detached=True,
    )
    assert detached_count > 150
    assert detached_restored.getpixel((10, 12)) == (180, 190, 204, 255)


def test_exact_idle_copy_pairs_require_shared_idle_and_identical_source_cells() -> None:
    grid = Image.new("RGBA", (16, 16), (128, 128, 128, 255))
    draw = ImageDraw.Draw(grid)
    draw.rectangle((1, 1, 6, 6), fill=(20, 20, 20, 255))
    draw.rectangle((9, 9, 14, 14), fill=(20, 20, 20, 255))

    assert exact_idle_copy_pairs(
        grid,
        state="attack",
        frame_count=4,
        columns=2,
        rows=2,
        shared_idle=True,
    ) == [(0, 3)]
    assert exact_idle_copy_pairs(
        grid,
        state="attack",
        frame_count=4,
        columns=2,
        rows=2,
        shared_idle=False,
    ) == []
    draw.point((15, 15), fill=(30, 30, 30, 255))
    assert exact_idle_copy_pairs(
        grid,
        state="attack",
        frame_count=4,
        columns=2,
        rows=2,
        shared_idle=True,
    ) == []


def test_identity_fails_when_manifest_is_missing_and_zero_rows_are_checked(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    result = _run("check_identity_consistency.py", "--run-dir", str(run_dir))

    assert result.returncode != 0
    report = json.loads((run_dir / "qa" / "identity-consistency-report.json").read_text())
    assert report["ok"] is False
    assert report["results"] == []
    assert report["errors"]


def test_identity_inflation_and_excessive_spread_block_by_default(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    (run_dir / "frames").mkdir(parents=True)
    (run_dir / "sprite-request.json").write_text(
        json.dumps({"states": {"idle": {"frames": 2, "fps": 2}}}),
        encoding="utf-8",
    )
    records = [
        {
            "head_width_vs_reference": value,
            "upper_width_vs_reference": value,
            "body_mass_width_80_vs_reference": value,
            "opaque_area_vs_reference": value,
        }
        for value in (1.0, 2.0)
    ]
    (run_dir / "frames" / "frames-manifest.json").write_text(
        json.dumps(
            {
                "ok": True,
                "rows": [{"state": "idle", "frame_records": records}],
            }
        ),
        encoding="utf-8",
    )

    result = _run("check_identity_consistency.py", "--run-dir", str(run_dir))

    assert result.returncode == 1
    report = json.loads(
        (run_dir / "qa" / "identity-consistency-report.json").read_text()
    )
    assert any("grows" in error for error in report["errors"])
    assert any("varies" in error for error in report["errors"])


def test_identity_allows_pose_width_change_when_head_and_upper_body_stay_stable(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    (run_dir / "frames").mkdir(parents=True)
    (run_dir / "sprite-request.json").write_text(
        json.dumps({"states": {"poses": {"frames": 2, "fps": 1}}}),
        encoding="utf-8",
    )
    records = [
        {
            "head_width_vs_reference": 1.0,
            "upper_width_vs_reference": 1.0,
            "body_mass_width_80_vs_reference": body_width,
            "opaque_area_vs_reference": 1.0,
        }
        for body_width in (0.85, 1.36)
    ]
    (run_dir / "frames" / "frames-manifest.json").write_text(
        json.dumps({"ok": True, "rows": [{"state": "poses", "frame_records": records}]}),
        encoding="utf-8",
    )

    result = _run("check_identity_consistency.py", "--run-dir", str(run_dir))

    assert result.returncode == 0, result.stdout + result.stderr


def test_identity_uses_visual_review_for_front_quadruped_head_proxy(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "front-quadruped"
    (run_dir / "frames").mkdir(parents=True)
    (run_dir / "sprite-request.json").write_text(
        json.dumps(
            {
                "creature_motion": {
                    "anatomy": "quadruped",
                    "attack_source": "mouth and front limbs",
                },
                "states": {"idle-step": {"frames": 4, "fps": 8}},
            }
        ),
        encoding="utf-8",
    )
    records = [
        {
            "head_width_vs_reference": head_width,
            "upper_width_vs_reference": 1.0,
            "body_mass_width_80_vs_reference": 1.0,
            "opaque_area_vs_reference": 1.0,
        }
        for head_width in (1.0, 0.69, 1.0, 0.71)
    ]
    (run_dir / "frames" / "frames-manifest.json").write_text(
        json.dumps(
            {
                "ok": True,
                "sprite_registration": {
                    "reference_body_mass_width_80": 100,
                    "reference_head_width": 30,
                    "reference_upper_width": 60,
                },
                "rows": [{"state": "idle-step", "frame_records": records}],
            }
        ),
        encoding="utf-8",
    )

    result = _run("check_identity_consistency.py", "--run-dir", str(run_dir))

    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(
        (run_dir / "qa" / "identity-consistency-report.json").read_text()
    )
    assert report["unreliable_proxies"] == ["head_width_vs_reference"]
    assert report["results"][0]["metrics"]["head_width_vs_reference"]["reliable"] is False


def test_identity_allows_declared_arm_attack_width_without_relaxing_other_rows(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "arm-attack"
    (run_dir / "frames").mkdir(parents=True)
    request = {
        "creature_motion": {"attack_source": "mouth and both forward attack limbs"},
        "states": {"attack": {"frames": 4, "fps": 10}},
    }
    (run_dir / "sprite-request.json").write_text(
        json.dumps(request), encoding="utf-8"
    )
    records = [
        {
            "head_width_vs_reference": 1.0,
            "upper_width_vs_reference": upper_width,
            "body_mass_width_80_vs_reference": body_width,
            "opaque_area_vs_reference": 1.0,
        }
        for upper_width, body_width in zip(
            (1.0, 1.3, 1.45, 1.0),
            (1.0, 1.45, 1.72, 1.0),
            strict=True,
        )
    ]
    (run_dir / "frames" / "frames-manifest.json").write_text(
        json.dumps(
            {"ok": True, "rows": [{"state": "attack", "frame_records": records}]}
        ),
        encoding="utf-8",
    )

    result = _run("check_identity_consistency.py", "--run-dir", str(run_dir))

    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(
        (run_dir / "qa" / "identity-consistency-report.json").read_text()
    )
    upper = report["results"][0]["metrics"]["upper_width_vs_reference"]
    assert upper["spread_policy"] == "declared-appendage-attack"
    assert upper["spread"] == 0.45
    assert upper["ceiling"] == 1.85
    body = report["results"][0]["metrics"]["body_mass_width_80_vs_reference"]
    assert body["spread_policy"] == "declared-appendage-attack"
    assert body["ceiling"] == 1.85


@pytest.mark.parametrize("attack_source", ["both arms and hands", "the exact oversized plant gauntlet"])
def test_identity_allows_raised_appendages_to_cross_the_head_proxy_band(
    tmp_path: Path, attack_source: str,
) -> None:
    run_dir = tmp_path / "raised-appendage-attack"
    (run_dir / "frames").mkdir(parents=True)
    (run_dir / "sprite-request.json").write_text(
        json.dumps(
            {
                "creature_motion": {"attack_source": attack_source},
                "states": {"attack": {"frames": 4, "fps": 10}},
            }
        ),
        encoding="utf-8",
    )
    records = [
        {
            "head_width_vs_reference": head_width,
            "upper_width_vs_reference": 1.0,
            "body_mass_width_80_vs_reference": 1.0,
            "opaque_area_vs_reference": 1.0,
        }
        for head_width in (1.0, 0.76, 1.95, 1.0)
    ]
    (run_dir / "frames" / "frames-manifest.json").write_text(
        json.dumps(
            {"ok": True, "rows": [{"state": "attack", "frame_records": records}]}
        ),
        encoding="utf-8",
    )

    result = _run("check_identity_consistency.py", "--run-dir", str(run_dir))

    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(
        (run_dir / "qa" / "identity-consistency-report.json").read_text()
    )
    head = report["results"][0]["metrics"]["head_width_vs_reference"]
    assert head["floor"] == 0.40
    assert head["ceiling"] == 2.20
    assert head["spread_policy"] == "declared-appendage-attack"


def test_identity_allows_declared_mouth_attack_head_change(tmp_path: Path) -> None:
    run_dir = tmp_path / "mouth-attack"
    (run_dir / "frames").mkdir(parents=True)
    (run_dir / "sprite-request.json").write_text(
        json.dumps(
            {
                "creature_motion": {
                    "attack_source": "both hands, claws, and open mouth"
                },
                "states": {"attack": {"frames": 4, "fps": 10}},
            }
        ),
        encoding="utf-8",
    )
    records = [
        {
            "head_width_vs_reference": head_width,
            "upper_width_vs_reference": upper_width,
            "body_mass_width_80_vs_reference": 1.0,
            "opaque_area_vs_reference": 1.0,
        }
        for head_width, upper_width in zip(
            (1.0, 0.88, 1.32, 1.0),
            (1.0, 1.25, 1.91, 1.0),
            strict=True,
        )
    ]
    (run_dir / "frames" / "frames-manifest.json").write_text(
        json.dumps(
            {"ok": True, "rows": [{"state": "attack", "frame_records": records}]}
        ),
        encoding="utf-8",
    )

    result = _run("check_identity_consistency.py", "--run-dir", str(run_dir))

    assert result.returncode == 1, result.stdout + result.stderr
    report = json.loads(
        (run_dir / "qa" / "identity-consistency-report.json").read_text()
    )
    head = report["results"][0]["metrics"]["head_width_vs_reference"]
    assert head["spread_policy"] == "declared-head-attack"
    assert head["ceiling"] == 1.40
    assert head["spread"] == 0.44
    assert report["errors"] == [
        "attack: upper_width_vs_reference grows to 1.91x reference; expected <= 1.85x"
    ]


def test_identity_uses_narrow_airborne_head_tolerance(tmp_path: Path) -> None:
    run_dir = tmp_path / "airborne-hover"
    (run_dir / "frames").mkdir(parents=True)
    (run_dir / "sprite-request.json").write_text(
        json.dumps(
            {
                "creature_motion": {"anatomy": "hovering", "locomotion": "hover"},
                "states": {"idle-step": {"frames": 4, "fps": 8}},
            }
        ),
        encoding="utf-8",
    )
    records = [
        {
            "head_width_vs_reference": head_width,
            "upper_width_vs_reference": 1.0,
            "body_mass_width_80_vs_reference": 1.0,
            "opaque_area_vs_reference": 1.0,
        }
        for head_width in (1.0, 0.81, 1.0, 0.81)
    ]
    (run_dir / "frames" / "frames-manifest.json").write_text(
        json.dumps(
            {
                "ok": True,
                "rows": [
                    {
                        "state": "idle-step",
                        "frame_records": records,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = _run("check_identity_consistency.py", "--run-dir", str(run_dir))

    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(
        (run_dir / "qa" / "identity-consistency-report.json").read_text()
    )
    head = report["results"][0]["metrics"]["head_width_vs_reference"]
    assert head["floor"] == 0.80


def test_identity_uses_visual_review_for_fixed_scale_wing_flap_widths(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "fixed-scale-wing-flap"
    (run_dir / "frames").mkdir(parents=True)
    (run_dir / "sprite-request.json").write_text(
        json.dumps(
            {
                "creature_motion": {"anatomy": "winged", "locomotion": "fly"},
                "registration": {"scale_policy": "source-reference"},
                "states": {"idle-step": {"frames": 4, "fps": 8}},
            }
        ),
        encoding="utf-8",
    )
    records = [
        {
            "head_width_vs_reference": 1.0,
            "upper_width_vs_reference": upper_width,
            "body_mass_width_80_vs_reference": body_width,
            "opaque_area_vs_reference": 1.0,
        }
        for upper_width, body_width in zip(
            (1.0, 1.68, 1.0, 1.65),
            (1.0, 0.63, 1.0, 0.64),
            strict=True,
        )
    ]
    (run_dir / "frames" / "frames-manifest.json").write_text(
        json.dumps(
            {
                "ok": True,
                "sprite_registration": {
                    "reference_head_width": 30,
                    "reference_upper_width": 100,
                    "reference_body_mass_width_80": 200,
                },
                "rows": [{"state": "idle-step", "frame_records": records}],
            }
        ),
        encoding="utf-8",
    )

    result = _run("check_identity_consistency.py", "--run-dir", str(run_dir))

    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(
        (run_dir / "qa" / "identity-consistency-report.json").read_text()
    )
    assert report["unreliable_proxies"] == [
        "body_mass_width_80_vs_reference",
        "upper_width_vs_reference",
    ]
    assert report["results"][0]["metrics"]["upper_width_vs_reference"]["reliable"] is False
    assert report["results"][0]["metrics"]["body_mass_width_80_vs_reference"]["reliable"] is False


def test_identity_uses_visual_review_for_declared_long_arm_counter_swing(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "long-arm-counter-swing"
    (run_dir / "frames").mkdir(parents=True)
    (run_dir / "sprite-request.json").write_text(
        json.dumps(
            {
                "creature_motion": {
                    "anatomy": "biped",
                    "movement_source": "restrained long-arm counter-swing",
                },
                "states": {"idle-step": {"frames": 4, "fps": 8}},
            }
        ),
        encoding="utf-8",
    )
    records = [
        {
            "head_width_vs_reference": 1.0,
            "upper_width_vs_reference": width,
            "body_mass_width_80_vs_reference": 1.0,
            "opaque_area_vs_reference": 1.0,
        }
        for width in (1.0, 1.44, 1.0, 1.38)
    ]
    (run_dir / "frames" / "frames-manifest.json").write_text(
        json.dumps(
            {
                "ok": True,
                "sprite_registration": {
                    "reference_head_width": 40,
                    "reference_upper_width": 100,
                    "reference_body_mass_width_80": 200,
                },
                "rows": [{"state": "idle-step", "frame_records": records}],
            }
        ),
        encoding="utf-8",
    )

    result = _run("check_identity_consistency.py", "--run-dir", str(run_dir))

    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(
        (run_dir / "qa" / "identity-consistency-report.json").read_text()
    )
    assert report["unreliable_proxies"] == ["upper_width_vs_reference"]
    upper = report["results"][0]["metrics"]["upper_width_vs_reference"]
    assert upper["reliable"] is False


def test_identity_allows_declared_wing_attack_width(tmp_path: Path) -> None:
    run_dir = tmp_path / "wing-attack"
    (run_dir / "frames").mkdir(parents=True)
    (run_dir / "sprite-request.json").write_text(
        json.dumps(
            {
                "creature_motion": {"attack_source": "both hooked wing tips"},
                "states": {"attack": {"frames": 4, "fps": 10}},
            }
        ),
        encoding="utf-8",
    )
    records = [
        {
            "head_width_vs_reference": 1.0,
            "upper_width_vs_reference": upper_width,
            "body_mass_width_80_vs_reference": body_width,
            "opaque_area_vs_reference": 1.0,
        }
        for upper_width, body_width in zip(
            (1.0, 1.2, 1.4, 1.0),
            (0.92, 1.25, 1.66, 0.92),
            strict=True,
        )
    ]
    (run_dir / "frames" / "frames-manifest.json").write_text(
        json.dumps(
            {"ok": True, "rows": [{"state": "attack", "frame_records": records}]}
        ),
        encoding="utf-8",
    )

    result = _run("check_identity_consistency.py", "--run-dir", str(run_dir))

    assert result.returncode == 0, result.stdout + result.stderr


def test_animation_gate_rejects_unknown_explicit_workflow(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    (run_dir / "frames").mkdir(parents=True)
    request = {
        "asset_kind": "sprite",
        "frame_semantics": "animation",
        "states": {
            "idle": {
                "frames": 2,
                "fps": 4,
                "loop": True,
                "animation_workflows": ["typo-workflow"],
            }
        },
    }
    (run_dir / "sprite-request.json").write_text(json.dumps(request), encoding="utf-8")
    (run_dir / "frames" / "frames-manifest.json").write_text(
        json.dumps({"ok": True, "rows": [{"state": "idle", "files": []}]}),
        encoding="utf-8",
    )

    result = _run("check_animation_contracts.py", "--run-dir", str(run_dir))

    assert result.returncode != 0
    report = json.loads((run_dir / "qa" / "animation-contract-report.json").read_text())
    assert report["ok"] is False
    assert any("typo-workflow" in error for error in report["errors"])


def test_static_variants_do_not_infer_temporal_workflow_from_nouns() -> None:
    request = {
        "asset_kind": "asset",
        "frame_semantics": "variants",
        "cell": {"width": 32, "height": 32},
    }
    entry = {
        "frames": 4,
        "fps": 1,
        "loop": False,
        "action": "water grass fabric material variants",
    }

    assert infer_workflows(request, "nature-materials", entry) == []


def test_character_wave_infers_gesture_loop_not_water_loop() -> None:
    request = {
        "asset_kind": "sprite",
        "frame_semantics": "animation",
        "cell": {"width": 192, "height": 192},
    }
    entry = {
        "frames": 6,
        "fps": 6,
        "loop": True,
        "action": "planted friendly hand wave loop",
    }

    assert infer_workflows(request, "wave", entry) == ["gesture-loop"]


def _write_gesture_run(run_dir: Path, *, drifting_lower_body: bool) -> None:
    (run_dir / "frames" / "wave").mkdir(parents=True)
    request = {
        "asset_kind": "sprite",
        "frame_semantics": "animation",
        "cell": {"width": 64, "height": 64},
        "states": {
            "wave": {
                "frames": 6,
                "fps": 6,
                "loop": True,
                "action": "planted friendly wave loop",
                "animation_workflows": ["gesture-loop"],
            }
        },
    }
    (run_dir / "sprite-request.json").write_text(
        json.dumps(request), encoding="utf-8"
    )
    files = []
    arm_tips = [(46, 30), (51, 24), (53, 16), (49, 12), (46, 20), (46, 30)]
    for index, arm_tip in enumerate(arm_tips):
        frame = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(frame)
        draw.ellipse((22, 8, 42, 28), fill=(150, 220, 30, 255))
        draw.rectangle((25, 27, 39, 43), fill=(140, 210, 25, 255))
        draw.line((37, 29, *arm_tip), fill=(140, 210, 25, 255), width=5)
        lower_shift = 8 if drifting_lower_body and index in {2, 3, 4} else 0
        draw.rectangle((26 + lower_shift, 41, 31 + lower_shift, 57), fill=(130, 195, 20, 255))
        draw.rectangle((34 + lower_shift, 41, 39 + lower_shift, 57), fill=(130, 195, 20, 255))
        draw.rectangle((23 + lower_shift, 55, 31 + lower_shift, 59), fill=(130, 195, 20, 255))
        draw.rectangle((34 + lower_shift, 55, 42 + lower_shift, 59), fill=(130, 195, 20, 255))
        path = run_dir / "frames" / "wave" / f"frame-{index}.png"
        frame.save(path)
        files.append(path.relative_to(run_dir).as_posix())
    (run_dir / "frames" / "frames-manifest.json").write_text(
        json.dumps({"ok": True, "rows": [{"state": "wave", "files": files}]}),
        encoding="utf-8",
    )


def test_gesture_contract_passes_when_only_the_upper_limb_moves(tmp_path: Path) -> None:
    run_dir = tmp_path / "planted"
    _write_gesture_run(run_dir, drifting_lower_body=False)

    result = _run("check_animation_contracts.py", "--run-dir", str(run_dir))

    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads((run_dir / "qa" / "animation-contract-report.json").read_text())
    planted = report["results"][0]["metrics"]["gesture_planted_lower_body"]
    assert planted["ok"] is True
    assert planted["max_anchor_diff"] == 0.0
    assert planted["lower_center_x_range"] == 0.0


def test_gesture_contract_rejects_leg_and_contact_footprint_drift(tmp_path: Path) -> None:
    run_dir = tmp_path / "drifting"
    _write_gesture_run(run_dir, drifting_lower_body=True)

    result = _run("check_animation_contracts.py", "--run-dir", str(run_dir))

    assert result.returncode == 1, result.stdout + result.stderr
    report = json.loads((run_dir / "qa" / "animation-contract-report.json").read_text())
    assert any("lower body" in error.lower() for error in report["errors"])
    planted = report["results"][0]["metrics"]["gesture_planted_lower_body"]
    assert planted["ok"] is False
    assert planted["lower_center_x_range"] > planted["max_center_x_range"]


def test_environment_wave_still_infers_water_loop() -> None:
    request = {
        "asset_kind": "vfx",
        "frame_semantics": "effects",
        "cell": {"width": 64, "height": 64},
    }
    entry = {
        "frames": 6,
        "fps": 8,
        "loop": True,
        "action": "ocean wave surface loop",
    }

    assert infer_workflows(request, "wave", entry) == [
        "vfx-buildup-peak-decay",
        "water-loop",
    ]


def test_auto_import_is_blocked_for_production_but_explicit_diagnostic_can_succeed(
    tmp_path: Path,
) -> None:
    atlas = tmp_path / "atlas.png"
    image = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    for y in range(4, 12):
        for x in range(4, 12):
            image.putpixel((x, y), (230, 70, 70, 255))
    image.save(atlas)

    production = _run(
        "unpack_atlas_run.py",
        "--atlas",
        str(atlas),
        "--out-dir",
        str(tmp_path / "production"),
        "--states",
        "idle",
    )
    diagnostic = _run(
        "unpack_atlas_run.py",
        "--atlas",
        str(atlas),
        "--out-dir",
        str(tmp_path / "diagnostic"),
        "--states",
        "idle",
        "--diagnostic",
    )

    assert production.returncode != 0
    assert diagnostic.returncode == 0, diagnostic.stderr
    report = json.loads(
        (tmp_path / "diagnostic" / "qa" / "segmentation-report.json").read_text()
    )
    assert report["diagnostic"] is True
    assert report["production_eligible"] is False
