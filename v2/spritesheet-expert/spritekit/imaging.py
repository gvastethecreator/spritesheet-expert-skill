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
    if align_x == "center":
        return crop.width / 2
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


def match_pose_sizes(frames: list[Frame], expected: list[float], limit: float = 0.25) -> list[float]:
    """Rescale each frame so its body size follows the pose guides, relative to the run of frames.

    `expected[i]` is the pose guide's body height for frame i. A frame the model drew
    larger or smaller than its pose asks for is brought back; height changes the pose
    itself asks for (a crouch, raised arms) stay. Corrections are clamped to ±limit.
    Returns the factor applied to each frame.
    """
    measured = [frame_body_height(f.crop) for f in frames]
    reference = float(np.median([m / e for m, e in zip(measured, expected)]))
    factors = []
    for f, m, e in zip(frames, measured, expected):
        factor = float(np.clip(reference * e / max(m, 1), 1 - limit, 1 + limit))
        if abs(factor - 1) > 0.01:
            size = (max(1, round(f.crop.width * factor)), max(1, round(f.crop.height * factor)))
            f.crop = f.crop.resize(size, Image.Resampling.LANCZOS)
        factors.append(round(factor, 3))
    return factors


def body_height(frames: list[Frame]) -> float:
    """Typical body height in source pixels: the median over frames."""
    return float(np.median([frame_body_height(f.crop) for f in frames]))


