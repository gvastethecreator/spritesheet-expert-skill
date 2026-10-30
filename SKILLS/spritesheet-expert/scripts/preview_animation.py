#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Build motion-QA previews for a sprite-gen run.

For each state in frames/frames-manifest.json this writes:
  qa/<state>-contact.png  - frames left-to-right on a checker so motion is readable
  qa/<state>.gif          - GIF preview; stdout records its decoded delays
  qa/all-contact.png      - every state stacked, one row per state
  qa/pose-scale-review.png - idle/reference + pose rows for visual scale review

These are QA instruments, not runtime assets. The runtime contract is
manifest.json and its declared atlas; previews do not establish delivery.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from PIL import Image, ImageDraw

from compose_sprite_gif import flatten
from gif_utils import delay_ticks_to_duration_ms, gif_report, save_clean_gif
from check_animation_contracts import frame_rows_by_state
from check_asset_slots import review_output
from runio import atomic_save_image
from spritecore.paths import resolve_run_path

REVIEW_BACKGROUND = (17, 17, 17)
REVIEW_TEXT = (232, 232, 232)
REVIEW_OUTLINE = (180, 180, 180)


def load_frames(run_dir: Path, files: list[str]) -> list[Image.Image]:
    frames = []
    for relative in files:
        with Image.open(resolve_run_path(run_dir, relative)) as opened:
            frames.append(opened.convert("RGBA"))
    return frames


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
    sheet = Image.new("RGB", (n * cw + (n + 1) * gap, ch + 2 * gap + label_height), REVIEW_BACKGROUND)
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
            draw.rectangle((x + left, frame_top + top, x + right - 1, frame_top + bottom - 1), outline=REVIEW_OUTLINE, width=1)
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
            draw.text((x + 2, gap + 2), "  ".join(labels_top), fill=REVIEW_TEXT)
        if labels_bottom:
            draw.text((x + 2, gap + 14), "  ".join(labels_bottom), fill=REVIEW_TEXT)
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
    review = Image.new("RGB", (width, height), REVIEW_BACKGROUND)
    draw = ImageDraw.Draw(review)
    draw.text((gap, 8), "Pose scale visual review: compare height, width, baseline, and pose readability", fill=REVIEW_TEXT)
    y = header_h
    for state, kind, sheet in selected:
        draw.text((gap, y + 4), state, fill=REVIEW_TEXT)
        draw.text((gap, y + 20), kind, fill=REVIEW_OUTLINE)
        review.paste(sheet, (label_w + gap, y))
        y += sheet.height + gap
    atomic_save_image(review, qa_dir / "pose-scale-review.png")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument(
        "--delay-ticks",
        type=int,
        help="override every GIF preview delay in 1/100 second ticks",
    )
    args = parser.parse_args()
    override_duration = delay_ticks_to_duration_ms(args.delay_ticks) if args.delay_ticks is not None else None

    run_dir = args.run_dir.expanduser().resolve()
    manifest_path = resolve_run_path(run_dir, "frames/frames-manifest.json")
    if not manifest_path.is_file():
        raise SystemExit(f"missing frames manifest: {manifest_path} (run extract first)")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    registration = manifest.get("sprite_registration") if isinstance(manifest.get("sprite_registration"), dict) else {}
    baseline_y = registration.get("baseline_y")
    baseline_y = int(baseline_y) if isinstance(baseline_y, (int, float)) else None
    request_path = resolve_run_path(run_dir, "sprite-request.json")
    request = json.loads(request_path.read_text(encoding="utf-8")) if request_path.is_file() else {}
    state_meta = request.get("states", {})

    summary = []
    rows = list(frame_rows_by_state(manifest).values())
    sources = {manifest_path, request_path}
    for row in rows:
        files = row.get("files", [])
        if not isinstance(files, list) or any(not isinstance(path, str) for path in files):
            raise ValueError("preview frame files must be an array of relative paths")
        sources.update(resolve_run_path(run_dir, path) for path in files)
    outputs = {}
    for relative in [
        "qa/all-contact.png", "qa/pose-scale-review.png",
        *[f"qa/{row['state']}{suffix}" for row in rows for suffix in ("-contact.png", ".gif")],
    ]:
        target = review_output(run_dir, relative, sources)
        if target in outputs.values():
            raise ValueError("preview outputs alias each other")
        outputs[relative] = target
    qa_dir = resolve_run_path(run_dir, "qa")
    qa_dir.mkdir(parents=True, exist_ok=True)
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
        atomic_save_image(sheet, outputs[f"qa/{state}-contact.png"])
        state_sheets[state] = sheet

        duration = (
            override_duration
            if override_duration is not None
            else max(1, round(1000 / fps))
        )
        save_clean_gif(
            frames,
            outputs[f"qa/{state}.gif"],
            duration_ms=duration,
            loop=0 if loop else 1,
        )
        encoded_delays = gif_report(outputs[f"qa/{state}.gif"])["delay_ticks"]
        summary.append(
            {
                "state": state,
                "ok": True,
                "frames": len(frames),
                "fps": fps,
                "delay_ticks": encoded_delays[0] if len(set(encoded_delays)) == 1 else None,
                "durations_ms": [ticks * 10 for ticks in encoded_delays],
                "encoded_frames": len(encoded_delays),
                "requested_duration_ms": duration,
                "loop": loop,
            }
        )

    # stacked all-state contact sheet
    if state_sheets:
        gap = 8
        width = max(s.width for s in state_sheets.values()) + 2 * gap
        height = sum(s.height for s in state_sheets.values()) + gap * (len(state_sheets) + 1)
        stacked = Image.new("RGB", (width, height), REVIEW_BACKGROUND)
        y = gap
        for s in state_sheets.values():
            stacked.paste(s, (gap, y))
            y += s.height + gap
        atomic_save_image(stacked, outputs["qa/all-contact.png"])
        write_pose_scale_review(qa_dir, rows, state_sheets)

    ok = bool(summary) and all(row["ok"] for row in summary)
    print(json.dumps({"ok": ok, "qa_dir": str(qa_dir), "states": summary}, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        print(json.dumps({"ok": False, "complete": False, "status": "operational-error", "errors": [str(exc)]}))
        raise SystemExit(3)
