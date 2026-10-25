"""Pixel operations: cutout, frame segmentation, shared-scale fitting."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image
from scipy import ndimage

ALPHA_SOLID = 16          # alpha at or above this counts as subject
MATTE_TOLERANCE = 18.0    # RGB distance that still counts as background
MATTE_EDGE = 60.0         # distance where an edge pixel becomes fully opaque


def has_native_alpha(img: Image.Image) -> bool:
    """True when the border is mostly transparent, so the provider gave real alpha."""
    if img.mode != "RGBA":
        return False
    a = np.asarray(img.getchannel("A"))
    border = np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]])
    return float((border < ALPHA_SOLID).mean()) >= 0.7


def matte_color(rgb: np.ndarray) -> np.ndarray:
    border = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]]).astype(np.float32)
    return np.median(border, axis=0)


def remove_matte(img: Image.Image, min_hole: int = 64) -> tuple[Image.Image, dict]:
    """Remove a flat background color.

    Background is every pixel connected to the border within tolerance, plus
    enclosed regions of the same color larger than ``min_hole`` pixels (gaps
    between limbs, the hole inside a hook). Edge pixels get partial alpha from
    their color distance, and their color is un-mixed from the matte.
    """
    rgb = np.asarray(img.convert("RGB")).astype(np.float32)
    bg = matte_color(rgb)
    dist = np.sqrt(((rgb - bg) ** 2).sum(axis=2))
    near = dist <= MATTE_TOLERANCE
    labels, count = ndimage.label(near)
    border_ids = set(np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))) - {0}
    sizes = ndimage.sum_labels(near, labels, index=np.arange(1, count + 1)) if count else np.array([])
    keep_bg = np.zeros(count + 1, dtype=bool)
    for i in range(1, count + 1):
        keep_bg[i] = i in border_ids or sizes[i - 1] >= min_hole
    background = keep_bg[labels]
    alpha = np.where(background, 0.0, 1.0)
    edge = ndimage.binary_dilation(background, iterations=2) & ~background
    soft = np.clip((dist - MATTE_TOLERANCE) / (MATTE_EDGE - MATTE_TOLERANCE), 0.0, 1.0)
    alpha = np.where(edge, soft, alpha)
    a3 = alpha[..., None]
    with np.errstate(divide="ignore", invalid="ignore"):
        unmixed = np.where(a3 > 0, (rgb - (1 - a3) * bg) / a3, 0)
    out = np.dstack([np.clip(unmixed, 0, 255), alpha * 255]).astype(np.uint8)
    info = {"method": "matte", "matte_rgb": [int(v) for v in bg], "enclosed_holes_removed": int(sum(
        1 for i in range(1, count + 1) if keep_bg[i] and i not in border_ids))}
    return Image.fromarray(out, "RGBA"), info


def remove_birefnet(img: Image.Image) -> tuple[Image.Image, dict]:
    try:
        from rembg import new_session, remove
    except ImportError as exc:
        raise SystemExit("--cutout birefnet needs `pip install \"rembg[cpu]\"`") from exc
    out = remove(img.convert("RGB"), session=new_session("birefnet-general"))
    return out.convert("RGBA"), {"method": "birefnet-general"}


def cutout(img: Image.Image, mode: str) -> tuple[Image.Image, dict]:
    """`auto`: native alpha if present, else flat matte removal."""
    if mode == "birefnet":
        return remove_birefnet(img)
    if mode in ("auto", "alpha") and has_native_alpha(img):
        rgba = np.asarray(img.convert("RGBA")).copy()
        rgba[..., 3][rgba[..., 3] < 8] = 0
        return Image.fromarray(rgba, "RGBA"), {"method": "native-alpha"}
    if mode == "alpha":
        raise SystemExit("source has no usable native alpha; use --cutout auto or matte")
    return remove_matte(img)


@dataclass
class Frame:
    index: int
    crop: Image.Image          # tight RGBA crop of the subject
    box: tuple[int, int, int, int]   # crop box in source pixels
    cell_box: tuple[int, int, int, int]
    touches_source_edge: bool
    specks_dropped: int


def split_frames(img: Image.Image, cols: int, rows: int, frames: int) -> list[Frame | None]:
    """Assign every opaque component to the grid cell holding its centroid.

    Poses that cross a cell border stay whole. Specks under 0.05% of a cell are
    dropped and counted. A cell with no component returns None.
    """
    a = np.asarray(img.getchannel("A"))
    h, w = a.shape
    cw, ch = w / cols, h / rows
    labels, count = ndimage.label(a >= ALPHA_SOLID)
    if count == 0:
        return [None] * frames
    idx = np.arange(1, count + 1)
    areas = ndimage.sum_labels(np.ones_like(a), labels, index=idx)
    centers = ndimage.center_of_mass(a >= ALPHA_SOLID, labels, idx)
    slices = ndimage.find_objects(labels)
    min_area = max(4, cw * ch * 0.0005)
    members: dict[int, list[int]] = {}
    small: list[tuple[int, int, float, float]] = []
    for label, area, (cy, cx) in zip(idx, areas, centers):
        cell = min(int(cy // ch), rows - 1) * cols + min(int(cx // cw), cols - 1)
        if area < min_area:
            small.append((int(label), cell, cy, cx))
        else:
            members.setdefault(cell, []).append(int(label))
    # Small pieces next to a body (hair strands, sparks, sweat) stay with it; far ones are specks.
    reach = max(2, round(min(cw, ch) * 0.03))
    body = ndimage.binary_dilation(np.isin(labels, [l for ids in members.values() for l in ids]), iterations=reach)
    specks: dict[int, int] = {}
    for label, cell, cy, cx in small:
        if body[int(cy), int(cx)] and cell in members:
            members[cell].append(label)
        else:
            specks[cell] = specks.get(cell, 0) + 1
    out: list[Frame | None] = []
    for i in range(frames):
        ids = members.get(i)
        if not ids:
            out.append(None)
            continue
        ys = [slices[l - 1][0] for l in ids]
        xs = [slices[l - 1][1] for l in ids]
        box = (min(s.start for s in xs), min(s.start for s in ys), max(s.stop for s in xs), max(s.stop for s in ys))
        mask = np.isin(labels[box[1]:box[3], box[0]:box[2]], ids)
        crop = np.asarray(img.crop(box)).copy()
        crop[..., 3] = np.where(mask, crop[..., 3], 0)
        cx0, cy0 = int((i % cols) * cw), int((i // cols) * ch)
        out.append(Frame(
            index=i, crop=Image.fromarray(crop, "RGBA"), box=box,
            cell_box=(cx0, cy0, int(cx0 + cw), int(cy0 + ch)),
            touches_source_edge=box[0] == 0 or box[1] == 0 or box[2] == w or box[3] == h,
            specks_dropped=specks.get(i, 0),
        ))
    return out


def mass_center_x(crop: Image.Image) -> float:
    a = np.asarray(crop.getchannel("A")).astype(np.float64)
    total = a.sum()
    return float((a.sum(axis=0) * np.arange(a.shape[1])).sum() / total) if total else crop.width / 2


def feet_center_x(crop: Image.Image) -> float:
    """Alpha-weighted x center of the ground-contact band (bottom 8% of the subject)."""
    a = np.asarray(crop.getchannel("A")).astype(np.float64)
    band = a[-max(4, round(a.shape[0] * 0.08)):]
    total = band.sum()
    return float((band.sum(axis=0) * np.arange(a.shape[1])).sum() / total) if total else crop.width / 2


def anchor_x(crop: Image.Image, align_x: str) -> float:
    return feet_center_x(crop) if align_x == "feet" else mass_center_x(crop)


def frame_body_height(crop: Image.Image) -> int:
    """Height from the feet to the top of the body, ignoring thin things above it
    (a raised weapon, a staff, a plume): the top is the first row whose opaque
    width reaches 15% of the widest row. Legs are never trimmed.
    """
    widths = (np.asarray(crop.getchannel("A")) >= ALPHA_SOLID).sum(axis=1)
    if not widths.max():
        return 0
    solid = np.nonzero(widths)[0]
    top = int(np.nonzero(widths >= widths.max() * 0.15)[0].min())
    return int(solid.max() - top + 1)


def body_height(frames: list[Frame]) -> float:
    """Typical body height in source pixels: the median over frames."""
    return float(np.median([frame_body_height(f.crop) for f in frames]))


def fit_frames(frames: list[Frame], cell: tuple[int, int], baseline: float, ground: str, align_x: str,
               margin: float = 0.06, scale: float | None = None) -> tuple[list[Image.Image], float]:
    """Place every frame in a runtime cell with ONE shared scale.

    ``ground="ground"`` puts each frame's bottom on the baseline. ``"keep"``
    keeps vertical motion relative to the source cells (lowest frame lands on
    the baseline). ``align_x="feet"`` pins the ground-contact band to the
    pivot; ``"mass"`` centers the alpha mass; ``"keep"``
    keeps horizontal motion relative to the source cell centers.
    """
    cw, chh = cell
    base_y = round(chh * baseline)
    pad_x, pad_top = cw * margin, chh * margin
    if ground == "keep":
        tops = [f.box[1] - f.cell_box[1] for f in frames]
        bottoms = [f.box[3] - f.cell_box[1] for f in frames]
        span_h = max(bottoms) - min(tops)
    else:
        span_h = max(f.crop.height for f in frames)
    if align_x == "keep":
        lefts = [f.box[0] - (f.cell_box[0] + f.cell_box[2]) / 2 for f in frames]
        rights = [f.box[2] - (f.cell_box[0] + f.cell_box[2]) / 2 for f in frames]
        span_w = 2 * max(max(abs(v) for v in lefts), max(abs(v) for v in rights))
    else:
        span_w = 2 * max(max(anchor_x(f.crop, align_x), f.crop.width - anchor_x(f.crop, align_x)) for f in frames)
    fit = min((cw - 2 * pad_x) / span_w, (base_y - pad_top) / span_h)
    scale = fit if scale is None else min(scale, fit)
    lowest = max((f.box[3] - f.cell_box[1]) for f in frames) if ground == "keep" else 0
    placed = []
    for f in frames:
        size = (max(1, round(f.crop.width * scale)), max(1, round(f.crop.height * scale)))
        sprite = f.crop.resize(size, Image.Resampling.LANCZOS)
        if align_x == "keep":
            x = cw / 2 + (f.box[0] - (f.cell_box[0] + f.cell_box[2]) / 2) * scale
        else:
            x = cw / 2 - anchor_x(f.crop, align_x) * scale
        if ground == "keep":
            y = base_y - (lowest - (f.box[3] - f.cell_box[1])) * scale - size[1]
        else:
            y = base_y - size[1]
        canvas = Image.new("RGBA", (cw, chh), (0, 0, 0, 0))
        canvas.paste(sprite, (round(x), round(y)))  # empty canvas: plain copy keeps exact RGBA
        placed.append(canvas)
    return placed, scale
