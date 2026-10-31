from __future__ import annotations

from argparse import Namespace
from pathlib import Path

from PIL import Image

import extract_sprite_row_frames as backgrounds


def _args() -> Namespace:
    return Namespace(
        background_removal="request",
        background_model=None,
        background_device=None,
        alpha_matting=None,
        post_rembg_chroma_cleanup=None,
        key_threshold=30.0,
        fringe_key_threshold=90.0,
        fringe_delta=18.0,
        matte_threshold=28.0,
        matte_max_colors=8,
        edge_refine="off",
        edge_refine_threshold=36.0,
        edge_refine_feather=36.0,
        edge_refine_passes=1,
    )


def _flat_source(background: tuple[int, int, int]) -> Image.Image:
    image = Image.new("RGBA", (24, 24), (*background, 255))
    for y in range(7, 19):
        for x in range(8, 16):
            image.putpixel((x, y), (220, 70, 40, 255))
    return image


def test_default_models_are_stable_and_lucida_is_revision_pinned() -> None:
    assert backgrounds.DEFAULT_REMBG_MODEL == "birefnet-general"
    assert backgrounds.default_background_model("auto") == "birefnet-general"
    assert backgrounds.default_background_model("lucida") == "egeorcun/lucida"
    assert backgrounds.default_background_revision("lucida") == (
        "6ee11122534c8de59402a589d2293c198cfbf848"
    )


def test_auto_neutral_sources_never_enter_the_legacy_chroma_branch() -> None:
    config = {
        "method": "auto",
        "model": "birefnet-general",
        "source_family": "neutral",
        "post_rembg_chroma_cleanup": False,
    }

    _cutout, method = backgrounds.remove_background(
        _flat_source((0, 255, 0)),
        (0, 255, 0),
        config,
        _args(),
        {},
    )

    assert method != "chroma"

    unknown = backgrounds.normalize_background_removal({}, _args())
    assert unknown["source_family"] == "unknown"
    _cutout, unknown_method = backgrounds.remove_background(
        _flat_source((0, 255, 0)), (0, 255, 0), unknown, _args(), {}
    )
    assert unknown_method == "matte"


def test_auto_legacy_chroma_sources_keep_import_compatibility() -> None:
    config = {
        "method": "auto",
        "model": "birefnet-general",
        "source_family": "legacy-chroma",
        "post_rembg_chroma_cleanup": False,
    }

    cutout, method = backgrounds.remove_background(
        _flat_source((0, 255, 0)),
        (0, 255, 0),
        config,
        _args(),
        {},
    )

    assert method == "chroma"
    assert cutout.getpixel((0, 0))[3] == 0
    explicit = backgrounds.normalize_background_removal({"background_removal": {"method": "chroma"}}, _args())
    assert explicit["source_family"] == "legacy-chroma"


def test_matte_review_compares_checker_black_gray_white_and_alpha(
    tmp_path: Path,
) -> None:
    raw = _flat_source((128, 128, 128))
    processed = backgrounds.remove_matte_background(raw, 28.0, 8)

    relative = backgrounds.save_background_matte_review(
        [{"state": "idle", "method": "matte", "raw": raw, "processed": processed}],
        tmp_path,
    )

    assert relative == "qa/background-matte-review.png"
    with Image.open(tmp_path / relative) as review:
        assert review.width == 260 * 6 + 8 * 7
        assert review.height > 100


def test_state_local_matte_refresh_keeps_sibling_state_in_combined_review(
    tmp_path: Path,
) -> None:
    raw = _flat_source((128, 128, 128))
    processed = backgrounds.remove_matte_background(raw, 28.0, 8)
    entries = [
        {"state": state, "method": "matte", "raw": raw, "processed": processed}
        for state in ("idle-step", "attack")
    ]

    relative = backgrounds.save_state_and_combined_matte_reviews(
        entries,
        tmp_path,
        ["idle-step", "attack"],
    )
    with Image.open(tmp_path / "qa" / "idle-step-background-matte-review.png") as idle:
        idle_height = idle.height
    with Image.open(tmp_path / "qa" / "attack-background-matte-review.png") as attack:
        attack_height = attack.height
    with Image.open(tmp_path / relative) as combined:
        assert combined.height == idle_height + attack_height

    backgrounds.save_state_and_combined_matte_reviews(
        [entries[1]],
        tmp_path,
        ["idle-step", "attack"],
    )
    with Image.open(tmp_path / relative) as combined:
        assert combined.height == idle_height + attack_height


def test_pixel_art_edge_refinement_does_not_introduce_fractional_alpha() -> None:
    args = _args()
    args.edge_refine = "conservative"
    args.pixel_art = True
    source = _flat_source((128, 128, 128))

    cutout, method = backgrounds.remove_background(
        source,
        (255, 0, 255),
        {
            "method": "matte",
            "model": "birefnet-general",
            "source_family": "neutral",
            "post_rembg_chroma_cleanup": False,
        },
        args,
        {},
    )

    assert method == "matte"
    assert set(cutout.getchannel("A").tobytes()) <= {0, 255}


