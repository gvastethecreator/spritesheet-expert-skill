from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from PIL import Image, ImageDraw

from check_animation_contracts import infer_workflows


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
