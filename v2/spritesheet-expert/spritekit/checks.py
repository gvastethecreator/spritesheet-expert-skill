"""Informational checks. Each returns {id, status, detail}; status is pass, warn or fail.

They are heuristics that point a reviewer at a frame. `check --strict` turns
warn and fail into a non-zero exit for deliveries.
"""

from __future__ import annotations

import numpy as np
from PIL import Image

from .imaging import ALPHA_SOLID, Frame, nine_slice, size_offsets


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


def mean_lab(img: Image.Image) -> np.ndarray:
    """Average CIELAB color of the solid pixels."""
    raw = np.asarray(img.convert("RGB").convert("LAB"))
    lab = raw.astype(np.float64)
    lab[..., 0] *= 100 / 255  # Pillow stores L as 0..255
    lab[..., 1:] = raw[..., 1:].view(np.int8)  # numpy sees Pillow's a and b as signed bytes
    solid = np.asarray(img.getchannel("A")) >= 200
    return lab[solid].mean(axis=0) if solid.any() else np.zeros(3)


def state_match(rows: dict[str, list[Image.Image]]) -> dict[str, dict]:
    """One character keeps one palette and light across states: each row against the first."""
    typical = {name: np.median([mean_lab(i) for i in imgs if i.getchannel("A").getbbox()], axis=0) for name, imgs in rows.items()}
    first = next(iter(typical))
    out = {}
    for name, lab in list(typical.items())[1:]:
        d = float(np.linalg.norm(lab - typical[first]))
        out[name] = result("match", "warn" if d > 8 else "pass",
                           f"color and light differ from {first} by {d:.1f}; regenerate this state with {first}'s frames attached"
                           if d > 8 else f"color and light match {first} (difference {d:.1f})")
    return out


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
    if st["motion"] == "atlas":
        n, seen = len(frames), cutout_info.get("found", len(found))
        out.append(result("items", "pass" if seen == n else "fail",
                          f"{seen} items found, {n} planned" + ("" if seen == n else
                          "; items that touch merge into one, so ask for wider gaps" if seen < n else
                          "; stray pieces count as items, so ask for fewer details or remove extras"),
                          [] if seen >= n else list(range(seen + 1, n + 1))))
    if not found:
        return out

    edge = [f.index + 1 for f in found if f.touches_source_edge]
    out.append(result("source-edge", "warn" if edge else "pass",
                      f"subject touches the source image edge in frame(s) {edge}; it may be cut off" if edge
                      else "no frame touches the source image edge", edge))

    specks = sum(f.specks_dropped for f in found)
    out.append(result("specks", "pass", f"{specks} tiny detached speck(s) dropped" if specks else "no stray specks"))

    animation = st["motion"] not in ("slots", "atlas")
    # Frames of one character share palette and light; icon sets and UI states change them on purpose.
    one_look = animation or st["ground"] == "ground"
    if st["ground"] in ("ground", "center") and len(found) > 2:
        offsets = size_offsets([f.crop for f in found])
        drift = [f.index + 1 for f, o in zip(found, offsets) if abs(o) > 0.06]
        detail = ", ".join(f"{f.index + 1}: {o:+.0%}" for f, o in zip(found, offsets) if abs(o) > 0.06)
        worst = max(abs(o) for o in offsets)
        out.append(result("scale", "warn" if drift else "pass",
                          f"frame(s) drawn at another size than the row ({detail}); repair them" if drift
                          else f"every frame within {worst:.1%} of the row's size", drift))

    factors = cutout_info.get("size_factors")
    if factors:
        clamped = [i + 1 for i, f in enumerate(factors) if abs(f - 1) >= 0.249]
        detail = ", ".join(f"{i + 1}: {f:.2f}x" for i, f in enumerate(factors))
        out.append(result("size", "warn" if clamped else "pass",
                          f"frame(s) {clamped} needed the maximum size correction; regenerate them ({detail})" if clamped
                          else f"body size matched to the pose guides ({detail})", clamped))

    if one_look and len(found) > 2:
        # Lighting or color shifts show up as a frame whose average Lab color sits away from the row's.
        means = [mean_lab(f.crop) for f in found]
        typical = np.median(means, axis=0)
        delta = [float(np.linalg.norm(m - typical)) for m in means]
        off = [f.index + 1 for f, d in zip(found, delta) if d > 8]
        worst = max(delta)
        out.append(result("color", "warn" if off else "pass",
                          f"frame(s) {off} differ in color or lighting from the rest (max difference {worst:.1f}); repair them" if off
                          else f"color and lighting match across frames (max difference {worst:.1f})", off))

    if one_look:
        ref = reference or found[0].crop
        dists = [(f.index + 1, palette_distance(ref, f.crop)) for f in found]
        drift = [i for i, d in dists if d > 0.35]
        worst = max(d for _, d in dists)
        out.append(result("identity", "warn" if drift else "pass",
                          f"palette differs from the {'anchor' if reference else 'first frame'} in frame(s) {drift} (max distance {worst:.2f})"
                          if drift else f"palette matches the {'anchor' if reference else 'first frame'} (max distance {worst:.2f})", drift))

    if st["ground"] == "nine":
        flat = [f.index + 1 for f, img in zip(found, placed) if nine_slice(img) is None]
        out.append(result("stretch", "warn" if flat else "pass",
                          f"frame(s) {flat} have no plain middle band to stretch; ask for an even fill between the borders"
                          if flat else "every panel has a plain middle band for nine-slice stretching", flat))

    if animation and len(placed) > 1:
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

    if st["motion"] != "atlas":  # packed items are tight crops, not cells
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
