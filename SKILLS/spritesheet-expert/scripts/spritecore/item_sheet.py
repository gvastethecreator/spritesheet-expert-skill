"""Deterministic segmentation and rectangular packing for irregular item sheets.

The module deliberately owns geometry only. It never invents semantic pixels and
never invokes a paid or remote model. Classification and regeneration are
portable handoffs applied after extraction.
"""

from __future__ import annotations

from array import array
from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import math
from pathlib import Path
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
        if not 0 <= self.alpha_low <= self.alpha_high:
            raise ItemSheetError("alpha_low must be between 0 and alpha_high")
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
    max_width: int = 4096
    outer_padding: int = 0
    extrude: int = 0

    def validate(self) -> None:
        if self.quantum < 1:
            raise ItemSheetError("quantum must be positive")
        if self.padding < 0:
            raise ItemSheetError("padding cannot be negative")
        if self.max_width < self.quantum:
            raise ItemSheetError("max_width must be at least one quantum")
        if self.outer_padding < 0:
            raise ItemSheetError("outer_padding cannot be negative")
        if self.extrude < 0 or self.extrude > self.padding:
            raise ItemSheetError("extrude must be between zero and padding")


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
        fingerprint = _digest_bytes(
            crop.width.to_bytes(4, "big")
            + crop.height.to_bytes(4, "big")
            + crop.tobytes()
        )
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


def _split_free(free: _Rect, used: _Rect) -> list[_Rect]:
    if not _intersects(free, used):
        return [free]
    result: list[_Rect] = []
    if used.x > free.x:
        result.append(_Rect(free.x, free.y, used.x - free.x, free.h))
    if used.right < free.right:
        result.append(_Rect(used.right, free.y, free.right - used.right, free.h))
    if used.y > free.y:
        result.append(_Rect(free.x, free.y, free.w, used.y - free.y))
    if used.bottom < free.bottom:
        result.append(_Rect(free.x, used.bottom, free.w, free.bottom - used.bottom))
    return [rect for rect in result if rect.w > 0 and rect.h > 0]


def _prune_free(rectangles: list[_Rect]) -> list[_Rect]:
    unique = list(dict.fromkeys(rectangles))
    kept: list[_Rect] = []
    for index, candidate in enumerate(unique):
        if any(index != other and _contains(container, candidate) for other, container in enumerate(unique)):
            continue
        kept.append(candidate)
    return kept


def _pack_width(
    footprints: Sequence[tuple[str, int, int]],
    width: int,
    quantum: int,
) -> tuple[dict[str, _Rect], int] | None:
    if any(item_width > width for _, item_width, _ in footprints):
        return None
    safe_height = sum(item_height for _, _, item_height in footprints)
    free = [_Rect(0, 0, width, safe_height)]
    placements: dict[str, _Rect] = {}

    for item_id, item_width, item_height in footprints:
        candidates: list[tuple[int, int, int, int, int, _Rect]] = []
        for rect in free:
            if item_width <= rect.w and item_height <= rect.h:
                leftover_horizontal = rect.w - item_width
                leftover_vertical = rect.h - item_height
                candidates.append(
                    (
                        min(leftover_horizontal, leftover_vertical),
                        max(leftover_horizontal, leftover_vertical),
                        rect.y,
                        rect.x,
                        rect.w * rect.h,
                        rect,
                    )
                )
        if not candidates:
            return None
        selected = min(candidates)[-1]
        used = _Rect(selected.x, selected.y, item_width, item_height)
        placements[item_id] = used
        next_free: list[_Rect] = []
        for rectangle in free:
            next_free.extend(_split_free(rectangle, used))
        free = _prune_free(next_free)

    height = _snap(max(rect.bottom for rect in placements.values()), quantum)
    return placements, height


def pack_items(
    items: Sequence[ExtractedItem],
    config: PackingConfig | None = None,
) -> tuple[dict[str, _Rect], tuple[int, int], dict[str, tuple[int, int]]]:
    """Pack variable rectangular cells without rotation or image scaling."""

    selected = config or PackingConfig()
    selected.validate()
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
    minimum = _snap(max_cell_width, selected.quantum)
    maximum = _snap(max(minimum, selected.max_width), selected.quantum)
    ideal = _snap(max(minimum, math.ceil(math.sqrt(total_area))), selected.quantum)

    candidate_widths = set(range(minimum, maximum + 1, selected.quantum))
    candidate_widths.update(
        _snap(value, selected.quantum)
        for value in (
            ideal,
            256,
            512,
            1024,
            1536,
            2048,
            3072,
            4096,
        )
        if minimum <= value <= maximum
    )

    best: tuple[tuple[int, int, int], dict[str, _Rect], int, int] | None = None
    for width in sorted(candidate_widths):
        packed = _pack_width(footprints, width, selected.quantum)
        if packed is None:
            continue
        placements, height = packed
        score = (width * height, abs(width - height), width)
        if best is None or score < best[0]:
            best = (score, placements, width, height)
    if best is None:
        raise ItemSheetError("items cannot fit inside max_width")

    _, raw_placements, width, height = best
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
    packing: PackingConfig,
) -> tuple[Image.Image, Image.Image, dict[str, dict[str, int]]]:
    atlas = Image.new("RGBA", atlas_size, (0, 0, 0, 0))
    debug = _checker(atlas_size)
    draw = ImageDraw.Draw(debug)
    frames: dict[str, dict[str, int]] = {}

    for item in items:
        cell = placements[item.item_id]
        frame_x = cell.x + (cell.w - item.width) // 2
        frame_y = cell.y + (cell.h - item.height) // 2
        atlas.alpha_composite(item.image, (frame_x, frame_y))
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


