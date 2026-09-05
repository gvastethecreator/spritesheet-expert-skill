"""Deterministic segmentation and rectangular packing for irregular item sheets.

The module deliberately owns geometry only. It never invents semantic pixels and
never invokes a paid or remote model. Classification and regeneration are
portable handoffs applied after extraction.
"""

from __future__ import annotations

from array import array
from collections import defaultdict, deque
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from hashlib import sha256
import json
import math
from pathlib import Path
import shutil
import tempfile
from typing import Any, Iterable, Mapping, Sequence

from PIL import Image, ImageDraw


class ItemSheetError(ValueError):
    """Raised when an item sheet cannot be compiled safely."""


@dataclass(frozen=True)
class SegmentationConfig:
    alpha_high: int = 64
    alpha_low: int = 2
    halo_radius: int = 6
    min_strong_pixels: int = 12
    connectivity: int = 8

    def validate(self) -> None:
        if not 1 <= self.alpha_high <= 255:
            raise ItemSheetError("alpha_high must be between 1 and 255")
        if not 1 <= self.alpha_low <= self.alpha_high:
            raise ItemSheetError("alpha_low must be between 1 and alpha_high")
        if not 0 <= self.halo_radius <= 64:
            raise ItemSheetError("halo_radius must be between 0 and 64")
        if self.min_strong_pixels < 1:
            raise ItemSheetError("min_strong_pixels must be positive")
        if self.connectivity not in {4, 8}:
            raise ItemSheetError("connectivity must be 4 or 8")


@dataclass(frozen=True)
class PackingConfig:
    quantum: int = 32
    padding: int = 16
    max_width: int = 0
    outer_padding: int = 0

    def validate(self) -> None:
        if self.quantum < 1:
            raise ItemSheetError("quantum must be positive")
        if self.padding < 0:
            raise ItemSheetError("padding cannot be negative")
        if self.max_width and self.max_width < self.quantum:
            raise ItemSheetError("max_width must be at least one quantum")
        if self.outer_padding < 0:
            raise ItemSheetError("outer_padding cannot be negative")
        if self.max_width and self.max_width - self.outer_padding * 2 < self.quantum:
            raise ItemSheetError("max_width cannot contain one quantum after outer padding")


@dataclass(frozen=True)
class _Rect:
    x: int
    y: int
    w: int
    h: int

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h


@dataclass
class ExtractedItem:
    item_id: str
    content_sha256: str
    source_bbox: tuple[int, int, int, int]
    image: Image.Image
    strong_pixels: int
    assigned_pixels: int
    weak_pixels: int
    qa_flags: list[str]
    lineage: dict[str, Any] = field(default_factory=dict)

    @property
    def width(self) -> int:
        return self.image.width

    @property
    def height(self) -> int:
        return self.image.height


_NEIGHBORS_4 = ((-1, 0), (1, 0), (0, -1), (0, 1))
_NEIGHBORS_8 = (
    (-1, 0),
    (1, 0),
    (0, -1),
    (0, 1),
    (-1, -1),
    (1, -1),
    (-1, 1),
    (1, 1),
)


def _digest_bytes(content: bytes) -> str:
    return sha256(content).hexdigest()


def _digest_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def item_content_sha256(image: Image.Image) -> str:
    """Hash native dimensions and RGBA bytes for one isolated item."""

    rgba = image.convert("RGBA")
    return _digest_bytes(
        rgba.width.to_bytes(4, "big")
        + rgba.height.to_bytes(4, "big")
        + rgba.tobytes()
    )


def unique_item_id(content_sha256: str, used_ids: set[str]) -> str:
    """Return the first stable content-derived ID not present in ``used_ids``."""

    if len(content_sha256) != 64 or any(character not in "0123456789abcdef" for character in content_sha256):
        raise ItemSheetError("content_sha256 must be a lowercase SHA-256 digest")
    base = f"item_{content_sha256[:12]}"
    if base not in used_ids:
        return base
    for occurrence in range(2, 100):
        candidate = f"{base}_{occurrence:02d}"
        if candidate not in used_ids:
            return candidate
    raise ItemSheetError(f"too many identical items for stable ID prefix {base}")


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _atomic_image(path: Path, image: Image.Image) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.stem + ".tmp" + path.suffix)
    image.save(temporary)
    temporary.replace(path)


def _neighbors(index: int, width: int, height: int, connectivity: int) -> Iterable[int]:
    x = index % width
    y = index // width
    offsets = _NEIGHBORS_8 if connectivity == 8 else _NEIGHBORS_4
    for dx, dy in offsets:
        nx = x + dx
        ny = y + dy
        if 0 <= nx < width and 0 <= ny < height:
            yield ny * width + nx


