"""Independent, fail-closed validation of a deterministic item-atlas delivery.

No inference, pixel repair, or implicit approval. Check disk artifacts rather than
trusting completion booleans. Drafts may be unreviewed, but may not be corrupt.
"""
from __future__ import annotations

from hashlib import sha256
import json
import math
from pathlib import Path, PurePosixPath
import re
from typing import Any

from PIL import Image, ImageChops

MAX_PIXELS = 50_000_000
MAX_FILE_BYTES = 256 * 1024 * 1024
HARD_FLAGS = frozenset({"touching_source_edge"})
STATUSES = frozenset({"pending", "approved", "rejected", "replace", "regenerate"})


class DeliveryError(ValueError):
    """The artifact set is structurally invalid or no longer matches its manifest."""


def digest_file(path: Path) -> str:
    with path.open("rb") as stream:
        return sha256(stream.read()).hexdigest()


def artifact(root: Path, relative: Any) -> Path:
    """Resolve an exact portable path; never guess by basename or follow symlinks."""
    if not isinstance(relative, str) or not relative or "\\" in relative or ":" in relative:
        raise DeliveryError("artifact path must be a portable relative path")
    parts = PurePosixPath(relative).parts
    if not parts or relative.startswith("/") or any(p in {"..", "."} for p in parts):
        raise DeliveryError(f"unsafe artifact path: {relative!r}")
    root = root.resolve()
    candidate = root
    for part in parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise DeliveryError(f"symlink artifact is not permitted: {relative}")
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise DeliveryError(f"missing or escaping artifact: {relative}")
    if resolved.stat().st_size > MAX_FILE_BYTES:
        raise DeliveryError(f"artifact exceeds byte budget: {relative}")
    return resolved


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DeliveryError(message)


def _integer(value: Any, name: str, minimum: int = 0) -> int:
    _require(type(value) is int and value >= minimum, f"{name}: invalid integer")
    return value


def _rect(value: Any, name: str, *, corners: bool = False) -> tuple[int, int, int, int]:
    _require(isinstance(value, list) and len(value) == 4, f"{name}: expected four integers")
    x, y, a, b = [_integer(n, name) for n in value]
    w, h = (a - x, b - y) if corners else (a, b)
    _require(w > 0 and h > 0, f"{name}: dimensions must be positive")
    return x, y, w, h


def _same(left: Image.Image, right: Image.Image) -> bool:
    return left.mode == right.mode and left.size == right.size and all(
        band.getbbox() is None for band in ImageChops.difference(left, right).split())


def _visible(image: Image.Image) -> Image.Image:
    return image.getchannel("A").point(lambda a: 255 if a else 0)


def _read_image(path: Path, *, mask: bool = False) -> Image.Image:
    with Image.open(path) as opened:
        _require(opened.width * opened.height <= MAX_PIXELS, f"image exceeds pixel budget: {path.name}")
        _require(getattr(opened, "n_frames", 1) == 1, f"animated image is not an item artifact: {path.name}")
        _require(opened.mode == ("L" if mask else "RGBA"), f"unexpected image mode: {path.name}")
        opened.load()
        result = opened.copy()
    if mask:
        hist = result.histogram()
        _require(sum(hist[1:255]) == 0, f"ownership mask must be binary: {path.name}")
    return result


def review_blockers(manifest: dict[str, Any]) -> list[str]:
    """Cheap UI hint only. Use validate_delivery before any final export."""
    blockers = []
    for item in manifest.get("items", []):
        item_id = item.get("id", "<missing>")
        if item.get("review", {}).get("status") != "approved":
            blockers.append(f"{item_id}: explicit approval required")
        for flag in sorted(HARD_FLAGS.intersection(item.get("qaFlags", []))):
            blockers.append(f"{item_id}: hard failure {flag}")
    if manifest.get("completion", {}).get("pendingPixels", 0):
        blockers.append("source ownership has pending pixels")
    if manifest.get("source", {}).get("provenance") == "fixture":
        blockers.append("fixtures are not production artwork")
    if not manifest.get("items"):
        blockers.append("delivery has no items")
    return blockers


