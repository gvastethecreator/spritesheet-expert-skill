from __future__ import annotations

from argparse import Namespace
from pathlib import Path

from PIL import Image

import extract_sprite_row_frames as backgrounds


def _args() -> Namespace:
    return Namespace(
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


def test_quality_birefnet_is_the_default_model() -> None:
    assert backgrounds.DEFAULT_REMBG_MODEL == "birefnet-general"
    assert backgrounds.default_background_model("auto") == "birefnet-general"


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
