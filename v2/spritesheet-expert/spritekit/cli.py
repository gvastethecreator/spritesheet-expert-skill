"""Command line: plan → build → check."""

from __future__ import annotations

import argparse
from pathlib import Path

from . import builder, planner, runfile

LANES = ("animation",)


def check(args) -> int:
    run_dir = Path(args.run)
    run = runfile.load(run_dir)
    if not run.get("build"):
        raise SystemExit("nothing built yet. Run `sprite.py build` first.")
    problems: list[str] = []
    for name, src in run["sources"].items():
        path = run_dir / src["file"]
        if not path.is_file() or runfile.sha256(path) != src["sha256"]:
            problems.append(f"FAIL provenance: {src['file']} is missing or changed since ingest")
    for rel in ("atlas.png", "atlas.json", "review.html"):
        if not (run_dir / rel).is_file():
            problems.append(f"FAIL outputs: {rel} is missing")
    if run["build"]["pending"]:
        problems.append(f"WARN sources: no image yet for {', '.join(run['build']['pending'])}")
    for name, st in run["build"]["states"].items():
        for c in st["checks"]:
            if c["status"] != "pass":
                problems.append(f"{c['status'].upper()} {name}/{c['id']}: {c['detail']}")
    for line in problems:
        print(line)
    if not problems:
        print("all checks pass")
    if args.strict and problems:
        print(f"strict: {len(problems)} issue(s) block delivery")
        return 1
    return 0


def size(text: str) -> tuple[int, int]:
    w, _, h = text.partition("x")
    return int(w), int(h or w)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sprite.py", description="Plan, build and check game sprite runs.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("plan", help="write run.json, prompts and layout guides")
    p.add_argument("--out", required=True, help="run folder to create")
    p.add_argument("--lane", choices=LANES, default="animation")
    p.add_argument("--subject", required=True, help="who or what is drawn, e.g. 'a tired mimic accountant'")
    p.add_argument("--style", default="", help="art style in plain words; omit to leave it to the subject")
    p.add_argument("--view", default="", help="camera, e.g. side, top-down, three-quarter")
    p.add_argument("--notes", default="", help="extra direction added to every prompt")
    p.add_argument("--state", action="append", required=True, metavar="NAME:FRAMES[:MOTION[:FPS]]",
                   help="repeatable, e.g. walk:8 or strike:6:attack:12")
    p.add_argument("--anchor", help="approved identity image, attached to every prompt")
    p.add_argument("--cell", type=size, default=(256, 256), help="runtime cell, e.g. 256 or 384x288")
    p.add_argument("--baseline", type=float, default=0.9, help="ground line as a fraction of cell height")
    p.add_argument("--pose-guide", choices=("mannequin", "openpose"), default="mannequin",
                   help="how per-frame pose guides are drawn; OpenPose JSON is always written too")
    p.add_argument("--force", action="store_true", help="replace an existing plan")
    p.set_defaults(func=planner.plan)

    b = sub.add_parser("build", help="ingest sources and build frames, atlas, previews and review.html")
    b.add_argument("run")
    b.add_argument("--source", action="append", metavar="STATE=IMAGE", help="repeatable")
    b.add_argument("--provider", default="", help="who generated the source, recorded with its hash")
    b.add_argument("--cutout", choices=("auto", "alpha", "matte", "birefnet"), default="auto")
    b.set_defaults(func=builder.build)

    c = sub.add_parser("check", help="report problems; --strict exits 1 when any remain")
    c.add_argument("run")
    c.add_argument("--strict", action="store_true")
    c.set_defaults(func=check)

    args = parser.parse_args(argv)
    if getattr(args, "baseline", 0.5) and not 0.3 <= getattr(args, "baseline", 0.5) <= 1.0:
        parser.error("--baseline must be between 0.3 and 1.0")
    return args.func(args)