def test_lucida_hard_alpha_policy_uses_the_declared_threshold(monkeypatch) -> None:
    source = Image.new("RGBA", (4, 1), (40, 40, 40, 255))
    soft = Image.new("RGBA", (4, 1), (220, 80, 40, 255))
    soft.putalpha(Image.frombytes("L", (4, 1), bytes([0, 63, 64, 255])))
    monkeypatch.setattr(
        backgrounds,
        "remove_lucida_background",
        lambda image, config, sessions: soft.copy(),
    )

    cutout, method = backgrounds.remove_background(
        source,
        (255, 0, 255),
        {
            "method": "lucida",
            "model": backgrounds.DEFAULT_LUCIDA_MODEL,
            "revision": backgrounds.DEFAULT_LUCIDA_REVISION,
            "device": "cpu",
            "input_size": 1024,
            "alpha_mode": "hard",
            "hard_alpha_threshold": 64,
        },
        _args(),
        {},
    )

    assert method == "lucida"
    assert list(cutout.getchannel("A").tobytes()) == [0, 0, 255, 255]


def test_native_alpha_honors_the_declared_hard_alpha_policy() -> None:
    source = Image.new("RGBA", (8, 1), (220, 80, 40, 0))
    source.putalpha(Image.frombytes("L", (8, 1), bytes([0, 0, 0, 0, 0, 0, 100, 200])))

    cutout, method = backgrounds.remove_background(
        source,
        (255, 0, 255),
        {"method": "alpha", "alpha_mode": "hard", "hard_alpha_threshold": 128},
        _args(),
        {},
    )

    assert method == "alpha"
    assert list(cutout.getchannel("A").tobytes()) == [0, 0, 0, 0, 0, 0, 0, 255]

    video_cell = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    video_cell.paste((220, 80, 40, 255), (8, 6, 23, 28))
    for requested, expected in (("alpha", "alpha"), ("none", "none"), ("auto", "alpha")):
        sprites, processed, method, report, errors = backgrounds.extract_video_frame_sprites(
            video_cell,
            frame_count=1,
            columns=1,
            rows=1,
            background_rgb=(17, 17, 17),
            chroma_key=(255, 0, 255),
            background_removal={"method": requested, "source_family": "transparent", "alpha_mode": "soft"},
            args=_args(),
            sessions={},
            position_locked_canvas=True,
        )
        assert method == expected and report["ok"] is True and errors == []
        assert sprites is not None and sprites[0].tobytes() == video_cell.tobytes()
        assert processed.tobytes() == video_cell.tobytes()


def test_lucida_conservative_cleanup_removes_only_neutral_edge_leak(monkeypatch) -> None:
    source = Image.new("RGBA", (8, 8), (0, 0, 0, 255))
    soft = Image.new("RGBA", source.size, (0, 0, 0, 0))
    for y in range(2, 6):
        for x in range(2, 6):
            soft.putpixel((x, y), (18, 18, 18, 255))
    soft.putpixel((7, 3), (1, 1, 1, 255))
    monkeypatch.setattr(
        backgrounds,
        "remove_lucida_background",
        lambda image, config, sessions: soft.copy(),
    )
    args = _args()
    args.edge_refine = "conservative"

    cutout, method = backgrounds.remove_background(
        source,
        (255, 0, 255),
        {
            "method": "lucida",
            "model": backgrounds.DEFAULT_LUCIDA_MODEL,
            "revision": backgrounds.DEFAULT_LUCIDA_REVISION,
            "device": "cpu",
            "input_size": 1024,
            "alpha_mode": "hard",
            "hard_alpha_threshold": 64,
        },
        args,
        {},
    )

    assert method == "lucida"
    assert cutout.getpixel((7, 3))[3] == 0
    assert cutout.getpixel((2, 3))[3] == 255
    assert cutout.getpixel((4, 4))[3] == 255


