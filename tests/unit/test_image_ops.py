from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest
from PIL import Image, ImageDraw


def pixel_fixture() -> Image.Image:
    image = Image.new("RGBA", (2, 2))
    image.putdata(
        [
            (255, 0, 0, 255),
            (0, 255, 0, 255),
            (0, 0, 255, 255),
            (0, 0, 0, 0),
        ]
    )
    return image


def test_pixel_resize_replicates_source_pixels_without_mutating_input() -> None:
    from spritecore.image_ops import ResizePolicy, resize_image

    source = pixel_fixture()
    original = source.tobytes()

    resized = resize_image(
        source,
        (4, 4),
        policy=ResizePolicy(mode="pixel", enforce_integer_scale=True),
    )

    assert source.size == (2, 2)
    assert source.tobytes() == original
    assert resized.size == (4, 4)
    assert resized.getpixel((0, 0)) == (255, 0, 0, 255)
    assert resized.getpixel((1, 1)) == (255, 0, 0, 255)
    assert resized.getpixel((2, 0)) == (0, 255, 0, 255)
    assert resized.getpixel((0, 2)) == (0, 0, 255, 255)
    assert resized.getpixel((3, 3)) == (0, 0, 0, 0)


def test_pixel_resize_can_require_a_uniform_integer_scale() -> None:
    from spritecore.image_ops import ImagePolicyError, ResizePolicy, resize_image

    with pytest.raises(ImagePolicyError, match="integer scale"):
        resize_image(
            pixel_fixture(),
            (3, 3),
            policy=ResizePolicy(mode="pixel", enforce_integer_scale=True),
        )


def test_canonical_sampling_policy_selects_pixel_or_illustrated_resampling() -> None:
    from spritecore.image_ops import (
        ArtMode,
        resize_policy_from_sampling_policy,
    )

    assert resize_policy_from_sampling_policy({"filter": "nearest"}).mode is ArtMode.PIXEL
    assert (
        resize_policy_from_sampling_policy({"filter": "linear"}).mode
        is ArtMode.ILLUSTRATED
    )


def test_illustrated_downscale_uses_lanczos_without_mutating_input() -> None:
    from spritecore.image_ops import ResizePolicy, resize_image

    source = Image.new("RGBA", (4, 4))
    source.putdata(
        [
            (255, 255, 255, 255) if (x + y) % 2 == 0 else (0, 0, 0, 255)
            for y in range(4)
            for x in range(4)
        ]
    )
    original = source.tobytes()
    expected = source.resize((2, 2), Image.Resampling.LANCZOS)

    resized = resize_image(
        source,
        (2, 2),
        policy=ResizePolicy(mode="illustrated"),
    )

    assert resized.tobytes() == expected.tobytes()
    assert resized.tobytes() != source.resize(
        (2, 2), Image.Resampling.NEAREST
    ).tobytes()
    assert source.tobytes() == original


def test_nearest_pixel_transform_preserves_palette_and_binary_alpha() -> None:
    from spritecore.image_ops import (
        ResizePolicy,
        inspect_transform_invariants,
        resize_image,
    )

    source = pixel_fixture()
    resized = resize_image(
        source,
        (8, 8),
        policy=ResizePolicy(mode="pixel", enforce_integer_scale=True),
    )

    report = inspect_transform_invariants(source, resized)

    assert report.ok is True
    assert report.palette.new_opaque_colors == ()
    assert report.alpha.new_fractional_alpha_values == ()


def test_bilinear_pixel_corruption_fails_palette_and_alpha_invariants() -> None:
    from spritecore.image_ops import inspect_transform_invariants

    source = pixel_fixture()
    corrupted = source.resize((8, 8), Image.Resampling.BILINEAR)

    report = inspect_transform_invariants(source, corrupted)

    assert report.ok is False
    assert report.palette.ok is False
    assert report.palette.new_opaque_colors
    assert report.alpha.ok is False
    assert report.alpha.new_fractional_alpha_values
    with pytest.raises(FrozenInstanceError):
        report.palette.new_opaque_colors = ()