def _label_strong_components(
    alpha: bytes,
    width: int,
    height: int,
    config: SegmentationConfig,
) -> tuple[array, list[int]]:
    labels = array("i", [-1]) * (width * height)
    counts: list[int] = []
    queue: deque[int] = deque()

    for start, value in enumerate(alpha):
        if value < config.alpha_high or labels[start] != -1:
            continue
        component = len(counts)
        labels[start] = component
        queue.append(start)
        count = 0
        while queue:
            current = queue.popleft()
            count += 1
            for neighbor in _neighbors(current, width, height, config.connectivity):
                if alpha[neighbor] >= config.alpha_high and labels[neighbor] == -1:
                    labels[neighbor] = component
                    queue.append(neighbor)
        counts.append(count)

    keep = [index for index, count in enumerate(counts) if count >= config.min_strong_pixels]
    remap = {old: new for new, old in enumerate(keep)}
    kept_counts = [counts[index] for index in keep]
    for index, label in enumerate(labels):
        labels[index] = remap.get(label, -1)
    return labels, kept_counts


def _grow_into_weak_alpha(
    alpha: bytes,
    width: int,
    height: int,
    labels: array,
    component_count: int,
    config: SegmentationConfig,
) -> tuple[array, list[int]]:
    """Grow strong components through nearby weak alpha without joining seeds.

    This is a bounded multi-source breadth-first expansion. Weak bridges beyond
    the configured halo cannot merge two otherwise independent components.
    """

    distances = array("h", [-1]) * (width * height)
    conflicts = [0] * component_count
    queue: deque[int] = deque()
    for index, label in enumerate(labels):
        if label >= 0:
            distances[index] = 0
            queue.append(index)

    while queue:
        current = queue.popleft()
        distance = distances[current]
        if distance >= config.halo_radius:
            continue
        owner = labels[current]
        for neighbor in _neighbors(current, width, height, config.connectivity):
            if alpha[neighbor] < config.alpha_low:
                continue
            candidate_distance = distance + 1
            previous_distance = distances[neighbor]
            previous_owner = labels[neighbor]
            if previous_distance == -1:
                distances[neighbor] = candidate_distance
                labels[neighbor] = owner
                queue.append(neighbor)
            elif previous_owner != owner and previous_distance == candidate_distance:
                conflicts[owner] += 1
                if previous_owner >= 0:
                    conflicts[previous_owner] += 1
                # Stable tie break. A changed boundary pixel is intentionally
                # not re-expanded; strong seeds always remain authoritative.
                if owner < previous_owner:
                    labels[neighbor] = owner
    return labels, conflicts


def _component_metrics(
    labels: array,
    alpha: bytes,
    width: int,
    height: int,
    strong_counts: Sequence[int],
    alpha_high: int,
) -> list[dict[str, Any]]:
    metrics: list[dict[str, Any]] = [
        {
            "left": width,
            "top": height,
            "right": -1,
            "bottom": -1,
            "assigned": 0,
            "weak": 0,
        }
        for _ in strong_counts
    ]
    for index, label in enumerate(labels):
        if label < 0:
            continue
        x = index % width
        y = index // width
        metric = metrics[label]
        metric["left"] = min(metric["left"], x)
        metric["top"] = min(metric["top"], y)
        metric["right"] = max(metric["right"], x)
        metric["bottom"] = max(metric["bottom"], y)
        metric["assigned"] += 1
        if alpha[index] < alpha_high:
            metric["weak"] += 1
    return metrics


def _masked_crop(
    source: Image.Image,
    labels: array,
    component: int,
    bbox: tuple[int, int, int, int],
) -> Image.Image:
    left, top, right, bottom = bbox
    crop = source.crop(bbox).convert("RGBA")
    mask = bytearray(crop.width * crop.height)
    for local_y, source_y in enumerate(range(top, bottom)):
        source_row = source_y * source.width
        local_row = local_y * crop.width
        for local_x, source_x in enumerate(range(left, right)):
            if labels[source_row + source_x] == component:
                mask[local_row + local_x] = 255
    binary = Image.frombytes("L", crop.size, bytes(mask))
    transparent = Image.new("RGBA", crop.size, (0, 0, 0, 0))
    return Image.composite(crop, transparent, binary)