def test_enclosed_hole_recovery_restores_dark_subject_interior() -> None:
    source = Image.new("RGBA", (9, 9), (0, 0, 0, 255))
    cutout = Image.new("RGBA", source.size, (0, 0, 0, 0))
    for value in range(2, 7):
        cutout.putpixel((value, 2), (100, 120, 140, 255))
        cutout.putpixel((value, 6), (100, 120, 140, 255))
        cutout.putpixel((2, value), (100, 120, 140, 255))
        cutout.putpixel((6, value), (100, 120, 140, 255))

    restored, pixels = backgrounds.restore_enclosed_source_holes(
        source,
        cutout,
        max_hole_ratio=0.2,
    )

    assert pixels == 9
    assert restored.getpixel((4, 4)) == (0, 0, 0, 255)
    assert restored.getpixel((0, 0))[3] == 0

    source.putpixel((4, 4), (240, 50, 80, 0))
    source.putpixel((3, 4), (0, 0, 0, 128))
    restored_alpha, pixels = backgrounds.restore_enclosed_source_holes(source, cutout, max_hole_ratio=0.2)
    assert pixels == 8
    assert restored_alpha.getpixel((4, 4))[3] == 0
    assert restored_alpha.getpixel((3, 4))[3] == 128
    single_hole = Image.new("RGBA", source.size, (100, 120, 140, 255))
    single_hole.putpixel((4, 4), (0, 0, 0, 0))
    source.putpixel((4, 4), (0, 0, 0, 255))
    zero_ratio, zero_pixels = backgrounds.restore_enclosed_source_holes(source, single_hole, max_hole_ratio=0)
    assert zero_pixels == 0 and zero_ratio.getpixel((4, 4))[3] == 0


def test_enclosed_hole_recovery_keeps_border_connected_gap_transparent() -> None:
    source = Image.new("RGBA", (9, 9), (0, 0, 0, 255))
    cutout = Image.new("RGBA", source.size, (0, 0, 0, 0))
    for value in range(2, 7):
        cutout.putpixel((value, 2), (100, 120, 140, 255))
        cutout.putpixel((value, 6), (100, 120, 140, 255))
        cutout.putpixel((2, value), (100, 120, 140, 255))
        cutout.putpixel((6, value), (100, 120, 140, 255))
    cutout.putpixel((4, 2), (0, 0, 0, 0))

    restored, pixels = backgrounds.restore_enclosed_source_holes(
        source,
        cutout,
        max_hole_ratio=0.2,
    )

    assert pixels == 0
    assert restored.getpixel((4, 4))[3] == 0


def test_lucida_can_restore_a_declared_large_enclosed_subject_cavity(
    monkeypatch,
) -> None:
    source = Image.new("RGBA", (21, 21), (0, 0, 0, 255))
    cutout = Image.new("RGBA", source.size, (0, 0, 0, 0))
    for value in range(4, 17):
        cutout.putpixel((value, 4), (100, 120, 140, 255))
        cutout.putpixel((value, 16), (100, 120, 140, 255))
        cutout.putpixel((4, value), (100, 120, 140, 255))
        cutout.putpixel((16, value), (100, 120, 140, 255))
    monkeypatch.setattr(
        backgrounds,
        "remove_lucida_background",
        lambda image, config, sessions: cutout.copy(),
    )

    restored, method = backgrounds.remove_background(
        source,
        (255, 0, 255),
        {
            "method": "lucida",
            "alpha_mode": "hard",
            "hard_alpha_threshold": 64,
            "source_recovery_enabled": False,
            "enclosed_hole_max_ratio": 0.3,
        },
        _args(),
        {},
    )

    assert method == "lucida"
    assert restored.getpixel((10, 10)) == (0, 0, 0, 255)

    source.putpixel((10, 10), (0, 0, 0, 128))
    hard_restored, _method = backgrounds.remove_background(
        source, (255, 0, 255),
        {"method": "lucida", "alpha_mode": "hard", "hard_alpha_threshold": 200,
         "source_recovery_enabled": False, "enclosed_hole_max_ratio": 0.3},
        _args(), {},
    )
    assert hard_restored.getpixel((10, 10))[3] == 0
    assert set(hard_restored.getchannel("A").tobytes()) <= {0, 255}


def test_canonical_reference_state_prefers_non_attack_state() -> None:
    request = {
        "states": {
            "attack": {"animation_workflows": ["front-fps-attack"]},
            "idle-step": {"animation_workflows": ["front-fps-creature-locomotion"]},
        }
    }

    assert backgrounds.canonical_reference_state(request) == "idle-step"


def test_canonical_reference_state_falls_back_when_only_attack_exists() -> None:
    request = {"states": {"attack": {"animation_workflows": ["front-fps-attack"]}}}

    assert backgrounds.canonical_reference_state(request) == "attack"


def test_row_frames_share_one_scale_when_a_wide_pose_needs_shrinking() -> None:
    idle = Image.new("RGBA", (40, 80), (0, 0, 0, 0))
    idle.paste((200, 60, 40, 255), (10, 0, 30, 80))
    strike = Image.new("RGBA", (120, 80), (0, 0, 0, 0))
    strike.paste((200, 60, 40, 255), (0, 0, 120, 80))

    frames = backgrounds.fit_pose_frames([idle, strike], None, None, 64, 96, 2, 2)

    heights = [frame.getbbox()[3] - frame.getbbox()[1] for frame in frames]
    assert heights[0] == heights[1]
