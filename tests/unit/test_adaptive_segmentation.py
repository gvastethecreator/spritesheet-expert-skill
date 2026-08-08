from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from extract_sprite_row_frames import (
    alpha_margin_count,
    extract_grid_adaptive_sprites,
    fit_pose_frames,
    safe_alpha_crop,
    save_adaptive_segmentation_overlay,
)


def _irregular_grid() -> Image.Image:
    sheet = Image.new("RGBA", (220, 140), (0, 0, 0, 0))
    draw = ImageDraw.Draw(sheet)
    draw.rectangle((5, 10, 49, 54), fill=(230, 60, 60, 255))
    draw.rectangle((80, 5, 144, 57), fill=(60, 180, 240, 255))
    draw.rectangle((15, 80, 89, 129), fill=(240, 190, 50, 255))
    draw.rectangle((125, 72, 209, 132), fill=(120, 220, 90, 255))
    draw.rectangle((72, 20, 77, 25), fill=(255, 255, 255, 255))
    draw.rectangle((104, 104, 109, 109), fill=(255, 255, 255, 255))
    return sheet


def test_adaptive_grid_uses_variable_source_bounds_and_keeps_row_order() -> None:
    sprites, report = extract_grid_adaptive_sprites(
        _irregular_grid(),
        frame_count=4,
        columns=2,
        rows=2,
    )

    assert sprites is not None
    assert report["ok"] is True
    assert report["assignment"] == "nearest-component-center-2d"
    assert report["row_counts"] == [2, 2]
    assert len(report["spans"]) == 4
    assert report["spans"][1]["source_bbox"][0] < 110
    assert report["spans"][1]["source_bbox"][2] > 110
    assert len({sprite.size for sprite in sprites}) > 1


def test_adaptive_grid_writes_a_source_bound_review(tmp_path: Path) -> None:
    sheet = _irregular_grid()
    _sprites, report = extract_grid_adaptive_sprites(
        sheet,
        frame_count=4,
        columns=2,
        rows=2,
    )

    relative = save_adaptive_segmentation_overlay(sheet, report, "attack", tmp_path)

    assert relative == "qa/attack-adaptive-segmentation.png"
    with Image.open(tmp_path / relative) as review:
        assert review.size == sheet.size


def test_safe_alpha_crop_adds_transparent_padding() -> None:
    image = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle((7, 5, 24, 28), fill=(220, 100, 50, 255))

    cropped, bbox, contacts = safe_alpha_crop(image, crop_padding=4)

    assert cropped is not None
    assert bbox == [7, 5, 25, 29]
    assert contacts == []
    assert cropped.getbbox() == (4, 4, cropped.width - 4, cropped.height - 4)


def test_safe_alpha_crop_reports_a_clipped_source_boundary() -> None:
    image = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle((0, 5, 24, 31), fill=(220, 100, 50, 255))

    _cropped, _bbox, contacts = safe_alpha_crop(image, crop_padding=4)

    assert contacts == ["left", "bottom"]


def test_alpha_margin_count_detects_content_inside_reserved_margin() -> None:
    image = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle((1, 8, 14, 20), fill=(255, 255, 255, 255))

    assert alpha_margin_count(image, 2, 2) > 0


def test_body_bottom_registration_places_every_grounded_frame_on_baseline() -> None:
    first = Image.new("RGBA", (20, 12), (220, 100, 50, 255))
    second = Image.new("RGBA", (18, 15), (220, 100, 50, 255))

    frames = fit_pose_frames(
        [first, second],
        None,
        None,
        32,
        32,
        2,
        2,
        registration={"anchor": "body-bottom", "target_bottom": 30},
    )

    assert [frame.getbbox()[3] for frame in frames] == [30, 30]


def test_airborne_pose_keeps_the_reserved_top_margin_transparent() -> None:
    sprite = Image.new("RGBA", (20, 30), (220, 100, 50, 255))
    pose = {
        "kind": "jump",
        "max_height_vs_reference": 1.15,
        "arc_peak_ratio": 0.22,
    }

    frames = fit_pose_frames(
        [sprite.copy() for _ in range(4)],
        pose,
        {"height": 30, "width": 20, "scale": 1.0},
        64,
        64,
        4,
        4,
    )

    assert all(alpha_margin_count(frame, 4, 4) == 0 for frame in frames)
