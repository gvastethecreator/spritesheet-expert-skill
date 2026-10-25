"""Informational checks. Each returns {id, status, detail}; status is pass, warn or fail.

They are heuristics that point a reviewer at a frame. `check --strict` turns
warn and fail into a non-zero exit for deliveries.
"""

from __future__ import annotations

import numpy as np
from PIL import Image

from .imaging import ALPHA_SOLID, Frame, frame_body_height


def result(check_id: str, status: str, detail: str, frames: list[int] | None = None) -> dict:
    return {"id": check_id, "status": status, "detail": detail, "frames": frames or []}


def hue_histogram(img: Image.Image) -> np.ndarray:
    hsv = np.asarray(img.convert("RGB").convert("HSV")).reshape(-1, 3).astype(np.int32)
    a = np.asarray(img.getchannel("A")).reshape(-1)
    hsv = hsv[a >= 128]
    if not len(hsv):
        return np.zeros(64)
    bins = (hsv[:, 0] // 32) * 8 + (hsv[:, 1] // 32)
    hist = np.bincount(bins, minlength=64).astype(np.float64)
    return hist / hist.sum()


def palette_distance(a: Image.Image, b: Image.Image) -> float:
    """Bhattacharyya distance between hue/saturation histograms (0 = same palette)."""
    coeff = float(np.sqrt(hue_histogram(a) * hue_histogram(b)).sum())
    return float(np.sqrt(max(0.0, 1.0 - coeff)))


def frame_diff(a: Image.Image, b: Image.Image) -> float:
    x = np.asarray(a).astype(np.float32) / 255
    y = np.asarray(b).astype(np.float32) / 255
    return float(np.abs(x - y).mean())


def run_checks(st: dict, frames: list[Frame | None], placed: list[Image.Image],
               reference: Image.Image | None, cutout_info: dict) -> list[dict]:
    out = []
    missing = [i + 1 for i, f in enumerate(frames) if f is None]
    out.append(result("frames", "fail" if missing else "pass",
                      f"missing frame(s) {missing}" if missing else f"{len(frames)} of {len(frames)} frames found", missing))
    found = [f for f in frames if f is not None]
    if not found:
        return out

    edge = [f.index + 1 for f in found if f.touches_source_edge]
    out.append(result("source-edge", "warn" if edge else "pass",
                      f"subject touches the source image edge in frame(s) {edge}; it may be cut off" if edge
                      else "no frame touches the source image edge", edge))

    specks = sum(f.specks_dropped for f in found)
    out.append(result("specks", "pass", f"{specks} tiny detached speck(s) dropped" if specks else "no stray specks"))

    if st["ground"] == "ground":
        heights = [frame_body_height(f.crop) for f in found]
        ratio = max(heights) / max(1, min(heights))
        # A model that redraws one frame smaller or larger shows up as a jump against both neighbors.
        drift = []
        typical = float(np.median(heights))
        for i, f in enumerate(found):
            near = [heights[j] for j in (i - 1, i + 1) if 0 <= j < len(found)]
            off_row = abs(heights[i] / typical - 1) > 0.12
            if near and off_row and all(abs(heights[i] / n - 1) > 0.10 for n in near):
                drift.append(f.index + 1)
        if drift:
            out.append(result("scale", "warn", f"frame(s) {drift} are drawn at a different size than their neighbors; regenerate them", drift))
        else:
            out.append(result("scale", "pass", f"body heights vary {ratio:.2f}x across the row and no frame jumps against its neighbors"))

    ref = reference or found[0].crop
    dists = [(f.index + 1, palette_distance(ref, f.crop)) for f in found]
    drift = [i for i, d in dists if d > 0.35]
    worst = max(d for _, d in dists)
    out.append(result("identity", "warn" if drift else "pass",
                      f"palette differs from the {'anchor' if reference else 'first frame'} in frame(s) {drift} (max distance {worst:.2f})"
                      if drift else f"palette matches the {'anchor' if reference else 'first frame'} (max distance {worst:.2f})", drift))

    if len(placed) > 1:
        diffs = [frame_diff(placed[i], placed[i + 1]) for i in range(len(placed) - 1)]
        dupes = [i + 2 for i, d in enumerate(diffs) if d < 0.002]
        mean = float(np.mean(diffs))
        status = "warn" if dupes or mean < 0.006 else "pass"
        detail = (f"frame(s) {dupes} repeat the previous frame" if dupes
                  else "frames barely change; the motion may read as static" if mean < 0.006
                  else f"average change between frames {mean:.3f}")
        out.append(result("motion", status, detail, dupes))
        if st.get("loop"):
            closing = frame_diff(placed[-1], placed[0])
            jump = closing > 2.5 * float(np.median(diffs))
            out.append(result("loop", "warn" if jump else "pass",
                              f"last-to-first change {closing:.3f} is much larger than the typical {np.median(diffs):.3f}; the loop may pop"
                              if jump else "the loop closes smoothly", [len(placed), 1] if jump else None))

    touching = []
    for i, img in enumerate(placed):
        a = np.asarray(img.getchannel("A"))
        if (a[0] >= ALPHA_SOLID).any() or (a[-1] >= ALPHA_SOLID).any() or (a[:, 0] >= ALPHA_SOLID).any() or (a[:, -1] >= ALPHA_SOLID).any():
            touching.append(i + 1)
    out.append(result("cell-edge", "warn" if touching else "pass",
                      f"frame(s) {touching} touch the runtime cell edge" if touching else "every frame fits inside its cell", touching))

    if cutout_info.get("method") == "matte":
        matte = np.array(cutout_info["matte_rgb"], dtype=np.float32)
        halo = []
        for f in found:
            px = np.asarray(f.crop).astype(np.float32)
            semi = (px[..., 3] > 0) & (px[..., 3] < 200)
            if semi.sum() > 20:
                near = np.sqrt(((px[..., :3][semi] - matte) ** 2).sum(axis=1)) < 30
                if near.mean() > 0.25:
                    halo.append(f.index + 1)
        out.append(result("halo", "warn" if halo else "pass",
                          f"edge pixels still carry the matte color in frame(s) {halo}" if halo else "no matte halo on edges", halo))
    return out