def fit_frames(frames: list[Frame], cell: tuple[int, int], baseline: float, ground: str, align_x: str,
               margin: float = 0.06, scale: float | None = None) -> tuple[list[Image.Image], float]:
    """Place every frame in a runtime cell with ONE shared scale.

    ``ground="ground"`` puts each frame's bottom on the baseline. ``"keep"``
    keeps vertical motion relative to the source cells (lowest frame lands on
    the baseline). ``"center"`` centers each frame in the cell. ``align_x="feet"``
    pins the ground-contact band to the pivot; ``"mass"`` centers the alpha mass;
    ``"center"`` centers the bounding box; ``"keep"`` keeps horizontal motion
    relative to the source cell centers.
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
    room_h = chh - 2 * pad_top if ground == "center" else base_y - pad_top
    fit = min((cw - 2 * pad_x) / span_w, room_h / span_h)
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
        elif ground == "center":
            y = (chh - size[1]) / 2
        else:
            y = base_y - size[1]
        canvas = Image.new("RGBA", (cw, chh), (0, 0, 0, 0))
        canvas.paste(sprite, (round(x), round(y)))  # empty canvas: plain copy keeps exact RGBA
        placed.append(canvas)
    return placed, scale


def nine_slice(img: Image.Image, tol: float = 10.0, min_share: float = 0.15) -> dict | None:
    """Find the plain middle band a panel can stretch along.

    Every column (row) is compared with the middle one; the run of near-identical
    lines around the middle is the stretchable part. Returns the subject box in
    cell pixels and the fixed margins [left, top, right, bottom] inside it, or
    None when either middle band is under ``min_share`` of the size.
    """
    box = img.getchannel("A").getbbox()
    if not box:
        return None
    px = np.asarray(img.crop(box)).astype(np.float32)

    def band(lines: np.ndarray) -> tuple[int, int]:
        n = len(lines)
        diff = np.abs(lines - lines[n // 2]).mean(axis=(1, 2))
        lo = hi = n // 2
        while lo > 0 and diff[lo - 1] < tol:
            lo -= 1
        while hi < n - 1 and diff[hi + 1] < tol:
            hi += 1
        return lo, hi

    left, right = band(px.transpose(1, 0, 2))
    top, bottom = band(px)
    w, h = px.shape[1], px.shape[0]
    if (right - left + 1) < min_share * w or (bottom - top + 1) < min_share * h:
        return None
    return {"box": list(box), "slice": [left, top, w - 1 - right, h - 1 - bottom]}


def row_bands(img: Image.Image, rows: int) -> list[int]:
    """Cut lines for ``rows`` stacked rows: the middles of the gaps between them, else equal bands.

    Generated sheets rarely keep rows of equal height, so the empty gaps are a
    better guide than the planned grid. Small gaps inside one row are merged first.
    """
    occupied = (np.asarray(img.getchannel("A")) >= 128).sum(axis=1) > max(2, img.width * 0.002)
    runs, y = [], 0
    while y < img.height:
        if occupied[y]:
            start = y
            while y < img.height and occupied[y]:
                y += 1
            runs.append([start, y])
        else:
            y += 1
    while len(runs) > rows:
        i = min(range(len(runs) - 1), key=lambda i: runs[i + 1][0] - runs[i][1])
        runs[i:i + 2] = [[runs[i][0], runs[i + 1][1]]]
    if len(runs) != rows:
        return [round(img.height * r / rows) for r in range(rows + 1)]
    return [0, *[(a[1] + b[0]) // 2 for a, b in zip(runs, runs[1:])], img.height]


def separate_items(img: Image.Image, gap_share: float = 0.015) -> tuple[list[Frame], int]:
    """Find loose items on a sheet without a grid.

    Pieces closer than ``gap_share`` of the sheet's short side belong to one
    item (a bottle and its cork, a sword and its glint); groups under 2% of the
    median item area are specks. Items come back in reading order: rows by
    vertical center, then left to right. Returns the items and the speck count.
    """
    solid = np.asarray(img.getchannel("A")) >= ALPHA_SOLID
    h, w = solid.shape
    reach = max(1, round(min(h, w) * gap_share / 2))  # both pieces grow by reach, so they meet across 2 * reach
    groups, count = ndimage.label(ndimage.distance_transform_edt(~solid) <= reach)
    if count == 0:
        return [], 0
    owner = np.where(solid, groups, 0)
    idx = np.arange(1, count + 1)
    areas = ndimage.sum_labels(solid, owner, idx)
    keep = [int(i) for i, a in zip(idx, areas) if a >= 0.02 * np.median(areas[areas > 0])]
    slices = ndimage.find_objects(owner)
    boxes = {i: (slices[i - 1][1].start, slices[i - 1][0].start, slices[i - 1][1].stop, slices[i - 1][0].stop)
             for i in keep if slices[i - 1] is not None}
    tol = 0.5 * float(np.median([b[3] - b[1] for b in boxes.values()]))
    rows: list[list[int]] = []
    for i in sorted(boxes, key=lambda i: (boxes[i][1] + boxes[i][3]) / 2):
        cy = (boxes[i][1] + boxes[i][3]) / 2
        if rows and cy - (boxes[rows[-1][0]][1] + boxes[rows[-1][0]][3]) / 2 <= tol:
            rows[-1].append(i)
        else:
            rows.append([i])
    order = [i for row in rows for i in sorted(row, key=lambda i: boxes[i][0])]
    items = []
    for k, i in enumerate(order):
        box = boxes[i]
        crop = np.asarray(img.crop(box)).copy()
        crop[..., 3] = np.where(owner[box[1]:box[3], box[0]:box[2]] == i, crop[..., 3], 0)
        items.append(Frame(index=k, crop=Image.fromarray(crop, "RGBA"), box=box, cell_box=box,
                           touches_source_edge=box[0] == 0 or box[1] == 0 or box[2] == w or box[3] == h,
                           specks_dropped=0))
    return items, count - len(boxes)


def shelf_pack(sizes: list[tuple[int, int]], pad: int = 2) -> tuple[list[tuple[int, int]], tuple[int, int]]:
    """Pack rectangles in shelves, tallest first, about as wide as a square of their total area."""
    width = max(max(w for w, _ in sizes) + pad, round(np.sqrt(sum((w + pad) * (h + pad) for w, h in sizes)) * 1.15))
    pos: list[tuple[int, int]] = [(0, 0)] * len(sizes)
    x = y = shelf = used_w = 0
    for i in sorted(range(len(sizes)), key=lambda i: -sizes[i][1]):
        w, h = sizes[i]
        if x and x + w > width:
            x, y, shelf = 0, y + shelf + pad, 0
        pos[i] = (x, y)
        x += w + pad
        shelf, used_w = max(shelf, h), max(used_w, x - pad)
    return pos, (used_w, y + shelf)


def size_signals(crop: Image.Image) -> tuple[float, float]:
    """Two pose-tolerant size measures: the square root of the opaque area and the radius of the thickest part."""
    solid = np.asarray(crop.getchannel("A")) >= 128
    return float(np.sqrt(solid.sum())), float(ndimage.distance_transform_edt(solid).max())


def size_offsets(crops: list[Image.Image]) -> list[float]:
    """How much larger (+) or smaller (-) each crop is drawn than the row.

    A pose changes area (arms overlap, a bow hides the chest) but not the head or
    torso, and the reverse for a raised fist near the head. Only when both
    measures move the same way is it drawing scale: the smaller move counts.
    """
    sig = np.array([size_signals(c) for c in crops])
    rel = sig / np.median(sig, axis=0) - 1
    return [float(np.sign(a) * min(abs(a), abs(b))) if np.sign(a) == np.sign(b) else 0.0 for a, b in rel]


def even_sizes(frames: list[Frame], limit: float = 0.15) -> list[float]:
    """Rescale frames drawn a little larger or smaller than the row; larger jumps are left for repair."""
    factors = []
    for f, off in zip(frames, size_offsets([f.crop for f in frames])):
        k = 1 / (1 + off) if 0.02 < abs(off) <= limit else 1.0
        if k != 1.0:
            f.crop = f.crop.resize((max(1, round(f.crop.width * k)), max(1, round(f.crop.height * k))), Image.Resampling.LANCZOS)
        factors.append(round(k, 3))
    return factors
