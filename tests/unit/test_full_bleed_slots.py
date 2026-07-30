from __future__ import annotations

from PIL import Image
import pytest

from extract_sprite_row_frames import (
    fit_full_bleed_cell,
    fit_position_locked_canvas,
    full_bleed_slot_flags,
)


def test_full_bleed_fit_covers_odd_provider_cell_without_alpha_gaps() -> None:
    source = Image.new("RGBA", (313, 314), (65, 140, 50, 255))

    result = fit_full_bleed_cell(source, 256, 256)

    assert result.size == (256, 256)
    assert result.getchannel("A").getextrema() == (255, 255)


def test_position_locked_canvas_preserves_subject_offset() -> None:
    source = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
    for x in range(20, 40):
        for y in range(60, 90):
            source.putpixel((x, y), (70, 150, 45, 255))

    result = fit_position_locked_canvas(source, 50, 50)

    alpha = result.getchannel("A")
    weighted_x = sum(
        x * alpha.getpixel((x, y)) for y in range(50) for x in range(50)
    )
    alpha_mass = sum(value * count for value, count in enumerate(alpha.histogram()))
    assert (weighted_x / alpha_mass) / 50 == pytest.approx(0.295, abs=0.01)


def test_full_bleed_flags_preserve_overlay_transparency() -> None:
    entry = {"asset_labels": ["self", "edge", "overlay", "missing"]}
    catalog = {
        "self": {"repeat_mode": "self"},
        "edge": {"repeat_mode": "adjacency"},
        "overlay": {"repeat_mode": "overlay"},
    }

    assert full_bleed_slot_flags("tileset", entry, catalog, 4) == [
        True,
        True,
        False,
        False,
    ]