def build_item_atlas(
    source_path: Path,
    output_dir: Path,
    *,
    segmentation: SegmentationConfig | None = None,
    packing: PackingConfig | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Compile one RGBA item sheet and return its manifest."""

    source = Path(source_path).expanduser().resolve()
    output = Path(output_dir).expanduser().resolve()
    if not source.is_file():
        raise ItemSheetError(f"source image does not exist: {source}")
    manifest_path = output / "manifest.json"
    if manifest_path.exists() and not force:
        raise ItemSheetError("output already contains a manifest; pass force to replace known outputs")

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
    placements, atlas_size, footprints = pack_items(items, selected_packing)
    atlas, debug_atlas, frames = compose_atlas(items, placements, atlas_size, selected_packing)

    output.mkdir(parents=True, exist_ok=True)
    item_dir = output / "items"
    inference_dir = output / "inference"
    qa_dir = output / "qa"
    item_dir.mkdir(parents=True, exist_ok=True)
    inference_dir.mkdir(parents=True, exist_ok=True)
    qa_dir.mkdir(parents=True, exist_ok=True)

    item_records: list[dict[str, Any]] = []
    for item in items:
        relative_item = f"items/{item.item_id}.png"
        item_path = output / relative_item
        _atomic_image(item_path, item.image)

        light = Image.new("RGB", item.image.size, (238, 238, 232))
        dark = Image.new("RGB", item.image.size, (28, 28, 27))
        light.paste(item.image.convert("RGB"), mask=item.image.getchannel("A"))
        dark.paste(item.image.convert("RGB"), mask=item.image.getchannel("A"))
        light_path = output / f"inference/{item.item_id}-light.png"
        dark_path = output / f"inference/{item.item_id}-dark.png"
        _atomic_image(light_path, light)
        _atomic_image(dark_path, dark)

        cell = placements[item.item_id]
        frame = frames[item.item_id]
        cell_width, cell_height = footprints[item.item_id]
        item_records.append(
            {
                "id": item.item_id,
                "contentSha256": item.content_sha256,
                "source": {
                    "bbox": list(item.source_bbox),
                    "strongPixels": item.strong_pixels,
                    "assignedPixels": item.assigned_pixels,
                    "weakPixels": item.weak_pixels,
                },
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
                    "pivot": [0.5, 0.5],
                    "scale": 1,
                    "rotated": False,
                },
                "classification": _classification_stub(),
                "review": {
                    "status": "pending",
                    "notes": "",
                    "replacement": None,
                },
                "qaFlags": item.qa_flags,
            }
        )

    atlas_path = output / "atlas.png"
    debug_path = qa_dir / "atlas-grid.png"
    source_overlay_path = qa_dir / "source-components.png"
    _atomic_image(atlas_path, atlas)
    _atomic_image(debug_path, debug_atlas)
    _atomic_image(source_overlay_path, _draw_source_overlay(source_image, items))

    source_sha = _digest_file(source)
    run_fingerprint = _digest_bytes(
        json.dumps(
            {
                "source": source_sha,
                "segmentation": asdict(selected_segmentation),
                "packing": asdict(selected_packing),
                "items": [item.content_sha256 for item in items],
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
        "parentManifestSha256": None,
        "source": {
            "path": source.name,
            "sha256": source_sha,
            "width": source_image.width,
            "height": source_image.height,
            "mode": "RGBA",
            "provenance": "imported",
        },
        "segmentation": {
            **asdict(selected_segmentation),
            "method": "alpha-hysteresis-connected-components",
            "itemCount": len(item_records),
        },
        "packing": {
            **asdict(selected_packing),
            "algorithm": "maxrects-best-short-side-fit",
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
        },
        "completion": {
            "geometryBuilt": True,
            "classificationComplete": False,
            "reviewComplete": False,
        },
    }
    _atomic_json(manifest_path, manifest)
    return manifest


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
    "build_item_atlas",
    "compose_atlas",
    "pack_items",
    "segment_items",
    "validate_manifest_geometry",
]
