from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from PIL import Image


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "SKILLS" / "spritesheet-expert" / "scripts"


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _run_check(script: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / script), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _write_opaque_box(path: Path, *, size: int = 16) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    for y in range(2, size - 2):
        for x in range(2, size - 2):
            image.putpixel((x, y), (80, 140, 220, 255))
    image.save(path)


def _write_iso_tile(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    for y in range(4, 12):
        for x in range(16):
            image.putpixel((x, y), (80, 140, 100, 255))
    image.save(path)


def _isometric_request() -> dict:
    items = {
        "grass-flat": {
            "category": "terrain",
            "tile_role": "base",
            "collision": "walkable",
            "pivot": [8, 12],
        },
        **{
            f"{edge}-edge": {
                "category": "terrain",
                "edge_role": edge,
                "collision": "ledge",
                "pivot": [8, 12],
            }
            for edge in ("north", "south", "east", "west")
        },
        "outer-corner": {
            "category": "terrain",
            "edge_role": "outer-corner",
            "collision": "ledge",
            "pivot": [8, 12],
        },
    }
    return {
        "asset_kind": "tileset",
        "cell": {"width": 16, "height": 16},
        "states": {},
        "asset_catalog": {
            "projection": "2:1 isometric",
            "tile": {"width": 16, "height": 8, "runtimeCell": [16, 16]},
            "items": items,
        },
    }


def test_motion_warn_only_does_not_waive_an_unknown_state_selector(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    _write_json(
        run_dir / "sprite-request.json",
        {
            "states": {
                "idle": {"frames": 1, "fps": 1, "loop": True},
            },
        },
    )
    _write_json(
        run_dir / "frames" / "frames-manifest.json",
        {
            "ok": True,
            "rows": [{"state": "idle", "files": []}],
        },
    )

    result = _run_check(
        "check_motion_variation.py",
        "--run-dir",
        str(run_dir),
        "--states",
        "ghost",
        "--warn-only",
    )

    assert result.returncode != 0, result.stdout + result.stderr
    report = json.loads(
        (run_dir / "qa" / "motion-variation-report.json").read_text(encoding="utf-8")
    )
    assert report["ok"] is False
    assert "unknown state: ghost" in report["errors"]


def test_motion_fails_when_the_expected_locomotion_selector_checks_zero_states(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    _write_json(
        run_dir / "sprite-request.json",
        {
            "states": {
                "idle": {"frames": 1, "fps": 1, "loop": True, "action": "idle"},
            },
        },
    )
    _write_json(
        run_dir / "frames" / "frames-manifest.json",
        {
            "ok": True,
            "rows": [{"state": "idle", "files": []}],
        },
    )

    result = _run_check(
        "check_motion_variation.py",
        "--run-dir",
        str(run_dir),
        "--states",
        "locomotion",
        "--warn-only",
    )

    assert result.returncode != 0, result.stdout + result.stderr
    report = json.loads(
        (run_dir / "qa" / "motion-variation-report.json").read_text(encoding="utf-8")
    )
    assert report["checked_states"] == []
    assert any("nothing checked" in message for message in report["errors"])


def test_motion_all_selector_fails_when_zero_states_are_checked(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _write_json(run_dir / "sprite-request.json", {"states": {}})
    _write_json(
        run_dir / "frames" / "frames-manifest.json",
        {"ok": True, "rows": []},
    )

    result = _run_check(
        "check_motion_variation.py",
        "--run-dir",
        str(run_dir),
        "--states",
        "all",
        "--warn-only",
    )

    assert result.returncode != 0, result.stdout + result.stderr
    report = json.loads(
        (run_dir / "qa" / "motion-variation-report.json").read_text(encoding="utf-8")
    )
    assert any("nothing checked" in message for message in report["errors"])


def test_motion_warn_only_does_not_waive_missing_expected_frames(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _write_json(
        run_dir / "sprite-request.json",
        {
            "states": {
                "run": {"frames": 4, "fps": 8, "loop": True, "action": "run"},
            },
        },
    )
    _write_json(
        run_dir / "frames" / "frames-manifest.json",
        {"ok": True, "rows": []},
    )

    result = _run_check(
        "check_motion_variation.py",
        "--run-dir",
        str(run_dir),
        "--states",
        "run",
        "--warn-only",
    )

    assert result.returncode != 0, result.stdout + result.stderr
    report = json.loads(
        (run_dir / "qa" / "motion-variation-report.json").read_text(encoding="utf-8")
    )
    assert any("missing extracted frames" in message for message in report["errors"])


def test_motion_warn_only_does_not_waive_an_incomplete_expected_frame_set(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    _write_json(
        run_dir / "sprite-request.json",
        {
            "states": {
                "run": {"frames": 4, "fps": 8, "loop": True, "action": "run"},
            },
        },
    )
    _write_json(
        run_dir / "frames" / "frames-manifest.json",
        {"ok": True, "rows": [{"state": "run", "files": []}]},
    )

    result = _run_check(
        "check_motion_variation.py",
        "--run-dir",
        str(run_dir),
        "--states",
        "run",
        "--warn-only",
    )

    assert result.returncode != 0, result.stdout + result.stderr
    report = json.loads(
        (run_dir / "qa" / "motion-variation-report.json").read_text(encoding="utf-8")
    )
    assert any("expected 4 frames" in message for message in report["errors"])


def test_motion_warn_only_does_not_waive_a_malformed_frame_contract(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    _write_json(
        run_dir / "sprite-request.json",
        {
            "states": {
                "run": {"frames": "four", "fps": 8, "loop": True, "action": "run"},
            },
        },
    )
    _write_json(
        run_dir / "frames" / "frames-manifest.json",
        {"ok": True, "rows": [{"state": "run", "files": []}]},
    )

    result = _run_check(
        "check_motion_variation.py",
        "--run-dir",
        str(run_dir),
        "--states",
        "run",
        "--warn-only",
    )

    assert result.returncode != 0, result.stdout + result.stderr
    report = json.loads(
        (run_dir / "qa" / "motion-variation-report.json").read_text(encoding="utf-8")
    )
    assert any("positive integer" in message for message in report["errors"])


def test_motion_warn_only_still_waives_only_heuristic_failures(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    files = []
    for index in range(4):
        frame = run_dir / "frames" / "run" / f"frame-{index}.png"
        _write_opaque_box(frame)
        files.append(str(frame.relative_to(run_dir)))
    _write_json(
        run_dir / "sprite-request.json",
        {
            "states": {
                "run": {"frames": 4, "fps": 8, "loop": True, "action": "run"},
            },
        },
    )
    _write_json(
        run_dir / "frames" / "frames-manifest.json",
        {"ok": True, "rows": [{"state": "run", "files": files}]},
    )

    result = _run_check(
        "check_motion_variation.py",
        "--run-dir",
        str(run_dir),
        "--states",
        "run",
        "--warn-only",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(
        (run_dir / "qa" / "motion-variation-report.json").read_text(encoding="utf-8")
    )
    assert report["ok"] is True
    assert report["checked_states"] == ["run"]
    assert report["errors"]


def test_motion_warn_only_does_not_waive_a_failed_frames_manifest(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    _write_json(
        run_dir / "sprite-request.json",
        {
            "states": {
                "run": {"frames": 4, "fps": 8, "loop": True, "action": "run"},
            },
        },
    )
    _write_json(
        run_dir / "frames" / "frames-manifest.json",
        {"ok": False, "rows": []},
    )

    result = _run_check(
        "check_motion_variation.py",
        "--run-dir",
        str(run_dir),
        "--warn-only",
    )

    assert result.returncode != 0
    assert "frames-manifest.json is not ok" in (result.stdout + result.stderr)


def test_run_directory_checks_fail_for_missing_and_malformed_prerequisites(
    tmp_path: Path,
) -> None:
    scripts = (
        "check_motion_variation.py",
        "check_asset_slots.py",
        "check_isometric_tiles.py",
    )
    for script in scripts:
        missing_run = tmp_path / f"missing-{script}"
        missing_result = _run_check(script, "--run-dir", str(missing_run))
        assert missing_result.returncode != 0, script

        malformed_run = tmp_path / f"malformed-{script}"
        malformed_run.mkdir()
        (malformed_run / "sprite-request.json").write_text("{", encoding="utf-8")
        malformed_result = _run_check(script, "--run-dir", str(malformed_run))
        assert malformed_result.returncode != 0, script


def test_asset_slots_rejects_an_upstream_frames_manifest_marked_not_ok(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    frame = run_dir / "frames" / "props" / "frame-0.png"
    _write_opaque_box(frame)
    _write_json(
        run_dir / "sprite-request.json",
        {
            "asset_kind": "asset",
            "cell": {"width": 16, "height": 16},
            "states": {"props": {"asset_labels": ["wooden-crate"]}},
            "asset_catalog": {
                "items": {
                    "wooden-crate": {
                        "category": "prop",
                        "pivot": [8, 14],
                        "strategy_class": "compact_prop",
                    }
                }
            },
        },
    )
    _write_json(
        run_dir / "frames" / "frames-manifest.json",
        {
            "ok": False,
            "rows": [
                {
                    "state": "props",
                    "files": [str(frame.relative_to(run_dir))],
                }
            ],
        },
    )

    result = _run_check("check_asset_slots.py", "--run-dir", str(run_dir))

    assert result.returncode != 0, result.stdout + result.stderr
    report = json.loads(
        (run_dir / "qa" / "asset-slot-review.json").read_text(encoding="utf-8")
    )
    assert report["ok"] is False
    assert any("frames-manifest.json" in message for message in report["errors"])


def test_asset_slots_fails_when_expected_catalog_items_are_not_checked(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    _write_json(
        run_dir / "sprite-request.json",
        {
            "asset_kind": "asset",
            "cell": {"width": 16, "height": 16},
            "states": {"props": {"asset_labels": ["wooden-crate"]}},
            "asset_catalog": {
                "items": {
                    "wooden-crate": {
                        "category": "prop",
                        "pivot": [8, 14],
                        "strategy_class": "compact_prop",
                    }
                }
            },
        },
    )
    _write_json(
        run_dir / "frames" / "frames-manifest.json",
        {"ok": True, "rows": []},
    )

    result = _run_check("check_asset_slots.py", "--run-dir", str(run_dir))

    assert result.returncode != 0, result.stdout + result.stderr
    report = json.loads(
        (run_dir / "qa" / "asset-slot-review.json").read_text(encoding="utf-8")
    )
    assert report["records"] == []
    assert any("wooden-crate" in message for message in report["errors"])
    assert any("nothing checked" in message for message in report["errors"])


def test_asset_slots_fails_when_an_expected_request_state_has_no_manifest_row(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    frame = run_dir / "frames" / "props" / "frame-0.png"
    _write_opaque_box(frame)
    _write_json(
        run_dir / "sprite-request.json",
        {
            "asset_kind": "asset",
            "cell": {"width": 16, "height": 16},
            "states": {
                "props": {"asset_labels": ["wooden-crate"]},
                "bonus": {"asset_labels": []},
            },
            "asset_catalog": {
                "items": {
                    "wooden-crate": {
                        "category": "prop",
                        "pivot": [8, 14],
                        "strategy_class": "compact_prop",
                    }
                }
            },
        },
    )
    _write_json(
        run_dir / "frames" / "frames-manifest.json",
        {
            "ok": True,
            "rows": [
                {
                    "state": "props",
                    "files": [str(frame.relative_to(run_dir))],
                }
            ],
        },
    )

    result = _run_check("check_asset_slots.py", "--run-dir", str(run_dir))

    assert result.returncode != 0, result.stdout + result.stderr
    report = json.loads(
        (run_dir / "qa" / "asset-slot-review.json").read_text(encoding="utf-8")
    )
    assert any("bonus" in message for message in report["errors"])


def test_asset_slots_rejects_a_request_without_a_states_contract(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    frame = run_dir / "frames" / "props" / "frame-0.png"
    _write_opaque_box(frame)
    _write_json(
        run_dir / "sprite-request.json",
        {
            "asset_kind": "asset",
            "cell": {"width": 16, "height": 16},
            "asset_catalog": {
                "items": {
                    "wooden-crate": {
                        "category": "prop",
                        "pivot": [8, 14],
                        "strategy_class": "compact_prop",
                    }
                }
            },
        },
    )
    _write_json(
        run_dir / "frames" / "frames-manifest.json",
        {
            "ok": True,
            "rows": [
                {
                    "state": "props",
                    "labels": ["wooden-crate"],
                    "files": [str(frame.relative_to(run_dir))],
                }
            ],
        },
    )

    result = _run_check("check_asset_slots.py", "--run-dir", str(run_dir))

    assert result.returncode != 0, result.stdout + result.stderr
    report = json.loads(
        (run_dir / "qa" / "asset-slot-review.json").read_text(encoding="utf-8")
    )
    assert any("states" in message for message in report["errors"])


def test_asset_slots_rejects_a_label_with_a_trailing_newline(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    frame = run_dir / "frames" / "props" / "frame-0.png"
    _write_opaque_box(frame)
    unsafe_label = "wooden-crate\n"
    _write_json(
        run_dir / "sprite-request.json",
        {
            "asset_kind": "asset",
            "cell": {"width": 16, "height": 16},
            "states": {"props": {"asset_labels": [unsafe_label]}},
            "asset_catalog": {
                "items": {
                    unsafe_label: {
                        "category": "prop",
                        "pivot": [8, 14],
                        "strategy_class": "compact_prop",
                    }
                }
            },
        },
    )
    _write_json(
        run_dir / "frames" / "frames-manifest.json",
        {
            "ok": True,
            "rows": [
                {
                    "state": "props",
                    "files": [str(frame.relative_to(run_dir))],
                }
            ],
        },
    )

    result = _run_check("check_asset_slots.py", "--run-dir", str(run_dir))

    assert result.returncode != 0, result.stdout + result.stderr
    report = json.loads(
        (run_dir / "qa" / "asset-slot-review.json").read_text(encoding="utf-8")
    )
    assert any("kebab-case" in message for message in report["errors"])


def test_isometric_tiles_rejects_an_upstream_frames_manifest_marked_not_ok(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    _write_json(run_dir / "sprite-request.json", _isometric_request())
    _write_json(run_dir / "manifest.json", {})
    _write_json(
        run_dir / "frames" / "frames-manifest.json",
        {"ok": False, "rows": []},
    )

    result = _run_check("check_isometric_tiles.py", "--run-dir", str(run_dir))

    assert result.returncode != 0, result.stdout + result.stderr
    report = json.loads(
        (run_dir / "qa" / "isometric-tile-review.json").read_text(encoding="utf-8")
    )
    assert report["ok"] is False
    assert any("frames-manifest.json" in message for message in report["errors"])


def test_isometric_tiles_rejects_an_upstream_manifest_marked_not_ok(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    _write_json(run_dir / "sprite-request.json", _isometric_request())
    _write_json(run_dir / "manifest.json", {"ok": False})
    _write_json(
        run_dir / "frames" / "frames-manifest.json",
        {"ok": True, "rows": []},
    )

    result = _run_check("check_isometric_tiles.py", "--run-dir", str(run_dir))

    assert result.returncode != 0, result.stdout + result.stderr
    report = json.loads(
        (run_dir / "qa" / "isometric-tile-review.json").read_text(encoding="utf-8")
    )
    assert any("manifest.json" in message for message in report["errors"])


def test_isometric_tiles_rejects_a_missing_runtime_manifest(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _write_json(run_dir / "sprite-request.json", _isometric_request())
    _write_json(
        run_dir / "frames" / "frames-manifest.json",
        {"ok": True, "rows": []},
    )

    result = _run_check("check_isometric_tiles.py", "--run-dir", str(run_dir))

    assert result.returncode != 0, result.stdout + result.stderr
    report = json.loads(
        (run_dir / "qa" / "isometric-tile-review.json").read_text(encoding="utf-8")
    )
    assert any("manifest.json is missing" in message for message in report["errors"])


def test_isometric_tiles_rejects_a_failed_segmentation_report_without_messages(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    _write_json(run_dir / "sprite-request.json", _isometric_request())
    _write_json(run_dir / "manifest.json", {})
    _write_json(
        run_dir / "frames" / "frames-manifest.json",
        {"ok": True, "rows": []},
    )
    _write_json(run_dir / "qa" / "segmentation-report.json", {"ok": False})

    result = _run_check("check_isometric_tiles.py", "--run-dir", str(run_dir))

    assert result.returncode != 0, result.stdout + result.stderr
    report = json.loads(
        (run_dir / "qa" / "isometric-tile-review.json").read_text(encoding="utf-8")
    )
    assert any("segmentation" in message for message in report["errors"])


def test_isometric_tiles_rejects_a_failed_asset_slot_report(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _write_json(run_dir / "sprite-request.json", _isometric_request())
    _write_json(run_dir / "manifest.json", {})
    _write_json(
        run_dir / "frames" / "frames-manifest.json",
        {"ok": True, "rows": []},
    )
    _write_json(run_dir / "qa" / "asset-slot-review.json", {"ok": False})

    result = _run_check("check_isometric_tiles.py", "--run-dir", str(run_dir))

    assert result.returncode != 0, result.stdout + result.stderr
    report = json.loads(
        (run_dir / "qa" / "isometric-tile-review.json").read_text(encoding="utf-8")
    )
    assert any("asset-slot-review" in message for message in report["errors"])


def test_isometric_tiles_fails_when_expected_catalog_items_are_not_checked(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    _write_json(run_dir / "sprite-request.json", _isometric_request())
    _write_json(run_dir / "manifest.json", {})
    _write_json(
        run_dir / "frames" / "frames-manifest.json",
        {"ok": True, "rows": []},
    )

    result = _run_check("check_isometric_tiles.py", "--run-dir", str(run_dir))

    assert result.returncode != 0, result.stdout + result.stderr
    report = json.loads(
        (run_dir / "qa" / "isometric-tile-review.json").read_text(encoding="utf-8")
    )
    assert report["records"] == []
    assert any("nothing checked" in message for message in report["errors"])
    assert any("grass-flat" in message for message in report["errors"])


def test_isometric_tiles_fails_when_an_expected_request_state_has_no_manifest_row(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    request = _isometric_request()
    labels = list(request["asset_catalog"]["items"])
    files = []
    for index, label in enumerate(labels):
        frame = run_dir / "frames" / "terrain" / f"frame-{index}.png"
        _write_iso_tile(frame)
        files.append(str(frame.relative_to(run_dir)))
    request["states"] = {
        "terrain": {"asset_labels": labels},
        "bonus": {"asset_labels": []},
    }
    _write_json(run_dir / "sprite-request.json", request)
    _write_json(run_dir / "manifest.json", {})
    _write_json(
        run_dir / "frames" / "frames-manifest.json",
        {"ok": True, "rows": [{"state": "terrain", "files": files}]},
    )

    result = _run_check("check_isometric_tiles.py", "--run-dir", str(run_dir))

    assert result.returncode != 0, result.stdout + result.stderr
    report = json.loads(
        (run_dir / "qa" / "isometric-tile-review.json").read_text(encoding="utf-8")
    )
    assert any("bonus" in message for message in report["errors"])


def test_isometric_tiles_rejects_a_request_without_a_states_contract(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    request = _isometric_request()
    labels = list(request["asset_catalog"]["items"])
    files = []
    for index, label in enumerate(labels):
        frame = run_dir / "frames" / "terrain" / f"frame-{index}.png"
        _write_iso_tile(frame)
        files.append(str(frame.relative_to(run_dir)))
    _write_json(run_dir / "sprite-request.json", request)
    _write_json(run_dir / "manifest.json", {})
    _write_json(
        run_dir / "frames" / "frames-manifest.json",
        {
            "ok": True,
            "rows": [
                {"state": "terrain", "labels": labels, "files": files},
            ],
        },
    )

    result = _run_check("check_isometric_tiles.py", "--run-dir", str(run_dir))

    assert result.returncode != 0, result.stdout + result.stderr
    report = json.loads(
        (run_dir / "qa" / "isometric-tile-review.json").read_text(encoding="utf-8")
    )
    assert any("states" in message for message in report["errors"])


def test_chroma_key_safety_fails_for_missing_malformed_and_unknown_inputs(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing.png"
    malformed = tmp_path / "malformed.png"
    malformed.write_text("not an image", encoding="utf-8")
    valid = tmp_path / "valid.png"
    _write_opaque_box(valid)

    missing_result = _run_check("check_chroma_key_safety.py", str(missing))
    malformed_result = _run_check("check_chroma_key_safety.py", str(malformed))
    unknown_key_result = _run_check(
        "check_chroma_key_safety.py", str(valid), "--key", "chartreuse"
    )

    assert missing_result.returncode != 0
    assert malformed_result.returncode != 0
    assert unknown_key_result.returncode != 0


def test_chroma_key_safety_fails_when_zero_subject_pixels_are_checked(
    tmp_path: Path,
) -> None:
    transparent = tmp_path / "transparent.png"
    Image.new("RGBA", (8, 8), (0, 0, 0, 0)).save(transparent)

    result = _run_check("check_chroma_key_safety.py", str(transparent))

    assert result.returncode != 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["ok"] is False
    assert report["results"][0]["subject_pixels"] == 0


def test_visible_magenta_fails_for_missing_and_malformed_images(tmp_path: Path) -> None:
    missing = tmp_path / "missing.png"
    malformed = tmp_path / "malformed.png"
    malformed.write_text("not an image", encoding="utf-8")

    missing_result = _run_check(
        "check_visible_magenta.py", "--image", str(missing)
    )
    malformed_result = _run_check(
        "check_visible_magenta.py", "--image", str(malformed)
    )

    assert missing_result.returncode != 0
    assert malformed_result.returncode != 0


def test_visible_magenta_preserves_the_pixel_threshold_gate(tmp_path: Path) -> None:
    magenta = tmp_path / "magenta.png"
    safe = tmp_path / "safe.png"
    Image.new("RGBA", (16, 16), (255, 0, 255, 255)).save(magenta)
    Image.new("RGBA", (16, 16), (40, 120, 220, 255)).save(safe)

    failed = _run_check("check_visible_magenta.py", "--image", str(magenta))
    passed = _run_check("check_visible_magenta.py", "--image", str(safe))

    assert failed.returncode != 0
    assert "status=fail" in failed.stdout
    assert passed.returncode == 0, passed.stdout + passed.stderr
    assert "status=pass" in passed.stdout
