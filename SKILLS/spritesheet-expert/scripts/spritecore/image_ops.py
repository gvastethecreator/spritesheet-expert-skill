"""Pure, policy-driven image transforms and scale-aware frame inspection."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from fractions import Fraction
from typing import Any, Mapping

from PIL import Image


class ImagePolicyError(ValueError):
    """An image operation contradicts its declared transform policy."""


class ArtMode(str, Enum):
    PIXEL = "pixel"
    ILLUSTRATED = "illustrated"


@dataclass(frozen=True, slots=True)
class ResizePolicy:
    """Immutable resampling policy for one art family."""

    mode: ArtMode | str
    enforce_integer_scale: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "mode", ArtMode(self.mode))
        if self.mode is ArtMode.ILLUSTRATED and self.enforce_integer_scale:
            raise ImagePolicyError(
                "integer-scale enforcement applies only to pixel art"
            )


def resize_policy_from_sampling_policy(
    sampling_policy: Mapping[str, Any] | None,
    *,
    enforce_integer_scale: bool = False,
) -> ResizePolicy:
    """Map the canonical nearest/linear sampling contract to transform policy."""

    policy = sampling_policy if isinstance(sampling_policy, Mapping) else {}
    filter_name = str(policy.get("filter", "linear"))
    if filter_name == "nearest":
        return ResizePolicy(
            mode=ArtMode.PIXEL,
            enforce_integer_scale=enforce_integer_scale,
        )
    if filter_name == "linear":
        return ResizePolicy(mode=ArtMode.ILLUSTRATED)
    raise ImagePolicyError(f"unsupported sampling_policy.filter: {filter_name!r}")


@dataclass(frozen=True, slots=True)
class PaletteInvariantReport:
    """Opaque palette changes introduced by a transform."""

    source_opaque_color_count: int
    transformed_opaque_color_count: int
    new_opaque_colors: tuple[tuple[int, int, int], ...]

    @property
    def ok(self) -> bool:
        return not self.new_opaque_colors


@dataclass(frozen=True, slots=True)
class AlphaInvariantReport:
    """Fractional alpha values introduced by a transform."""

    source_fractional_alpha_values: tuple[int, ...]
    transformed_fractional_alpha_values: tuple[int, ...]
    new_fractional_alpha_values: tuple[int, ...]

    @property
    def ok(self) -> bool:
        return not self.new_fractional_alpha_values


@dataclass(frozen=True, slots=True)
class TransformInvariantReport:
    """Combined immutable palette and alpha invariant report."""

    palette: PaletteInvariantReport
    alpha: AlphaInvariantReport

    @property
    def ok(self) -> bool:
        return self.palette.ok and self.alpha.ok


@dataclass(frozen=True, slots=True)
class FrameMetrics:
    """Scale-independent alpha geometry for one frame."""

    size: tuple[int, int]
    opaque_pixels: int
    opaque_ratio: float
    bbox: tuple[int, int, int, int] | None
    bbox_ratio: float
    largest_component_pixels: int
    largest_component_ratio: float
    edge_contact_pixels: int
    normalized_edge_contact: float


@dataclass(frozen=True, slots=True)
class FrameProfile:
    """Ratio-based validation envelope for one frame scale family."""

    name: str
    min_opaque_ratio: float
    max_opaque_ratio: float
    min_bbox_ratio: float
    max_bbox_ratio: float
    component_warning_ratio: float = 0.75


@dataclass(frozen=True, slots=True)
class FrameValidationReport:
    """Immutable frame validation result with hard failures and soft warnings."""

    profile: FrameProfile
    metrics: FrameMetrics
    failures: tuple[str, ...]
    warnings: tuple[str, ...]
    invariants: TransformInvariantReport | None = None

    @property
    def ok(self) -> bool:
        return not self.failures


TINY_8X8_PROFILE = FrameProfile(
    name="tiny-8x8",
    min_opaque_ratio=0.04,
    max_opaque_ratio=0.90,
    min_bbox_ratio=0.06,
    max_bbox_ratio=0.95,
)
TINY_8X16_PROFILE = FrameProfile(
    name="tiny-8x16",
    min_opaque_ratio=0.03,
    max_opaque_ratio=0.90,
    min_bbox_ratio=0.04,
    max_bbox_ratio=0.95,
)
SMALL_32X32_PROFILE = FrameProfile(
    name="small-32x32",
    min_opaque_ratio=0.01,
    max_opaque_ratio=0.90,
    min_bbox_ratio=0.02,
    max_bbox_ratio=0.95,
)
NORMAL_FRAME_PROFILE = FrameProfile(
    name="normal",
    min_opaque_ratio=0.005,
    max_opaque_ratio=0.90,
    min_bbox_ratio=0.01,
    max_bbox_ratio=0.95,
)
_PROFILES_BY_NAME = {
    profile.name: profile
    for profile in (
        TINY_8X8_PROFILE,
        TINY_8X16_PROFILE,
        SMALL_32X32_PROFILE,
        NORMAL_FRAME_PROFILE,
    )
}


def resize_image(
    image: Image.Image,
    target_size: tuple[int, int],
    *,
    policy: ResizePolicy,
) -> Image.Image:
    """Return a resized copy without mutating the source image."""

    width, height = target_size
    if width < 1 or height < 1:
        raise ImagePolicyError("target dimensions must be positive integers")
    if policy.mode is ArtMode.PIXEL:
        if policy.enforce_integer_scale:
            _require_uniform_integer_scale(image.size, target_size)
        resample = Image.Resampling.NEAREST
    else:
        is_downscale = width < image.width or height < image.height
        resample = (
            Image.Resampling.LANCZOS if is_downscale else Image.Resampling.BICUBIC
        )
    return image.resize(target_size, resample)


def inspect_transform_invariants(
    source: Image.Image, transformed: Image.Image
) -> TransformInvariantReport:
    """Report newly introduced opaque colors and fractional alpha values."""

    source_pixels = tuple(source.convert("RGBA").get_flattened_data())
    transformed_pixels = tuple(transformed.convert("RGBA").get_flattened_data())
    source_colors = {
        (red, green, blue)
        for red, green, blue, alpha in source_pixels
        if alpha == 255
    }
    transformed_colors = {
        (red, green, blue)
        for red, green, blue, alpha in transformed_pixels
        if alpha == 255
    }
    source_fractional = {
        alpha for _red, _green, _blue, alpha in source_pixels if 0 < alpha < 255
    }
    transformed_fractional = {
        alpha
        for _red, _green, _blue, alpha in transformed_pixels
        if 0 < alpha < 255
    }
    return TransformInvariantReport(
        palette=PaletteInvariantReport(
            source_opaque_color_count=len(source_colors),
            transformed_opaque_color_count=len(transformed_colors),
            new_opaque_colors=tuple(sorted(transformed_colors - source_colors)),
        ),
        alpha=AlphaInvariantReport(
            source_fractional_alpha_values=tuple(sorted(source_fractional)),
            transformed_fractional_alpha_values=tuple(sorted(transformed_fractional)),
            new_fractional_alpha_values=tuple(
                sorted(transformed_fractional - source_fractional)
            ),
        ),
    )


def inspect_hard_alpha(image: Image.Image) -> AlphaInvariantReport:
    """Report every fractional alpha value in a final pixel-art image."""

    fractional = tuple(
        sorted(
            {
                alpha
                for alpha in image.convert("RGBA")
                .getchannel("A")
                .get_flattened_data()
                if 0 < alpha < 255
            }
        )
    )
    return AlphaInvariantReport(
        source_fractional_alpha_values=(),
        transformed_fractional_alpha_values=fractional,
        new_fractional_alpha_values=fractional,
    )


def measure_frame(
    image: Image.Image, *, alpha_threshold: int = 0
) -> FrameMetrics:
    """Measure normalized occupancy, bounds, connectivity, and edge contact."""

    if not 0 <= alpha_threshold < 255:
        raise ImagePolicyError("alpha_threshold must be between 0 and 254")
    alpha = tuple(image.convert("RGBA").getchannel("A").get_flattened_data())
    width, height = image.size
    mask = tuple(value > alpha_threshold for value in alpha)
    occupied = [index for index, value in enumerate(mask) if value]
    opaque_pixels = len(occupied)
    frame_area = width * height
    if occupied:
        xs = [index % width for index in occupied]
        ys = [index // width for index in occupied]
        bbox = (min(xs), min(ys), max(xs) + 1, max(ys) + 1)
        bbox_area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
    else:
        bbox = None
        bbox_area = 0

    largest_component = _largest_component_size(mask, width, height)
    edge_indices = _edge_indices(width, height)
    edge_contact = sum(1 for index in edge_indices if mask[index])
    return FrameMetrics(
        size=(width, height),
        opaque_pixels=opaque_pixels,
        opaque_ratio=opaque_pixels / frame_area,
        bbox=bbox,
        bbox_ratio=bbox_area / frame_area,
        largest_component_pixels=largest_component,
        largest_component_ratio=(
            largest_component / opaque_pixels if opaque_pixels else 0.0
        ),
        edge_contact_pixels=edge_contact,
        normalized_edge_contact=edge_contact / len(edge_indices),
    )


def frame_profile_for_size(size: tuple[int, int]) -> FrameProfile:
    """Select the explicit tiny/small profile or the ratio-based normal profile."""

    if size == (8, 8):
        return TINY_8X8_PROFILE
    if sorted(size) == [8, 16]:
        return TINY_8X16_PROFILE
    if size == (32, 32):
        return SMALL_32X32_PROFILE
    return NORMAL_FRAME_PROFILE


def validate_frame(
    image: Image.Image,
    *,
    profile: FrameProfile | str | None = None,
    invariants: TransformInvariantReport | None = None,
    alpha_threshold: int = 0,
    allow_full_cell: bool = False,
) -> FrameValidationReport:
    """Validate only blank, escape, extreme occupancy, and invariant failures."""

    selected = _resolve_profile(profile, image.size)
    metrics = measure_frame(image, alpha_threshold=alpha_threshold)
    failures: list[str] = []
    warnings: list[str] = []
    if metrics.opaque_pixels == 0:
        failures.append("blank frame")
    else:
        if metrics.edge_contact_pixels and not allow_full_cell:
            failures.append(
                "clipped or edge escape: "
                f"{metrics.edge_contact_pixels} opaque boundary pixels "
                f"({metrics.normalized_edge_contact:.4f} normalized)"
            )
        opaque_too_low = metrics.opaque_ratio < selected.min_opaque_ratio
        opaque_too_high = metrics.opaque_ratio > selected.max_opaque_ratio
        if opaque_too_low or (opaque_too_high and not allow_full_cell):
            failures.append(
                f"extreme opaque occupancy {metrics.opaque_ratio:.4f}; expected "
                f"{selected.min_opaque_ratio:.4f}..{selected.max_opaque_ratio:.4f}"
            )
        bbox_too_low = metrics.bbox_ratio < selected.min_bbox_ratio
        bbox_too_high = metrics.bbox_ratio > selected.max_bbox_ratio
        if bbox_too_low or (bbox_too_high and not allow_full_cell):
            failures.append(
                f"extreme bbox occupancy {metrics.bbox_ratio:.4f}; expected "
                f"{selected.min_bbox_ratio:.4f}..{selected.max_bbox_ratio:.4f}"
            )
        if metrics.largest_component_ratio < selected.component_warning_ratio:
            warnings.append(
                "largest connected component covers only "
                f"{metrics.largest_component_ratio:.4f} of opaque pixels"
            )
    if invariants is not None:
        if not invariants.palette.ok:
            failures.append(
                "palette invariant violation: "
                f"{len(invariants.palette.new_opaque_colors)} new opaque colors"
            )
        if not invariants.alpha.ok:
            failures.append(
                "alpha invariant violation: "
                f"{len(invariants.alpha.new_fractional_alpha_values)} new fractional values"
            )
    return FrameValidationReport(
        profile=selected,
        metrics=metrics,
        failures=tuple(failures),
        warnings=tuple(warnings),
        invariants=invariants,
    )


def _resolve_profile(
    profile: FrameProfile | str | None, size: tuple[int, int]
) -> FrameProfile:
    if profile is None:
        return frame_profile_for_size(size)
    if isinstance(profile, FrameProfile):
        return profile
    try:
        return _PROFILES_BY_NAME[profile]
    except KeyError as exc:
        raise ImagePolicyError(f"unknown frame profile: {profile!r}") from exc


def _edge_indices(width: int, height: int) -> tuple[int, ...]:
    indices = set(range(width))
    indices.update(range((height - 1) * width, height * width))
    for y in range(1, height - 1):
        indices.add(y * width)
        indices.add(y * width + width - 1)
    return tuple(sorted(indices))


def _largest_component_size(
    mask: tuple[bool, ...], width: int, height: int
) -> int:
    visited = bytearray(len(mask))
    largest = 0
    for start, occupied in enumerate(mask):
        if not occupied or visited[start]:
            continue
        visited[start] = 1
        stack = [start]
        size = 0
        while stack:
            index = stack.pop()
            size += 1
            x, y = index % width, index // width
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if dx == 0 and dy == 0:
                        continue
                    nx, ny = x + dx, y + dy
                    if not (0 <= nx < width and 0 <= ny < height):
                        continue
                    neighbor = ny * width + nx
                    if mask[neighbor] and not visited[neighbor]:
                        visited[neighbor] = 1
                        stack.append(neighbor)
        largest = max(largest, size)
    return largest


def _require_uniform_integer_scale(
    source_size: tuple[int, int], target_size: tuple[int, int]
) -> None:
    scale_x = Fraction(target_size[0], source_size[0])
    scale_y = Fraction(target_size[1], source_size[1])
    if scale_x != scale_y or not (scale_x.numerator == 1 or scale_x.denominator == 1):
        raise ImagePolicyError(
            "pixel art integer scale must be uniform and an integer multiple or divisor"
        )