def validate_delivery(manifest_path: Path, *, draft: bool = False,
                      max_texture_size: int = 16384) -> dict[str, Any]:
    """Return a JSON-safe receipt. Never writes or trusts cached QA booleans.

    A pass proves technical consistency of this snapshot, not aesthetic quality,
    authenticity of an author identity, or successful loading in a game engine.
    """
    report: dict[str, Any] = {"schemaVersion": "item-delivery-check-v1", "draft": draft,
        "status": "blocked", "integrityErrors": [], "reviewBlockers": [], "warnings": [],
        "verifiedArtifacts": {}, "metrics": {}, "manifestSha256": None}
    try:
        _integer(max_texture_size, "max_texture_size", 1)
        _require(type(draft) is bool, "draft must be a boolean")
        path = Path(manifest_path).resolve()
        _require(path.is_file() and path.stat().st_size <= 16 * 1024 * 1024, "missing or oversized manifest")
        raw = path.read_bytes()
        report["manifestSha256"] = sha256(raw).hexdigest()
        manifest = json.loads(raw)
        _require(isinstance(manifest, dict), "manifest must be an object")
        _require(manifest.get("schemaVersion") == "deterministic-item-sheet-v1" and
                 manifest.get("kind") == "deterministic-item-atlas", "unsupported manifest contract")
        root = path.parent
        verified: dict[str, str] = report["verifiedArtifacts"]

        def read(relative: Any, expected: Any = None, *, mask: bool = False) -> Image.Image:
            candidate = artifact(root, relative)
            actual = digest_file(candidate)
            if not mask:
                _require(isinstance(expected, str) and re.fullmatch(r"[0-9a-f]{64}", expected) is not None,
                         f"invalid SHA-256: {relative}")
                _require(actual == expected, f"SHA-256 mismatch: {relative}")
            verified[relative] = actual
            return _read_image(candidate, mask=mask)

        source_record, evidence, atlas_record = manifest["source"], manifest["evidence"], manifest["atlas"]
        _require(source_record.get("provenance") in {"imported", "fixture", "imagegen", "grok-imagine-image", "mixed"},
                 "unsupported source provenance")
        source = read(evidence["sourceRgba"], evidence["sourceRgbaSha256"])
        _require(source_record.get("mode") == "RGBA", "source mode must be RGBA")
        source_size = (_integer(source_record["width"], "source width", 1),
                       _integer(source_record["height"], "source height", 1))
        _require(source.size == source_size, "source dimensions mismatch")
        visible = _visible(source)
        _require(visible.getbbox() is not None, "source is completely transparent")
        _require(source.getchannel("A").getextrema()[0] == 0, "source lacks transparent exterior")
        atlas = read(atlas_record["path"], atlas_record["sha256"])
        declared_size = (_integer(atlas_record["width"], "atlas width", 1),
                         _integer(atlas_record["height"], "atlas height", 1))
        _require(atlas.size == declared_size, "atlas dimensions mismatch")
        _require(max(atlas.size) <= max_texture_size, "atlas exceeds target texture limit")
        packing = manifest["packing"]
        padding = _integer(packing["padding"], "padding")
        quantum = _integer(packing["quantum"], "quantum", 1)
        outer = _integer(packing.get("outer_padding", 0), "outer padding")
        items = manifest["items"]
        _require(isinstance(items, list) and 0 < len(items) <= 10000, "item count outside 1..10000")
        owned, atlas_alpha = Image.new("L", source.size), Image.new("L", atlas.size)
        cells, ids, content_groups = [], set(), {}
        total_crop_pixels = 0
        for item in items:
            item_id = item["id"]
            _require(isinstance(item_id, str) and re.fullmatch(r"[A-Za-z0-9_-]+", item_id) is not None
                     and item_id not in ids, "invalid or duplicate item id")
            ids.add(item_id)
            _require(item["review"]["status"] in STATUSES, f"{item_id}: invalid review status")
            _require(isinstance(item.get("qaFlags"), list) and all(isinstance(f, str) for f in item["qaFlags"]),
                     f"{item_id}: invalid QA flags")
            image = read(item["artifacts"]["rgba"], item["artifacts"]["sha256"])
            total_crop_pixels += image.width * image.height
            _require(total_crop_pixels <= MAX_PIXELS, "aggregate crop pixel budget exceeded")
            content_hash = sha256(image.width.to_bytes(4, "big") + image.height.to_bytes(4, "big") + image.tobytes()).hexdigest()
            _require(item["contentSha256"] == content_hash, f"{item_id}: content hash mismatch")
            content_groups.setdefault(content_hash, []).append(item_id)
            geometry = item["geometry"]
            _require(type(geometry.get("scale")) in {int, float} and geometry["scale"] == 1
                     and geometry.get("rotated") is False, f"{item_id}: scaling or rotation is forbidden")
            original = geometry["originalSize"]
            _require(isinstance(original, list) and len(original) == 2 and
                     all(type(v) is int and v > 0 for v in original) and tuple(original) == image.size,
                     f"{item_id}: native dimensions mismatch")
            pivot = geometry["pivot"]
            _require(isinstance(pivot, list) and len(pivot) == 2 and all(type(v) in {int, float}
                     and math.isfinite(v) and 0 <= v <= 1 for v in pivot), f"{item_id}: invalid normalized pivot")
            x, y, w, h = _rect(geometry["frame"], f"{item_id} frame")
            cx, cy, cw, ch = _rect(geometry["cellRect"], f"{item_id} cell")
            _require((w, h) == image.size, f"{item_id}: frame dimensions mismatch")
            _require(cx >= outer and cy >= outer and cx + cw <= atlas.width - outer
                     and cy + ch <= atlas.height - outer, f"{item_id}: cell outside atlas")
            _require(min(x - cx, y - cy, cx + cw - x - w, cy + ch - y - h) >= padding,
                     f"{item_id}: invalid frame containment or padding")
            _require(not any(v % quantum for v in (cx - outer, cy - outer, cw, ch)),
                     f"{item_id}: cell is not quantum-aligned")
            for px, py, pw, ph in cells:
                _require(cx + cw <= px or px + pw <= cx or cy + ch <= py or py + ph <= cy,
                         f"{item_id}: overlapping atlas cells")
            cells.append((cx, cy, cw, ch))
            _require(_same(image, atlas.crop((x, y, x + w, y + h))), f"{item_id}: atlas pixels differ from crop")
            atlas_alpha.paste(image.getchannel("A"), (x, y))
            sx, sy, sw, sh = _rect(item["source"]["bbox"], f"{item_id} source bbox", corners=True)
            _require((sw, sh) == image.size and sx + sw <= source.width and sy + sh <= source.height,
                     f"{item_id}: invalid source bounds")
            if sx == 0 or sy == 0 or sx + sw == source.width or sy + sh == source.height:
                report["reviewBlockers"].append(f"{item_id}: source-edge contact requires a new source")
            mask = _visible(image)
            _require(mask.getbbox() is not None, f"{item_id}: empty crop")
            _require(ImageChops.multiply(owned.crop((sx, sy, sx + sw, sy + sh)), mask).getbbox() is None,
                     f"{item_id}: duplicate source ownership")
            expected = Image.composite(source.crop((sx, sy, sx + sw, sy + sh)), Image.new("RGBA", image.size), mask)
            actual = Image.composite(image, Image.new("RGBA", image.size), mask)
            _require(_same(expected, actual), f"{item_id}: source pixels differ from crop")
            owned.paste(255, (sx, sy), mask)
        _require(_same(atlas.getchannel("A"), atlas_alpha), "unaccounted atlas pixels outside item frames")
        pending = read(evidence["pendingMask"], mask=True)
        discarded = read(evidence["discardedMask"], mask=True)
        _require(pending.size == source.size == discarded.size, "ownership mask dimensions mismatch")
        for left, right in ((owned, pending), (owned, discarded), (pending, discarded)):
            _require(ImageChops.multiply(left, right).getbbox() is None, "ownership masks overlap")
        combined = ImageChops.lighter(owned, ImageChops.lighter(pending, discarded))
        _require(_same(combined, visible), "source pixels are missing or invented in ownership accounting")
        pending_pixels = pending.histogram()[255]
        _require(_integer(manifest["completion"]["pendingPixels"], "pendingPixels") == pending_pixels,
                 "pending pixel counter does not match mask")
        report["reviewBlockers"] = list(dict.fromkeys(report["reviewBlockers"] + review_blockers(manifest)))
        report["metrics"] = {"items": len(items), "approved": sum(i["review"]["status"] == "approved" for i in items),
            "pendingPixels": pending_pixels, "discardedPixels": discarded.histogram()[255],
            "ownedPixels": owned.histogram()[255], "atlasSize": list(atlas.size),
            "duplicateContentGroups": [group for group in content_groups.values() if len(group) > 1]}
        report["warnings"] = ["Technical consistency is not visual approval or an engine smoke test."]
        if report["metrics"]["duplicateContentGroups"]:
            report["warnings"].append("Identical item pixels found; confirm that duplication is intentional.")
        report["status"] = "pass" if draft or not report["reviewBlockers"] else "review-required"
    except (DeliveryError, OSError, ValueError, KeyError, TypeError, AttributeError, Image.DecompressionBombError) as exc:
        report["integrityErrors"].append(str(exc))
        report["status"] = "invalid"
    return report