def segment_items(
    image: Image.Image,
    config: SegmentationConfig | None = None,
) -> list[ExtractedItem]:
    """Return isolated RGBA items in deterministic source order."""

    selected = config or SegmentationConfig()
    selected.validate()
    rgba = image.convert("RGBA")
    width, height = rgba.size
    if width < 1 or height < 1:
        raise ItemSheetError("source image is empty")

    alpha = rgba.getchannel("A").tobytes()
    labels, strong_counts = _label_strong_components(alpha, width, height, selected)
    if not strong_counts:
        raise ItemSheetError("no significant strong-alpha components found")
    labels, conflicts = _grow_into_weak_alpha(
        alpha,
        width,
        height,
        labels,
        len(strong_counts),
        selected,
    )
    metrics = _component_metrics(
        labels,
        alpha,
        width,
        height,
        strong_counts,
        selected.alpha_high,
    )

    provisional: list[tuple[str, tuple[int, int, int, int], Image.Image, int, int, int, list[str]]] = []
    for component, metric in enumerate(metrics):
        if metric["right"] < metric["left"] or metric["bottom"] < metric["top"]:
            continue
        bbox = (
            int(metric["left"]),
            int(metric["top"]),
            int(metric["right"]) + 1,
            int(metric["bottom"]) + 1,
        )
        crop = _masked_crop(rgba, labels, component, bbox)
        assigned = int(metric["assigned"])
        weak = int(metric["weak"])
        bbox_area = crop.width * crop.height
        flags: list[str] = []
        if bbox[0] == 0 or bbox[1] == 0 or bbox[2] == width or bbox[3] == height:
            flags.append("touching_source_edge")
        if strong_counts[component] < max(64, selected.min_strong_pixels * 4):
            flags.append("small_instance_review")
        if assigned and weak / assigned > 0.30:
            flags.append("high_weak_alpha_ratio")
        if bbox_area and assigned / bbox_area < 0.06:
            flags.append("sparse_shape_review")
        if conflicts[component] > 0:
            flags.append("neighbor_alpha_conflict")
        fingerprint = item_content_sha256(crop)
        provisional.append(
            (
                fingerprint,
                bbox,
                crop,
                strong_counts[component],
                assigned,
                weak,
                flags,
            )
        )

    provisional.sort(key=lambda entry: (entry[1][1], entry[1][0], entry[1][3], entry[1][2]))
    occurrences: defaultdict[str, int] = defaultdict(int)
    extracted: list[ExtractedItem] = []
    for fingerprint, bbox, crop, strong, assigned, weak, flags in provisional:
        occurrence = occurrences[fingerprint]
        occurrences[fingerprint] += 1
        item_id = f"item_{fingerprint[:12]}"
        if occurrence:
            item_id += f"_{occurrence + 1:02d}"
        extracted.append(
            ExtractedItem(
                item_id=item_id,
                content_sha256=fingerprint,
                source_bbox=bbox,
                image=crop,
                strong_pixels=strong,
                assigned_pixels=assigned,
                weak_pixels=weak,
                qa_flags=flags,
            )
        )
    if not extracted:
        raise ItemSheetError("segmentation produced no usable items")
    return extracted


def _snap(value: int, quantum: int) -> int:
    return max(quantum, math.ceil(value / quantum) * quantum)


def _intersects(left: _Rect, right: _Rect) -> bool:
    return not (
        left.right <= right.x
        or right.right <= left.x
        or left.bottom <= right.y
        or right.bottom <= left.y
    )


def _contains(outer: _Rect, inner: _Rect) -> bool:
    return (
        outer.x <= inner.x
        and outer.y <= inner.y
        and outer.right >= inner.right
        and outer.bottom >= inner.bottom
    )


def pack_items(
    items: Sequence[ExtractedItem],
    config: PackingConfig | None = None,
) -> tuple[dict[str, _Rect], tuple[int, int], dict[str, tuple[int, int]]]:
    """Pack variable rectangular cells without rotation or image scaling."""

    selected = config or PackingConfig()
    selected.validate()
    if not items:
        raise ItemSheetError("at least one item is required for packing")
    footprints_by_id = {
        item.item_id: (
            _snap(item.width + selected.padding * 2, selected.quantum),
            _snap(item.height + selected.padding * 2, selected.quantum),
        )
        for item in items
    }
    footprints = [
        (item.item_id, *footprints_by_id[item.item_id])
        for item in sorted(
            items,
            key=lambda entry: (
                -(footprints_by_id[entry.item_id][0] * footprints_by_id[entry.item_id][1]),
                -max(footprints_by_id[entry.item_id]),
                -footprints_by_id[entry.item_id][1],
                entry.item_id,
            ),
        )
    ]
    max_cell_width = max(width for _, width, _ in footprints)
    total_area = sum(width * height for _, width, height in footprints)
    width = _snap(max(max_cell_width, math.ceil(math.sqrt(total_area))), selected.quantum)
    if selected.max_width:
        available = selected.max_width - selected.outer_padding * 2
        width = min(width, available - available % selected.quantum)
        if max_cell_width > width:
            raise ItemSheetError("items cannot fit inside max_width")
    raw_placements: dict[str, _Rect] = {}
    x = y = row_height = 0
    for item_id, item_width, item_height in footprints:
        if x and x + item_width > width:
            x = 0
            y += row_height
            row_height = 0
        raw_placements[item_id] = _Rect(x, y, item_width, item_height)
        x += item_width
        row_height = max(row_height, item_height)
    height = y + row_height
    offset = selected.outer_padding
    placements = {
        item_id: _Rect(rect.x + offset, rect.y + offset, rect.w, rect.h)
        for item_id, rect in raw_placements.items()
    }
    return (
        placements,
        (width + offset * 2, height + offset * 2),
        footprints_by_id,
    )


