#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Compose a QA-approved manual frame subset into a selected cycle.

This is for cases where generation produces a larger row, but motion QA finds
that only a human-selected subset is usable. The original extracted frame files
remain the source; this script writes a small selected-cycle manifest plus GIF
and contact-sheet previews.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image

from compose_sprite_gif import contact_sheet
from compose_sprite_atlas import resize_policy_for_request
from curation import apply_transform, load_curation, state_plan
from gif_utils import delay_ticks_to_duration_ms, save_clean_gif
from spritecore.image_ops import ResizePolicy
from spritecore.paths import PathSafetyError, resolve_run_path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_frames(value: str) -> list[int]:
    frames = [int(part.strip()) for part in value.split(",") if part.strip()]
    if not frames:
        raise argparse.ArgumentTypeError("at least one frame number is required")
    if any(frame <= 0 for frame in frames):
        raise argparse.ArgumentTypeError("frame numbers are 1-based and must be positive")
    return frames


def load_frame(
    run_dir: Path,
    state: str,
    user_frame: int,
    transform: dict[str, float] | None = None,
    cell_size: tuple[int, int] | None = None,
    resize_policy: ResizePolicy | None = None,
) -> tuple[Path, Image.Image]:
    try:
        path = resolve_run_path(run_dir, f"frames/{state}/frame-{user_frame - 1}.png")
    except PathSafetyError as exc:
        raise SystemExit(str(exc)) from exc
    if not path.is_file():
        raise SystemExit(f"missing selected frame {user_frame}: {path}")
    image = Image.open(path).convert("RGBA")
    if transform and cell_size:
        image = apply_transform(
            image, transform, cell_size, policy=resize_policy
        )
    return path, image


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--state", required=True)
    parser.add_argument("--frames", type=parse_frames, help="1-based frame numbers, for example 2,3,4,5; defaults to curation.json selection")
    parser.add_argument("--name", required=True, help="output basename under qa/, without extension")
    parser.add_argument("--duration-ms", type=int, default=190)
    parser.add_argument("--delay-ticks", type=int, help="GIF delay in 1/100 second ticks; overrides --duration-ms")
    parser.add_argument("--note", default="")
    args = parser.parse_args()

    run_dir = args.run_dir.expanduser().resolve()
    qa_dir = run_dir / "qa"
    if "/" in args.name or "\\" in args.name:
        raise SystemExit("selected cycle name must be a basename under qa")
    try:
        gif_path = resolve_run_path(qa_dir, f"{args.name}.gif")
        contact_path = resolve_run_path(qa_dir, f"{args.name}-contact.png")
        manifest_path = resolve_run_path(qa_dir, f"{args.name}.json")
    except PathSafetyError as exc:
        raise SystemExit(str(exc)) from exc
    qa_dir.mkdir(parents=True, exist_ok=True)

    request = json.loads((run_dir / "sprite-request.json").read_text(encoding="utf-8"))
    resize_policy = resize_policy_for_request(request)
    cell = request["cell"]
    cell_size = (
        int(cell.get("width", cell.get("size", 0))),
        int(cell.get("height", cell.get("size", 0))),
    )
    default_count = int(request["states"][args.state]["frames"])
    curation = load_curation(run_dir)
    ordered, transforms = state_plan(curation, args.state, default_count)

    # explicit --frames (1-based) wins; otherwise use the curation.json selection.
    if args.frames is not None:
        user_frames = args.frames
    else:
        user_frames = [index + 1 for index in ordered]
    if not user_frames:
        raise SystemExit("curation has no selected frames for this cycle")

    selected = [
        load_frame(
            run_dir,
            args.state,
            number,
            transforms.get(number - 1),
            cell_size,
            resize_policy,
        )
        for number in user_frames
    ]
    frame_paths = [path for path, _image in selected]
    frames = [(number, image) for number, (_path, image) in zip(user_frames, selected)]

    duration_ms = delay_ticks_to_duration_ms(args.delay_ticks) if args.delay_ticks else max(1, args.duration_ms)
    save_clean_gif(
        [frame for _number, frame in frames],
        gif_path,
        duration_ms=duration_ms,
        loop=0,
    )

    contact_sheet([(number, path, frame) for number, (path, frame) in zip(user_frames, selected)]).save(contact_path)

    manifest = {
        "version": 1,
        "kind": "sprite-gen-selected-cycle",
        "run_dir": str(run_dir),
        "state": args.state,
        "name": args.name,
        "selected_user_frames": user_frames,
        "selected_zero_based_frames": [frame - 1 for frame in user_frames],
        "selection_source": "explicit-frames" if args.frames is not None else "curation.json",
        "transforms_applied": {str(n - 1): transforms[n - 1] for n in user_frames if (n - 1) in transforms},
        "duration_ms": duration_ms,
        "delay_ticks": round(duration_ms / 10),
        "loop": True,
        "note": args.note,
        "outputs": {
            "gif": str(gif_path.relative_to(run_dir)),
            "contact": str(contact_path.relative_to(run_dir)),
        },
        "source_frames": [
            {
                "user_frame": user_frame,
                "zero_based_frame": user_frame - 1,
                "path": str(path.relative_to(run_dir)),
                "sha256": sha256(path),
            }
            for user_frame, path in zip(user_frames, frame_paths)
        ],
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "ok": True,
                "manifest": str(manifest_path),
                "gif": str(gif_path),
                "contact": str(contact_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
