#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Build motion-QA previews for a sprite-gen run.

For each state in frames/frames-manifest.json this writes:
  qa/<state>-contact.png  - frames left-to-right on a checker so motion is readable
  qa/<state>.gif          - frames played at the state fps (loops)
  qa/all-contact.png      - every state stacked, one row per state
  qa/pose-scale-review.png - idle/reference + pose rows for visual scale review

These are QA instruments, not runtime assets. The runtime SSoT stays
manifest.json.frame_layout over sprite-sheet-alpha.png.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw

from gif_utils import delay_ticks_to_duration_ms, save_clean_gif


def checker(size: tuple[int, int], square: int = 16) -> Image.Image:
    """Neutral checker so transparent pixels and stray fringe are both visible."""
    w, h = size
    bg = Image.new("RGBA", size, (210, 210, 210, 255))
    px = bg.load()
    for y in range(h):
        for x in range(w):
            if ((x // square) + (y // square)) % 2 == 0:
                px[x, y] = (235, 235, 235, 255)
    return bg


def flatten(frame: Image.Image) -> Image.Image:
    base = checker(frame.size)
    base.alpha_composite(frame)
    return base.convert("RGB")


def load_frames(run_dir: Path, files: list[str]) -> list[Image.Image]:
    return [Image.open(run_dir / rel).convert("RGBA") for rel in files]


def contact_sheet(
    frames: list[Image.Image],
    records: list[dict[str, object]] | None = None,
    baseline_y: int | None = None,
    gap: int = 4,
) -> Image.Image:
    cw = max(f.width for f in frames)
    ch = max(f.height for f in frames)
    n = len(frames)
    label_height = 28 if records else 0
    frame_top = gap + label_height
    sheet = Image.new("RGB", (n * cw + (n + 1) * gap, ch + 2 * gap + label_height), (255, 255, 255))
    draw = ImageDraw.Draw(sheet)
    x = gap
    for index, f in enumerate(frames):
        sheet.paste(flatten(f), (x, frame_top))
        if baseline_y is not None:
            y = frame_top + baseline_y
            draw.line((x, y, x + cw - 1, y), fill=(245, 158, 11), width=1)
        record = records[index] if records and index < len(records) else {}
        bbox = record.get("bbox") if isinstance(record, dict) else None
        if isinstance(bbox, list) and len(bbox) == 4:
            left, top, right, bottom = [int(value) for value in bbox]
            draw.rectangle((x + left, frame_top + top, x + right - 1, frame_top + bottom - 1), outline=(37, 99, 235), width=1)
        ratio = record.get("height_vs_reference") if isinstance(record, dict) else None
        width_ratio = record.get("width_vs_reference") if isinstance(record, dict) else None
        head_ratio = record.get("head_width_vs_reference") if isinstance(record, dict) else None
        expected = record.get("expected_height_vs_reference") if isinstance(record, dict) else None
        labels_top = []
        labels_bottom = []
        if isinstance(ratio, (int, float)):
            labels_top.append(f"h {ratio:.2f}x")
        if isinstance(width_ratio, (int, float)):
            labels_top.append(f"w {width_ratio:.2f}x")
        if isinstance(head_ratio, (int, float)):
            labels_bottom.append(f"head {head_ratio:.2f}x")
        if isinstance(expected, (int, float)):
            labels_bottom.append(f"exp {expected:.2f}x")
        if labels_top:
            draw.text((x + 2, gap + 2), "  ".join(labels_top), fill=(17, 24, 39))
        if labels_bottom:
            draw.text((x + 2, gap + 14), "  ".join(labels_bottom), fill=(17, 24, 39))
        x += cw + gap
    return sheet


def reference_state_name(rows: list[dict[str, object]]) -> str | None:
    for preferred in ("idle", "stand", "standing"):
        for row in rows:
            if row.get("state") == preferred:
                return str(row["state"])
    return str(rows[0]["state"]) if rows else None


def write_pose_scale_review(
    qa_dir: Path,
    rows: list[dict[str, object]],
    state_sheets: dict[str, Image.Image],
) -> None:
    selected: list[tuple[str, str, Image.Image]] = []
    reference = reference_state_name(rows)
    if reference and reference in state_sheets:
        selected.append((reference, "reference", state_sheets[reference]))
    for row in rows:
        state = str(row.get("state", ""))
        pose_geometry = row.get("pose_geometry")
        if not isinstance(pose_geometry, dict) or state not in state_sheets:
            continue
        kind = str(pose_geometry.get("kind", "pose"))
        if kind == "grounded-locomotion":
            continue
        selected.append((state, kind, state_sheets[state]))
    if len(selected) <= 1:
        return

    gap = 10
    label_w = 136
    header_h = 30
    width = label_w + max(sheet.width for _, _, sheet in selected) + gap * 3
    height = header_h + sum(sheet.height for _, _, sheet in selected) + gap * (len(selected) + 1)
    review = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(review)
    draw.text((gap, 8), "Pose scale visual review: compare height, width, baseline, and pose readability", fill=(17, 24, 39))
    y = header_h
    for state, kind, sheet in selected:
        draw.text((gap, y + 4), state, fill=(17, 24, 39))
        draw.text((gap, y + 20), kind, fill=(75, 85, 99))
        review.paste(sheet, (label_w + gap, y))
        y += sheet.height + gap
    review.save(qa_dir / "pose-scale-review.png")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument(
        "--delay-ticks",
        type=int,
        help="override every GIF preview delay in 1/100 second ticks",
    )
    args = parser.parse_args()

    run_dir = args.run_dir.expanduser().resolve()
    manifest_path = run_dir / "frames" / "frames-manifest.json"
    if not manifest_path.is_file():
        raise SystemExit(f"missing frames manifest: {manifest_path} (run extract first)")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    registration = manifest.get("sprite_registration") if isinstance(manifest.get("sprite_registration"), dict) else {}
    baseline_y = registration.get("baseline_y")
    baseline_y = int(baseline_y) if isinstance(baseline_y, (int, float)) else None
    request_path = run_dir / "sprite-request.json"
    request = json.loads(request_path.read_text(encoding="utf-8")) if request_path.is_file() else {}
    state_meta = request.get("states", {})

    qa_dir = run_dir / "qa"
    qa_dir.mkdir(parents=True, exist_ok=True)

    summary = []
    rows = manifest.get("rows", [])
    state_sheets: dict[str, Image.Image] = {}
    for row in rows:
        state = row["state"]
        files = row.get("files", [])
        if not files:
            summary.append({"state": state, "ok": False, "note": "no frame files"})
            continue
        frames = load_frames(run_dir, files)
        fps = int(state_meta.get(state, {}).get("fps", 6)) or 6
        loop = bool(state_meta.get(state, {}).get("loop", True))

        sheet = contact_sheet(frames, row.get("frame_records"), baseline_y)
        sheet.save(qa_dir / f"{state}-contact.png")
        state_sheets[state] = sheet

        duration = (
            delay_ticks_to_duration_ms(args.delay_ticks)
            if args.delay_ticks
            else max(1, round(1000 / fps))
        )
        save_clean_gif(
            frames,
            qa_dir / f"{state}.gif",
            duration_ms=duration,
            loop=0 if loop else 1,
        )
        summary.append(
            {
                "state": state,
                "ok": True,
                "frames": len(frames),
                "fps": fps,
                "delay_ticks": round(duration / 10),
                "loop": loop,
            }
        )

    # stacked all-state contact sheet
    if state_sheets:
        gap = 8
        width = max(s.width for s in state_sheets.values()) + 2 * gap
        height = sum(s.height for s in state_sheets.values()) + gap * (len(state_sheets) + 1)
        stacked = Image.new("RGB", (width, height), (255, 255, 255))
        y = gap
        for s in state_sheets.values():
            stacked.paste(s, (gap, y))
            y += s.height + gap
        stacked.save(qa_dir / "all-contact.png")
        write_pose_scale_review(qa_dir, rows, state_sheets)

    print(json.dumps({"ok": True, "qa_dir": str(qa_dir), "states": summary}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