def _draw_source_overlay(source: Image.Image, items: Sequence[ExtractedItem]) -> Image.Image:
    preview = source.convert("RGBA").copy()
    draw = ImageDraw.Draw(preview)
    for index, item in enumerate(items, start=1):
        left, top, right, bottom = item.source_bbox
        draw.rectangle((left, top, right - 1, bottom - 1), outline=(255, 186, 70, 255), width=2)
        label = f"{index:03d} {item.item_id[-6:]}"
        text_box = draw.textbbox((left + 2, top + 2), label)
        draw.rectangle(text_box, fill=(10, 10, 10, 220))
        draw.text((left + 2, top + 2), label, fill=(255, 240, 205, 255))
    return preview


def _checker(size: tuple[int, int], tile: int = 16) -> Image.Image:
    image = Image.new("RGBA", size, (36, 36, 34, 255))
    draw = ImageDraw.Draw(image)
    for y in range(0, size[1], tile):
        for x in range(0, size[0], tile):
            if (x // tile + y // tile) % 2:
                draw.rectangle((x, y, x + tile - 1, y + tile - 1), fill=(55, 55, 51, 255))
    return image


def compose_atlas(
    items: Sequence[ExtractedItem],
    placements: Mapping[str, _Rect],
    atlas_size: tuple[int, int],
) -> tuple[Image.Image, Image.Image, dict[str, dict[str, int]]]:
    atlas = Image.new("RGBA", atlas_size, (0, 0, 0, 0))
    debug = _checker(atlas_size)
    draw = ImageDraw.Draw(debug)
    frames: dict[str, dict[str, int]] = {}

    for item in items:
        cell = placements[item.item_id]
        frame_x = cell.x + (cell.w - item.width) // 2
        frame_y = cell.y + (cell.h - item.height) // 2
        atlas.paste(item.image, (frame_x, frame_y))
        debug.alpha_composite(item.image, (frame_x, frame_y))
        draw.rectangle(
            (cell.x, cell.y, cell.right - 1, cell.bottom - 1),
            outline=(215, 168, 95, 255),
            width=1,
        )
        draw.rectangle(
            (frame_x, frame_y, frame_x + item.width - 1, frame_y + item.height - 1),
            outline=(189, 207, 115, 255),
            width=1,
        )
        draw.text((cell.x + 3, cell.y + 3), item.item_id[-6:], fill=(245, 239, 220, 255))
        frames[item.item_id] = {
            "x": frame_x,
            "y": frame_y,
            "w": item.width,
            "h": item.height,
        }
    return atlas, debug, frames


def _classification_stub() -> dict[str, Any]:
    return {
        "family": "unknown",
        "canonicalType": "unknown",
        "subtype": None,
        "materials": [],
        "condition": [],
        "orientation": "unknown",
        "sizeClass": "unknown",
        "tags": [],
        "confidence": 0.0,
        "source": "unclassified",
    }


def reconstruct_source_reference(
    size: tuple[int, int],
    items: Sequence[ExtractedItem],
) -> Image.Image:
    """Reconstruct the exact accepted source pixels represented by ``items``."""

    reference = Image.new("RGBA", size, (0, 0, 0, 0))
    for item in items:
        left, top, right, bottom = item.source_bbox
        if right - left != item.width or bottom - top != item.height:
            raise ItemSheetError(f"{item.item_id}: source bbox does not match native item size")
        if left < 0 or top < 0 or right > size[0] or bottom > size[1]:
            raise ItemSheetError(f"{item.item_id}: source bbox exceeds the source canvas")
        reference.alpha_composite(item.image.convert("RGBA"), (left, top))
    return reference


def build_pixel_ownership_report(
    source_reference: Image.Image,
    items: Sequence[ExtractedItem],
) -> dict[str, Any]:
    """Prove that every emitted non-transparent item pixel has one exact owner."""

    source = source_reference.convert("RGBA")
    width, height = source.size
    source_bytes = source.tobytes()
    owners = bytearray(width * height)
    duplicates = 0
    out_of_bounds = 0
    rgba_mismatches = 0
    per_item: list[dict[str, Any]] = []

    for item in items:
        rgba = item.image.convert("RGBA")
        item_bytes = rgba.tobytes()
        left, top, _right, _bottom = item.source_bbox
        assigned = 0
        for local_y in range(rgba.height):
            source_y = top + local_y
            for local_x in range(rgba.width):
                pixel_offset = (local_y * rgba.width + local_x) * 4
                if item_bytes[pixel_offset + 3] == 0:
                    continue
                assigned += 1
                source_x = left + local_x
                if not (0 <= source_x < width and 0 <= source_y < height):
                    out_of_bounds += 1
                    continue
                source_index = source_y * width + source_x
                if owners[source_index] == 1:
                    duplicates += 1
                    owners[source_index] = 2
                elif owners[source_index] == 0:
                    owners[source_index] = 1
                source_offset = source_index * 4
                if item_bytes[pixel_offset : pixel_offset + 4] != source_bytes[
                    source_offset : source_offset + 4
                ]:
                    rgba_mismatches += 1
        per_item.append({"itemId": item.item_id, "ownedPixels": assigned})

    source_alpha_pixels = 0
    unowned_source_alpha_pixels = 0
    unique_owned_pixels = 0
    ownership_mask = bytearray(width * height)
    for index, owner_count in enumerate(owners):
        if source_bytes[index * 4 + 3] > 0:
            source_alpha_pixels += 1
            if owner_count == 0:
                unowned_source_alpha_pixels += 1
        if owner_count > 0:
            unique_owned_pixels += 1
            ownership_mask[index] = 255

    complete = duplicates == 0 and out_of_bounds == 0 and rgba_mismatches == 0
    return {
        "schemaVersion": "item-pixel-ownership-report-v1",
        "acceptedPixelDefinition": "non-transparent pixels emitted by item artifacts",
        "sourceSize": [width, height],
        "sourceAlphaPixels": source_alpha_pixels,
        "ownedPixels": unique_owned_pixels,
        "unownedSourceAlphaPixels": unowned_source_alpha_pixels,
        "duplicateOwnershipPixels": duplicates,
        "outOfBoundsAssignments": out_of_bounds,
        "rgbaMismatchPixels": rgba_mismatches,
        "ownershipMaskSha256": _digest_bytes(bytes(ownership_mask)),
        "ownershipComplete": complete,
        "allSourcePixelsAssigned": complete and unowned_source_alpha_pixels == 0,
        "items": per_item,
    }


def _validate_output_dir(output: Path, force: bool) -> None:
    if output == Path(output.anchor):
        raise ItemSheetError("output directory cannot be a filesystem root")
    try:
        if output.exists() and not output.is_dir():
            raise ItemSheetError("output path exists and is not a directory")
        if output.exists() and any(output.iterdir()) and not force:
            raise ItemSheetError("output directory is not empty; pass force to replace it")
    except OSError as exc:
        raise ItemSheetError(f"cannot inspect output directory: {exc}") from exc


def write_item_atlas_run(
    items: Sequence[ExtractedItem],
    output_dir: Path,
    *,
    source: Mapping[str, Any],
    source_reference: Image.Image,
    segmentation: Mapping[str, Any],
    packing: PackingConfig | None = None,
    parent_manifest_sha256: str | None = None,
    item_overrides: Mapping[str, Mapping[str, Any]] | None = None,
    manifest_extra: Mapping[str, Any] | None = None,
    completion: Mapping[str, bool] | None = None,
    discarded_mask: Image.Image | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Write a complete, atomically replaceable atlas run from exact item pixels."""

    if not items:
        raise ItemSheetError("at least one item is required")
    output = Path(output_dir).expanduser().resolve()
    _validate_output_dir(output, force)
    selected_packing = packing or PackingConfig()
    selected_packing.validate()
    source_record = deepcopy(dict(source))
    required_source = {"path", "sha256", "width", "height", "mode", "provenance"}
    if not required_source.issubset(source_record):
        raise ItemSheetError("source record is incomplete")
    if source_record.get("mode") != "RGBA":
        raise ItemSheetError("source mode must be RGBA")
    if source_reference.size != (source_record.get("width"), source_record.get("height")):
        raise ItemSheetError("source reference dimensions do not match the source record")
    if source_record.get("provenance") not in {
        "imagegen",
        "grok-imagine-image",
        "imported",
        "fixture",
        "mixed",
    }:
        raise ItemSheetError(f"unsupported source provenance: {source_record.get('provenance')}")
    if not isinstance(source_record.get("sha256"), str) or len(source_record["sha256"]) != 64:
        raise ItemSheetError("source sha256 is invalid")
    if parent_manifest_sha256 is not None and len(parent_manifest_sha256) != 64:
        raise ItemSheetError("parent manifest sha256 is invalid")

    seen_ids: set[str] = set()
    for item in items:
        if item.item_id in seen_ids:
            raise ItemSheetError(f"duplicate item id: {item.item_id}")
        seen_ids.add(item.item_id)
        if item.image.mode != "RGBA":
            item.image = item.image.convert("RGBA")
        if item.content_sha256 != item_content_sha256(item.image):
            raise ItemSheetError(f"{item.item_id}: content SHA-256 does not match native RGBA bytes")

    ownership = build_pixel_ownership_report(source_reference, items)
    if not ownership["ownershipComplete"]:
        raise ItemSheetError(
            "pixel ownership failed: "
            f"duplicates={ownership['duplicateOwnershipPixels']}, "
            f"out_of_bounds={ownership['outOfBoundsAssignments']}, "
            f"rgba_mismatches={ownership['rgbaMismatchPixels']}"
        )

    placements, atlas_size, footprints = pack_items(items, selected_packing)
    atlas, debug_atlas, frames = compose_atlas(items, placements, atlas_size)
    segmentation_record = deepcopy(dict(segmentation))
    segmentation_record["itemCount"] = len(items)
    overrides = item_overrides or {}

    staging: Path | None = None
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.tmp-", dir=output.parent))
        item_dir = staging / "items"
        inference_dir = staging / "inference"
        qa_dir = staging / "qa"
        item_dir.mkdir()
        inference_dir.mkdir()
        qa_dir.mkdir()
        _atomic_image(staging / "source.png", source_reference)
        occupied = Image.new("L", source_reference.size, 0)
        for item in items:
            occupied.paste(255, (item.source_bbox[0], item.source_bbox[1]), item.image.getchannel("A").point(lambda a: 255 if a else 0))
        from PIL import ImageChops
        visible = source_reference.getchannel("A").point(lambda a: 255 if a else 0)
        discarded = discarded_mask.convert("L").point(lambda a: 255 if a else 0) if discarded_mask is not None else Image.new("L", visible.size, 0)
        if discarded.size != visible.size or ImageChops.multiply(occupied, discarded).getbbox():
            raise ItemSheetError("discarded pixels overlap owned pixels or have invalid dimensions")
        discarded = ImageChops.multiply(discarded, visible)
        pending = ImageChops.subtract(ImageChops.subtract(visible, occupied), discarded)
        _atomic_image(qa_dir / "pending-mask.png", pending)
        _atomic_image(qa_dir / "discarded-mask.png", discarded)
        ownership["pendingPixels"] = pending.histogram()[255]
        ownership["discardedPixels"] = discarded.histogram()[255]
        ownership["accountedSourcePixels"] = ownership["ownedPixels"] + ownership["pendingPixels"] + ownership["discardedPixels"]

        item_records: list[dict[str, Any]] = []
        for item in items:
            relative_item = f"items/{item.item_id}.png"
            item_path = staging / relative_item
            _atomic_image(item_path, item.image)

            light = Image.new("RGB", item.image.size, (238, 238, 232))
            dark = Image.new("RGB", item.image.size, (28, 28, 27))
            light.paste(item.image.convert("RGB"), mask=item.image.getchannel("A"))
            dark.paste(item.image.convert("RGB"), mask=item.image.getchannel("A"))
            light_path = staging / f"inference/{item.item_id}-light.png"
            dark_path = staging / f"inference/{item.item_id}-dark.png"
            _atomic_image(light_path, light)
            _atomic_image(dark_path, dark)

            cell = placements[item.item_id]
            frame = frames[item.item_id]
            cell_width, cell_height = footprints[item.item_id]
            override = deepcopy(dict(overrides.get(item.item_id, {})))
            source_override = override.get("source")
            item_source: dict[str, Any] = {
                "bbox": list(item.source_bbox),
                "strongPixels": item.strong_pixels,
                "assignedPixels": item.assigned_pixels,
                "weakPixels": item.weak_pixels,
            }
            if isinstance(source_override, Mapping):
                for key, value in source_override.items():
                    if key not in {"bbox", "strongPixels", "assignedPixels", "weakPixels"}:
                        item_source[key] = deepcopy(value)
            if item.lineage:
                item_source["lineage"] = deepcopy(item.lineage)
            item_record: dict[str, Any] = {
                "id": item.item_id,
                "contentSha256": item.content_sha256,
                "source": item_source,
                "artifacts": {
                    "rgba": relative_item,
                    "lightComposite": f"inference/{item.item_id}-light.png",
                    "darkComposite": f"inference/{item.item_id}-dark.png",
                    "sha256": _digest_file(item_path),
                },
                "geometry": {
                    "originalSize": [item.width, item.height],
                    "cellRect": [cell.x, cell.y, cell_width, cell_height],
                    "frame": [frame["x"], frame["y"], frame["w"], frame["h"]],
                    "pivot": deepcopy(override.get("geometry", {}).get("pivot", [0.5, 0.5]))
                    if isinstance(override.get("geometry"), Mapping)
                    else [0.5, 0.5],
                    "scale": 1,
                    "rotated": False,
                },
                "classification": deepcopy(override.get("classification", _classification_stub())),
                "review": deepcopy(
                    override.get(
                        "review",
                        {"status": "pending", "notes": "", "replacement": None},
                    )
                ),
                "qaFlags": list(
                    dict.fromkeys(
                        [
                            *item.qa_flags,
                            *(override.get("qaFlags", []) if isinstance(override.get("qaFlags"), list) else []),
                        ]
                    )
                ),
            }
            controlled = {
                "id",
                "contentSha256",
                "source",
                "artifacts",
                "geometry",
                "classification",
                "review",
                "qaFlags",
            }
            for key, value in override.items():
                if key not in controlled:
                    item_record[key] = deepcopy(value)
            item_records.append(item_record)

        atlas_path = staging / "atlas.png"
        debug_path = qa_dir / "atlas-grid.png"
        source_overlay_path = qa_dir / "source-components.png"
        ownership_path = qa_dir / "pixel-ownership-report.json"
        _atomic_image(atlas_path, atlas)
        _atomic_image(debug_path, debug_atlas)
        _atomic_image(source_overlay_path, _draw_source_overlay(source_reference, items))
        _atomic_json(ownership_path, ownership)

        run_fingerprint = _digest_bytes(
            json.dumps(
                {
                    "source": source_record["sha256"],
                    "segmentation": segmentation_record,
                    "packing": asdict(selected_packing),
                    "items": [
                        {
                            "id": item.item_id,
                            "sha256": item.content_sha256,
                            "sourceBBox": list(item.source_bbox),
                        }
                        for item in items
                    ],
                    "parentManifestSha256": parent_manifest_sha256,
                    "manifestExtra": manifest_extra or {},
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        manifest: dict[str, Any] = {
            "schemaVersion": "deterministic-item-sheet-v1",
            "kind": "deterministic-item-atlas",
            "runId": f"item-atlas-{run_fingerprint[:16]}",
            "inputFingerprint": run_fingerprint,
            "parentManifestSha256": parent_manifest_sha256,
            "source": source_record,
            "segmentation": segmentation_record,
            "packing": {
                **asdict(selected_packing),
                "algorithm": "size-ordered-shelves",
                "sort": ["cell-area-desc", "max-side-desc", "height-desc", "stable-id"],
                "rotation": False,
                "rescale": False,
            },
            "atlas": {
                "path": "atlas.png",
                "width": atlas.width,
                "height": atlas.height,
                "sha256": _digest_file(atlas_path),
            },
            "items": item_records,
            "evidence": {
                "sourceComponents": "qa/source-components.png",
                "atlasGrid": "qa/atlas-grid.png",
                "pixelOwnership": "qa/pixel-ownership-report.json",
                "sourceRgba": "source.png",
                "sourceRgbaSha256": _digest_file(staging / "source.png"),
                "pendingMask": "qa/pending-mask.png",
                "discardedMask": "qa/discarded-mask.png",
            },
            "completion": {
                "geometryBuilt": True,
                "classificationComplete": False,
                "reviewComplete": False,
                "pendingPixels": ownership["pendingPixels"],
                **(dict(completion) if completion else {}),
            },
        }
        if manifest_extra:
            protected = set(manifest)
            for key, value in manifest_extra.items():
                if key in protected:
                    raise ItemSheetError(f"manifest extra cannot replace {key}")
                manifest[key] = deepcopy(value)
        manifest["completion"]["reviewGatePassed"] = ownership["pendingPixels"] == 0 and not any(
            item["qaFlags"] and item["review"]["status"] != "approved" for item in item_records)
        manifest["completion"]["reviewComplete"] = ownership["pendingPixels"] == 0 and all(
            item["review"]["status"] == "approved" for item in item_records)
        _atomic_json(staging / "manifest.json", manifest)
        if output.exists():
            if any(output.iterdir()) and not force:
                raise ItemSheetError("output directory changed during atlas compilation")
            shutil.rmtree(output)
        staging.replace(output)
        staging = None
        return manifest
    except OSError as exc:
        raise ItemSheetError(f"cannot write atlas output: {exc}") from exc
    finally:
        if staging is not None and staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def build_item_atlas(
    source_path: Path,
    output_dir: Path,
    *,
    segmentation: SegmentationConfig | None = None,
    packing: PackingConfig | None = None,
    provenance: str,
    force: bool = False,
) -> dict[str, Any]:
    """Compile one RGBA item sheet and return its manifest."""

    source = Path(source_path).expanduser().resolve()
    output = Path(output_dir).expanduser().resolve()
    if not source.is_file():
        raise ItemSheetError(f"source image does not exist: {source}")
    if source.is_relative_to(output):
        raise ItemSheetError("output directory cannot contain the source image")
    _validate_output_dir(output, force)

    selected_segmentation = segmentation or SegmentationConfig()
    selected_packing = packing or PackingConfig()
    selected_segmentation.validate()
    selected_packing.validate()
    try:
        with Image.open(source) as opened:
            opened.load()
            source_image = opened.convert("RGBA")
    except OSError as exc:
        raise ItemSheetError(f"source is not a decodable image: {source}") from exc

    items = segment_items(source_image, selected_segmentation)
    return write_item_atlas_run(
        items,
        output,
        source={
            "path": source.name,
            "sha256": _digest_file(source),
            "width": source_image.width,
            "height": source_image.height,
            "mode": "RGBA",
            "provenance": provenance,
        },
        source_reference=source_image,
        segmentation={
            **asdict(selected_segmentation),
            "method": "alpha-hysteresis-connected-components",
        },
        packing=selected_packing,
        force=force,
    )


def validate_manifest_geometry(manifest: Mapping[str, Any]) -> list[str]:
    """Return geometry errors without mutating the manifest."""

    errors: list[str] = []
    atlas = manifest.get("atlas")
    items = manifest.get("items")
    if not isinstance(atlas, Mapping) or not isinstance(items, list):
        return ["manifest requires atlas and items"]
    width = atlas.get("width")
    height = atlas.get("height")
    if not isinstance(width, int) or not isinstance(height, int):
        return ["atlas dimensions must be integers"]
    packing = manifest.get("packing")
    padding = packing.get("padding", 0) if isinstance(packing, Mapping) else 0
    quantum = packing.get("quantum", 1) if isinstance(packing, Mapping) else 1
    outer_padding = packing.get("outer_padding", 0) if isinstance(packing, Mapping) else 0
    if not isinstance(padding, int) or padding < 0:
        errors.append("packing padding must be a non-negative integer")
        padding = 0
    if not isinstance(quantum, int) or quantum < 1:
        errors.append("packing quantum must be a positive integer")
        quantum = 1
    if not isinstance(outer_padding, int) or outer_padding < 0:
        errors.append("packing outer_padding must be a non-negative integer")
        outer_padding = 0

    cells: list[tuple[str, _Rect]] = []
    for item in items:
        if not isinstance(item, Mapping):
            errors.append("item must be an object")
            continue
        item_id = str(item.get("id", "<missing>"))
        geometry = item.get("geometry")
        if not isinstance(geometry, Mapping):
            errors.append(f"{item_id}: geometry missing")
            continue
        cell = geometry.get("cellRect")
        frame = geometry.get("frame")
        if not (
            isinstance(cell, list)
            and len(cell) == 4
            and all(isinstance(value, int) for value in cell)
        ):
            errors.append(f"{item_id}: invalid cellRect")
            continue
        if not (
            isinstance(frame, list)
            and len(frame) == 4
            and all(isinstance(value, int) for value in frame)
        ):
            errors.append(f"{item_id}: invalid frame")
            continue
        cell_rect = _Rect(*cell)
        frame_rect = _Rect(*frame)
        if cell_rect.x < 0 or cell_rect.y < 0 or cell_rect.right > width or cell_rect.bottom > height:
            errors.append(f"{item_id}: cellRect exceeds atlas")
        if not _contains(cell_rect, frame_rect):
            errors.append(f"{item_id}: frame is not contained by cellRect")
        elif min(
            frame_rect.x - cell_rect.x,
            frame_rect.y - cell_rect.y,
            cell_rect.right - frame_rect.right,
            cell_rect.bottom - frame_rect.bottom,
        ) < padding:
            errors.append(f"{item_id}: frame does not preserve configured padding")
        if cell_rect.w % quantum or cell_rect.h % quantum:
            errors.append(f"{item_id}: cell dimensions are not quantum-aligned")
        if (cell_rect.x - outer_padding) % quantum or (cell_rect.y - outer_padding) % quantum:
            errors.append(f"{item_id}: cell position is not quantum-aligned")
        if geometry.get("scale") != 1:
            errors.append(f"{item_id}: scale must remain 1")
        if geometry.get("rotated") is not False:
            errors.append(f"{item_id}: rotation must remain disabled")
        cells.append((item_id, cell_rect))

    for index, (left_id, left) in enumerate(cells):
        for right_id, right in cells[index + 1 :]:
            if _intersects(left, right):
                errors.append(f"{left_id} overlaps {right_id}")
    return errors


__all__ = [
    "ExtractedItem",
    "ItemSheetError",
    "PackingConfig",
    "SegmentationConfig",
    "build_pixel_ownership_report",
    "build_item_atlas",
    "compose_atlas",
    "item_content_sha256",
    "pack_items",
    "reconstruct_source_reference",
    "segment_items",
    "unique_item_id",
    "validate_manifest_geometry",
    "write_item_atlas_run",
]