def test_frame_metrics_are_normalized_and_component_aware_for_tiny_art() -> None:
    from spritecore.image_ops import measure_frame

    frame = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    ImageDraw.Draw(frame).rectangle((2, 2, 5, 5), fill=(255, 0, 0, 255))

    metrics = measure_frame(frame)

    assert metrics.size == (8, 8)
    assert metrics.opaque_pixels == 16
    assert metrics.opaque_ratio == 0.25
    assert metrics.bbox == (2, 2, 6, 6)
    assert metrics.bbox_ratio == 0.25
    assert metrics.largest_component_pixels == 16
    assert metrics.largest_component_ratio == 1.0
    assert metrics.edge_contact_pixels == 0
    assert metrics.normalized_edge_contact == 0.0


@pytest.mark.parametrize(
    ("size", "rectangle", "profile_name"),
    [
        ((8, 8), (2, 2, 5, 5), "tiny-8x8"),
        ((8, 16), (2, 3, 5, 12), "tiny-8x16"),
        ((32, 32), (8, 6, 23, 25), "small-32x32"),
        ((64, 64), (16, 12, 47, 51), "normal"),
    ],
)
def test_scale_aware_profiles_accept_tiny_and_normal_frames(
    size: tuple[int, int],
    rectangle: tuple[int, int, int, int],
    profile_name: str,
) -> None:
    from spritecore.image_ops import validate_frame

    frame = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(frame).rectangle(rectangle, fill=(80, 160, 240, 255))

    report = validate_frame(frame)

    assert report.ok is True
    assert report.profile.name == profile_name
    assert report.failures == ()
    if size in {(8, 8), (8, 16), (32, 32)}:
        assert report.metrics.opaque_pixels < 400


def test_bilinear_corruption_is_a_hard_frame_invariant_failure() -> None:
    from spritecore.image_ops import inspect_transform_invariants, validate_frame

    source = pixel_fixture()
    corrupted = source.resize((8, 8), Image.Resampling.BILINEAR)
    invariants = inspect_transform_invariants(source, corrupted)

    report = validate_frame(corrupted, invariants=invariants)

    assert report.ok is False
    assert any("palette invariant violation" in failure for failure in report.failures)
    assert any("alpha invariant violation" in failure for failure in report.failures)


def test_blank_edge_escape_and_extreme_occupancy_are_hard_failures() -> None:
    from spritecore.image_ops import validate_frame

    blank = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    blank_report = validate_frame(blank)
    assert blank_report.failures == ("blank frame",)

    clipped = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    ImageDraw.Draw(clipped).rectangle((0, 8, 12, 23), fill=(255, 255, 255, 255))
    clipped_report = validate_frame(clipped)
    assert any("edge escape" in failure for failure in clipped_report.failures)

    implausibly_tiny = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    implausibly_tiny.putpixel((16, 16), (255, 255, 255, 255))
    tiny_report = validate_frame(implausibly_tiny)
    assert any("extreme opaque occupancy" in failure for failure in tiny_report.failures)


def test_fragmentation_is_reported_as_a_warning_not_an_extra_hard_gate() -> None:
    from spritecore.image_ops import validate_frame

    frame = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    draw = ImageDraw.Draw(frame)
    draw.rectangle((5, 10, 10, 15), fill=(255, 255, 255, 255))
    draw.rectangle((20, 10, 25, 15), fill=(255, 255, 255, 255))

    report = validate_frame(frame)

    assert report.ok is True
    assert report.failures == ()
    assert report.warnings
    assert report.metrics.largest_component_ratio == 0.5


def test_full_cell_profile_allows_edge_contact_without_weakening_sprite_profile() -> None:
    from spritecore.image_ops import validate_frame

    frame = Image.new("RGBA", (32, 32), (80, 120, 200, 255))

    full_cell = validate_frame(frame, allow_full_cell=True)
    sprite = validate_frame(frame)

    assert full_cell.ok is True
    assert full_cell.metrics.opaque_ratio == 1.0
    assert full_cell.metrics.edge_contact_pixels > 0
    assert sprite.ok is False
    assert any("edge escape" in failure for failure in sprite.failures)
