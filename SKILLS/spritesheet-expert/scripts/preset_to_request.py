#!/usr/bin/env python3
"""Convert a sprite-atlas preset into prepare_sprite_run.py request JSON."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


LOOP_HINTS = ("idle", "walk", "run", "running", "move", "blink", "talk", "sleep", "thinking")
FRAME_BUDGETS = ("default", "compact", "micro")
BACKGROUND_REMOVAL_METHODS = ("none", "chroma", "matte", "rembg", "ben2", "auto")
DEFAULT_REMBG_MODEL = "birefnet-general-lite"
DEFAULT_BEN2_MODEL = "PramaLLC/BEN2"
ART_DIRECTION_MODES = ("none", "pixel-art")
ART_DIRECTION_MODE_ALIASES: dict[str, str] = {}
ART_PROFILE_AUTO = "auto"
ART_PROFILES = {
    ART_PROFILE_AUTO,
    "pixel-core",
    "pixel-character",
    "pixel-motion",
    "pixel-sideview",
    "pixel-topdown",
    "pixel-isometric",
    "pixel-texture",
    "pixel-combat",
    "pixel-items-ui",
    "pixel-vfx",
    "pixel-shmup",
    "pixel-tiny",
    "pixel-environment",
}


def budgeted_frames(row_id: str, frames: int, budget: str, asset_kind: str) -> int:
    if asset_kind != "sprite" or budget == "default" or frames <= 1:
        return frames
    row = row_id.lower()

    def cap(value: int) -> int:
        return max(1, min(frames, value))

    if re.search(r"(^|-)(walk|walking|run|running|move)(-|$)", row):
        return cap(4 if budget == "micro" else 6)
    if any(part in row for part in ("death", "knockdown", "special", "heavy-attack", "win")):
        return cap(4 if budget == "micro" else 5)
    if any(part in row for part in ("attack", "punch", "kick", "cast", "dodge", "taunt")):
        return cap(3 if budget == "micro" else 4)
    if any(part in row for part in ("idle", "blink", "talk", "sleep", "thinking", "wave")):
        return cap(2 if budget == "micro" else 3)
    if any(part in row for part in ("hurt", "hit", "block", "crouch", "jump", "fall", "land")):
        return cap(2 if budget == "micro" else 3)
    return cap(3 if budget == "micro" else 4)


def fps_from_durations(row: dict[str, Any]) -> int:
    durations = row.get("durations_ms")
    if not durations:
        return 6
    avg = sum(int(ms) for ms in durations) / len(durations)
    return max(1, round(1000 / avg))


def default_loop(row_id: str) -> bool:
    return any(part in row_id for part in LOOP_HINTS)


def needs_motion_phase_guides(states: dict[str, dict[str, Any]]) -> bool:
    locomotion_tokens = {"walk", "walking", "run", "running", "move", "moving", "advance", "retreat", "dash", "dashing"}
    for state, entry in states.items():
        if int(entry.get("frames", 0)) not in {4, 6, 8}:
            continue
        workflows = entry.get("animation_workflows", [])
        workflow_text = " ".join(str(item) for item in workflows) if isinstance(workflows, list) else str(workflows)
        text = f"{state} {entry.get('action', '')} {workflow_text}".lower()
        tokens = {token for token in re.split(r"[^a-z0-9]+", text) if token}
        if "locomotion" in workflow_text or tokens & locomotion_tokens:
            return True
    return False


def state_action(row_id: str, camera: str, asset_kind: str = "sprite") -> str:
    words = row_id.replace("-", " ")
    if asset_kind == "tileset":
        return f"{camera} {words} tiles: runtime-ready variants with exact grid fit, readable collision surfaces, compatible edges, consistent palette, and projection"
    if asset_kind == "texture":
        return f"{words} seamless flat material texture samples with tileable edges, consistent texel density, and no perspective scene"
    if asset_kind != "sprite":
        return f"{camera} {words} still asset set with consistent palette, scale hierarchy, silhouette, practical pivots, and runtime isolation"
    if "run" in row_id or "walk" in row_id:
        return f"{camera} {words} full-body locomotion cycle with visible feet, alternating contacts, weight shift, body mechanics, loop seam, and stable identity"
    if "attack" in row_id or "punch" in row_id or "kick" in row_id:
        return f"{camera} {words} action: readable startup, active contact/extreme, recovery, strong line of action, no detached effects"
    if "special" in row_id:
        return f"{camera} {words} action: readable startup tell, active peak, recovery, body pose first, attached effects only"
    if "block" in row_id:
        return f"{camera} {words} defensive stance: planted feet, guarded silhouette, braced center of mass"
    if "crouch" in row_id or "duck" in row_id:
        return f"{camera} {words} grounded pose change: same character scale as idle, feet planted, body compressed lower"
    if "jump" in row_id or "leap" in row_id:
        return f"{camera} {words} action: same character scale as idle, vertical body-position arc, no zoom-to-fill"
    if "fall" in row_id:
        return f"{camera} {words} airborne descent: same character scale as idle, vertical placement changes only"
    if "land" in row_id:
        return f"{camera} {words} grounded landing compression: feet return to baseline, no enlarged body parts"
    if "knockdown" in row_id:
        return f"{camera} {words} reaction: force direction, balance loss, fall/contact, final down pose, no cropping"
    if "death" in row_id or "hurt" in row_id or "hit" in row_id:
        return f"{camera} {words} reaction with clear impact direction, overshoot/drag, and readable start/end poses"
    return f"{camera} {words} animation, same character identity across all frames"


def load_presets(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    return data["presets"]


def dedupe_ordered(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def normalize_profiles(values: Any, source: str) -> list[str]:
    if values in (None, False):
        return []
    if isinstance(values, str):
        profiles = [item.strip() for item in values.split(",") if item.strip()]
    elif isinstance(values, list):
        profiles = [str(item).strip() for item in values if str(item).strip()]
    else:
        raise SystemExit(f"{source} must be a string or list")
    unknown = [profile for profile in profiles if profile not in ART_PROFILES]
    if unknown:
        raise SystemExit(f"unknown {source} profile(s): {', '.join(unknown)}")
    return profiles


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("preset")
    parser.add_argument("--presets", type=Path, default=Path(__file__).parents[1] / "references" / "presets.json")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--style-preset", choices=["anime", "custom", "illustration", "painterly", "pixel-art", "realistic", "vector"], default=None)
    parser.add_argument("--style", default=None)
    parser.add_argument("--frame-budget", choices=FRAME_BUDGETS, default="default", help="optional sprite-only frame reduction; presets stay unchanged by default")
    parser.add_argument("--background-removal", choices=BACKGROUND_REMOVAL_METHODS, default=None)
    parser.add_argument("--background-model", default=None, help=f"model name; rembg default {DEFAULT_REMBG_MODEL}; ben2 default {DEFAULT_BEN2_MODEL}")
    parser.add_argument("--background-device", default=None, help="model-backed background removal device: auto, cpu, cuda, cuda:0, etc.")
    parser.add_argument("--alpha-matting", action="store_true")
    parser.add_argument("--motion-phase-guides", action="store_true")
    parser.add_argument("--art-direction", choices=ART_DIRECTION_MODES, default=None)
    parser.add_argument("--art-profile", action="append", choices=sorted(ART_PROFILES), help="repeatable Pixel-art profile id; use auto for inferred profiles")
    parser.add_argument("--states-json", help="custom-atlas states object")
    parser.add_argument("--states-file", type=Path, help="path to custom-atlas states JSON object")
    args = parser.parse_args()

    presets = load_presets(args.presets)
    if args.preset not in presets:
        raise SystemExit(f"unknown preset {args.preset!r}; choices: {', '.join(sorted(presets))}")
    preset = presets[args.preset]
    rows = preset.get("rows", [])
    budget_applied = False
    if args.states_json and args.states_file:
        raise SystemExit("use only one of --states-json or --states-file")
    if args.states_file:
        states = json.loads(args.states_file.read_text(encoding="utf-8-sig"))
    elif args.states_json:
        states = json.loads(args.states_json)
    else:
        if not rows:
            raise SystemExit("preset has no rows; pass --states-json")
        camera = str(preset.get("camera", "sprite"))
        asset_kind = str(preset.get("asset_kind", "sprite"))
        states = {}
        for row in rows:
            original_frames = int(row["frames"])
            frames = budgeted_frames(row["id"], original_frames, args.frame_budget, asset_kind)
            budget_applied = budget_applied or frames != original_frames
            entry = {
                "frames": frames,
                "fps": int(row.get("fps", fps_from_durations(row))),
                "loop": bool(row.get("loop", default_loop(row["id"]))),
                "action": str(row.get("action", state_action(row["id"], camera, asset_kind))),
            }
            if "durations_ms" in row and frames == original_frames:
                entry["durations_ms"] = row["durations_ms"]
            if "animation_workflows" in row:
                entry["animation_workflows"] = row["animation_workflows"]
            if "pose_geometry" in row:
                entry["pose_geometry"] = row["pose_geometry"]
            states[row["id"]] = entry

    preset_style = preset.get("style")
    style_preset = args.style_preset or preset.get("style_preset") or ("custom" if args.style or preset_style else "pixel-art")
    asset_kind = str(preset.get("asset_kind", "sprite"))
    request = {
        "preset": {
            "id": args.preset,
            "camera": preset.get("camera"),
            "columns": preset.get("columns"),
            "formats": preset.get("formats", ["png"]),
            "compatibility": preset.get("compatibility", []),
            "asset_kind": asset_kind,
        },
        "cell": preset.get("cell", {"width": 128, "height": 128}),
        "states": states,
        "asset_kind": asset_kind,
        "extraction_mode": preset.get("extraction_mode") or ("components" if asset_kind == "sprite" else "slots"),
        "style_preset": style_preset,
        "motion_phase_guides": bool(args.motion_phase_guides or needs_motion_phase_guides(states)),
    }
    if isinstance(preset.get("background_removal"), dict):
        request["background_removal"] = preset["background_removal"]
    if args.background_removal:
        request["background_removal"] = {
            "method": args.background_removal,
            "model": args.background_model or (DEFAULT_BEN2_MODEL if args.background_removal == "ben2" else DEFAULT_REMBG_MODEL),
            "device": args.background_device or "auto",
            "alpha_matting": bool(args.alpha_matting),
        }
    if budget_applied:
        request["frame_budget"] = args.frame_budget
    if "output" in preset:
        request["output"] = preset["output"]
    art_direction = args.art_direction or preset.get("art_direction")
    if art_direction in ART_DIRECTION_MODE_ALIASES:
        art_direction = ART_DIRECTION_MODE_ALIASES[art_direction]
    art_profiles = normalize_profiles(preset.get("art_profiles"), f"{args.preset}.art_profiles")
    user_art_profiles = args.art_profile or []
    if args.art_profile:
        art_profiles.extend(user_art_profiles)
    explicit_user_art_profiles = bool(user_art_profiles)
    if art_direction or art_profiles or style_preset == "pixel-art" or asset_kind in {"tileset", "texture"}:
        request["art_direction"] = {
            "mode": art_direction or ("pixel-art" if (explicit_user_art_profiles or style_preset == "pixel-art" or asset_kind in {"tileset", "texture"}) else "none"),
            "source": "pixel-art-wiki-derived",
            "reference": "references/pixel-art-direction.md",
            "workflow_reference": "references/pixel-animation-workflows.md",
            "profiles": dedupe_ordered(art_profiles) if art_profiles else [ART_PROFILE_AUTO],
        }
    if args.style:
        request["style"] = args.style
    elif preset_style:
        request["style"] = str(preset_style)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(request, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "preset": args.preset, "request": str(args.out), "states": list(states)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
