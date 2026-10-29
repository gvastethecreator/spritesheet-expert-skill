#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Generic animation contract QA for sprite atlas rows.

This script checks the animation workflows recorded by the sprite pipeline
or inferred from row names/actions. It is intentionally heuristic: it catches
obvious contract failures, then writes the visual checklist that still must be
reviewed by a human or browser/prototype pass.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from PIL import Image

from runio import atomic_write_text


WORKFLOW_ORDER = [
    "idle-breath",
    "fighting-stance-idle",
    "gesture-loop",
    "front-fps-creature-locomotion",
    "front-fps-creature-attack",
    "sideview-locomotion",
    "topdown-locomotion",
    "combat-quick-strike",
    "combat-power-strike",
    "topdown-weapon-attack",
    "responsive-jump",
    "hit-reaction-knockdown",
    "run-gun-layered-motion",
    "vfx-buildup-peak-decay",
    "water-loop",
    "wind-ambient-loop",
    "pickup-feedback",
    "tiny-motion",
]

LOCOMOTION_WORKFLOWS = {
    "front-fps-creature-locomotion",
    "sideview-locomotion",
    "topdown-locomotion",
    "run-gun-layered-motion",
}
ACTION_WORKFLOWS = {"front-fps-creature-attack", "combat-quick-strike", "combat-power-strike", "topdown-weapon-attack"}
LOOP_WORKFLOWS = {"idle-breath", "fighting-stance-idle", "gesture-loop", "water-loop", "wind-ambient-loop", "pickup-feedback"}

WORKFLOW_CONTRACTS: dict[str, dict[str, Any]] = {
    "idle-breath": {
        "min_frames": 2,
        "phases": ["anchor", "rise-or-hold", "down-accent", "return"],
        "visual_checks": [
            "feet or runtime pivot remain stable unless a step is intentional",
            "secondary motion is smaller and later than torso rhythm",
            "end-to-start loop does not pop at playback speed",
        ],
    },
    "fighting-stance-idle": {
        "min_frames": 2,
        "phases": ["combat stance", "breath or weight rhythm", "extremity offset", "return"],
        "visual_checks": [
            "guard, support side, and weapon or fist logic read clearly",
            "extremities amplify the torso without becoming random bobbing",
            "stance communicates role, not a generic idle with raised hands",
        ],
    },
    "gesture-loop": {
        "min_frames": 3,
        "phases": ["identity anchor", "gesture anticipation", "clear accent", "return to anchor"],
        "visual_checks": [
            "the gesture reads from body and limb motion without detached symbols",
            "feet, camera, scale, and character identity remain stable",
            "the final-to-first transition returns cleanly without an arm or prop pop",
        ],
    },
    "front-fps-creature-locomotion": {
        "min_frames": 4,
        "phases": ["idle anchor", "contact or pressure A", "idle anchor", "opposite contact or pressure B"],
        "visual_checks": [
            "the creature remains full frontal without camera rotation, scale change, or whole-body mirror sway",
            "the two active poses use opposite anatomy appropriate to the creature, not a generic biped leg mirror",
            "grounded limbs, crawling body mass, wings, tails, or lower bodies follow the declared movement source",
        ],
    },
    "front-fps-creature-attack": {
        "min_frames": 4,
        "phases": ["idle anchor", "anatomical anticipation", "frontal contact", "idle recovery"],
        "visual_checks": [
            "the attack uses the creature's declared anatomy instead of a generic one-hand strike",
            "anticipation and contact remain fully frontal and preserve body identity, scale, and limb count",
            "the contact pose is threatening and the final frame returns to the exact idle anchor",
        ],
    },
    "sideview-locomotion": {
        "min_frames": 4,
        "phases": ["contact A", "down/pass", "contact B", "up/pass"],
        "visual_checks": [
            "frame 1 and the opposite contact frame show opposite anatomical support legs",
            "pass/down frames do not keep both legs drifting to the same side",
            "foot sliding, frozen knees, and loop seam are reviewed at playback speed",
        ],
    },
    "topdown-locomotion": {
        "min_frames": 4,
        "phases": ["contact A", "pass/down", "contact B", "pass/up"],
        "visual_checks": [
            "each direction row proves opposite support/contact legs independently",
            "front/up/side projection keeps body volume and limb length consistent",
            "hair, robes, capes, or equipment do not hide the leg-phase proof",
        ],
    },
    "combat-quick-strike": {
        "min_frames": 4,
        "phases": ["guard/start", "brief smear", "hit/contact", "follow-through", "recover"],
        "visual_checks": [
            "active/contact frame is the strongest silhouette",
            "visual range matches gameplay range",
            "smear follows the motion direction and does not appear during recovery",
        ],
    },
    "combat-power-strike": {
        "min_frames": 5,
        "phases": ["load", "fast smear", "hit/contact", "held follow-through", "recovery", "settle"],
        "visual_checks": [
            "anticipation communicates weight instead of input lag",
            "active/contact frame reads as committed impact",
            "overshoot and recovery preserve the same body scale",
        ],
    },
    "topdown-weapon-attack": {
        "min_frames": 5,
        "phases": ["anticipation", "forward smear", "contact/rebound", "follow-through", "recover"],
        "visual_checks": [
            "weapon stays in the same hand across directions",
            "hitbox reach feels fair across angles",
            "smear appears on the forward strike, not on anticipation or recovery",
        ],
    },
    "responsive-jump": {
        "min_frames": 3,
        "phases": ["launch/up", "airborne", "down", "landing/compression"],
        "visual_checks": [
            "body scale remains locked to idle while the character moves through the slot",
            "up and down poses are distinct enough for input response",
            "dust or motion marks do not compensate for weak body placement",
        ],
    },
    "hit-reaction-knockdown": {
        "min_frames": 4,
        "phases": ["impact direction", "recoil/drag", "loss of balance", "ground/contact", "settle"],
        "visual_checks": [
            "force direction is readable",
            "pose loses support or braces instead of becoming a surprised idle",
            "final/contact pose is not cropped and keeps character scale",
        ],
    },
    "run-gun-layered-motion": {
        "min_frames": 4,
        "phases": ["leg locomotion", "torso/weapon layer", "gun sway", "loop return"],
        "visual_checks": [
            "legs keep flowing while the upper body aims or shoots",
            "weapon sway rides shoulder/body bounce",
            "hair and cloth do not fight the main run rhythm",
        ],
    },
    "vfx-buildup-peak-decay": {
        "min_frames": 4,
        "phases": ["buildup/source", "peak", "decay", "fade or loop return"],
        "visual_checks": [
            "emitter or contact anchor remains stable",
            "peak frame is visually dominant and not a linear same-energy ramp",
            "alpha fade is safe and does not preserve chroma-colored cores",
        ],
    },
    "water-loop": {
        "min_frames": 3,
        "phases": ["flow guide", "travel/displacement", "splash or ripple response", "loop closure"],
        "visual_checks": [
            "loop math closes without end-to-start pop",
            "flow follows the intended river, waterfall, wave, or reflection path",
            "bands, splashes, and reflections do not all move in sync",
        ],
    },
    "wind-ambient-loop": {
        "min_frames": 3,
        "phases": ["material choice", "flow points", "propagated wave", "loop closure"],
        "visual_checks": [
            "motion follows flow points instead of random per-frame shifts",
            "layers are offset in timing",
            "wind adds life without stealing focus from the subject",
        ],
    },
    "pickup-feedback": {
        "min_frames": 2,
        "phases": ["idle affordance", "readability", "meaningful feedback", "short stable loop"],
        "visual_checks": [
            "item reads as collectible or confirmation, not hazard/projectile/VFX",
            "silhouette and local color carry the read before detail",
            "loop stays noticeable without competing with player action",
        ],
    },
    "tiny-motion": {
        "min_frames": 2,
        "max_frames": 4,
        "phases": ["strong key frame", "1px or cluster change", "return or alternate key"],
        "visual_checks": [
            "each frame changes the runtime read",
            "detail does not flicker at playback size",
            "motion uses one-pixel or cluster-scale changes rather than smooth filler",
        ],
    },
}


def dedupe_ordered(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def ordered_workflows(values: list[str]) -> list[str]:
    requested = dedupe_ordered(values)
    unknown = sorted(set(requested) - set(WORKFLOW_ORDER))
    if unknown:
        raise ValueError(f"unknown animation workflows: {', '.join(unknown)}")
    return [workflow for workflow in WORKFLOW_ORDER if workflow in requested]


def normalized_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def state_tokens(state: str, entry: dict[str, Any] | None = None) -> set[str]:
    parts = [state]
    if entry:
        parts.append(str(entry.get("action", "")))
        parts.append(str(entry.get("description", "")))
    return set(re.findall(r"[a-z0-9]+", " ".join(parts).lower()))


def request_descriptor(request: dict[str, Any], state: str, entry: dict[str, Any]) -> str:
    parts = [
        str(request.get("preset", "")),
        str(request.get("asset_kind", "")),
        str(request.get("style", "")),
        str(request.get("style_preset", "")),
        str(request.get("camera", "")),
        str(state),
        str(entry.get("action", "")),
        str(entry.get("description", "")),
    ]
    character = request.get("character") if isinstance(request.get("character"), dict) else {}
    parts.append(str(character.get("description", "")))
    return " ".join(parts).lower()


def workflow_tokens_from_art_direction(art_direction: dict[str, Any], state: str) -> list[str]:
    rows = art_direction.get("rows")
    if isinstance(rows, dict):
        row = rows.get(state)
        if isinstance(row, dict):
            return [item for item in normalized_list(row.get("animation_workflows")) if item != "auto"]
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict) and str(row.get("state", "")) == state:
                return [item for item in normalized_list(row.get("animation_workflows")) if item != "auto"]
    return []


def infer_workflows(request: dict[str, Any], state: str, entry: dict[str, Any]) -> list[str]:
    descriptor = request_descriptor(request, state, entry)
    tokens = state_tokens(state, entry)
    state_only_tokens = set(re.findall(r"[a-z0-9]+", state.lower()))
    asset_kind = str(request.get("asset_kind", "sprite")).lower()
    default_semantics = (
        "animation" if asset_kind == "sprite" else "effects" if asset_kind == "vfx" else "variants"
    )
    frame_semantics = str(request.get("frame_semantics", default_semantics)).lower()
    frame_count = int(entry.get("frames", 0) or 0)
    if frame_semantics not in {"animation", "effects"} or frame_count <= 1:
        return []
    cell = request.get("cell") if isinstance(request.get("cell"), dict) else {}
    cell_width = int(cell.get("width", cell.get("size", 999)))
    cell_height = int(cell.get("height", cell.get("size", 999)))

    is_topdown = (
        "topdown" in descriptor
        or "top-down" in descriptor
        or bool(state_only_tokens & {"up", "down", "north", "south", "east", "west"})
    )
    is_sideview = "sideview" in descriptor or "side-view" in descriptor or "platformer" in descriptor
    fighting = "fighting" in descriptor or "combat" in descriptor or bool(tokens & {"guard", "block", "stance"})

    workflows: list[str] = []
    if asset_kind == "sprite":
        if cell_width <= 32 or cell_height <= 32 or bool(tokens & {"tiny", "8bit", "8-bit", "nes"}):
            workflows.append("tiny-motion")
        if state_only_tokens & {"idle", "stance", "guard", "block"}:
            workflows.append("fighting-stance-idle" if fighting else "idle-breath")
        if state_only_tokens & {"wave", "waving", "greet", "greeting", "salute", "saluting", "emote"}:
            workflows.append("gesture-loop")
        if tokens & {"walk", "walking", "run", "running", "move", "moving", "dash", "dashing"}:
            workflows.append("topdown-locomotion" if is_topdown and not is_sideview else "sideview-locomotion")
            if tokens & {"gun", "guns", "shoot", "shooting", "aim", "aiming"} or "run-n-gun" in descriptor:
                workflows.append("run-gun-layered-motion")
        if tokens & {"jump", "jumping", "leap", "leaping", "land", "landing", "fall", "falling"}:
            workflows.append("responsive-jump")
        if tokens & {"hit", "hurt", "hitstun", "knockdown", "death", "die", "dying", "collapse"}:
            workflows.append("hit-reaction-knockdown")
        if tokens & {
            "attack",
            "attacking",
            "punch",
            "punching",
            "jab",
            "cross",
            "kick",
            "kicking",
            "slash",
            "slashing",
            "swing",
            "sword",
            "spear",
            "hammer",
            "mace",
            "melee",
            "special",
            "cast",
        }:
            if is_topdown:
                workflows.append("topdown-weapon-attack")
            elif tokens & {"jab", "punch", "punching", "frontkick", "front-kick"} and not tokens & {
                "heavy",
                "power",
                "round",
                "roundhouse",
                "slash",
                "sword",
                "spear",
                "hammer",
                "mace",
                "special",
            }:
                workflows.append("combat-quick-strike")
            else:
                workflows.append("combat-power-strike")

    if asset_kind == "vfx" or tokens & {"vfx", "fx", "effect", "effects", "explosion", "impact", "spark", "smoke", "fire", "electric"}:
        workflows.append("vfx-buildup-peak-decay")
    water_tokens = {"water", "waterfall", "river", "ripple", "splash", "lake", "ocean"}
    water_context = bool(tokens & water_tokens)
    if water_context or (
        bool(tokens & {"wave", "waves"})
        and asset_kind in {"vfx", "tileset", "texture", "background"}
    ):
        workflows.append("water-loop")
    if tokens & {"wind", "fabric", "cloth", "hair", "leaf", "leaves", "grass", "tree", "dust", "cloud", "swirl"}:
        workflows.append("wind-ambient-loop")
    if asset_kind in {"asset", "prop", "props", "icon", "ui"} and tokens & {
        "pickup",
        "pickups",
        "item",
        "items",
        "coin",
        "coins",
        "gem",
        "gems",
        "heart",
        "powerup",
        "powerups",
        "icon",
        "icons",
    }:
        workflows.append("pickup-feedback")
    return ordered_workflows(workflows)


def workflows_for_state(
    request: dict[str, Any],
    art_direction: dict[str, Any],
    state: str,
    entry: dict[str, Any],
) -> tuple[list[str], str]:
    explicit: list[str] = []
    explicit.extend(item for item in normalized_list(request.get("animation_workflows")) if item != "auto")
    explicit.extend(item for item in normalized_list(entry.get("animation_workflows")) if item != "auto")
    art = workflow_tokens_from_art_direction(art_direction, state)
    if explicit:
        return ordered_workflows(explicit), "request"
    if art:
        return ordered_workflows(art), "art-direction"
    return infer_workflows(request, state, entry), "inferred"


def selected_states(
    request: dict[str, Any],
    rows_by_state: dict[str, dict[str, Any]],
    art_direction: dict[str, Any],
    mode: str,
) -> list[str]:
    states = request.get("states", {})
    if mode == "all":
        return list(states)
    if mode == "animated":
        result: list[str] = []
        for state, entry in states.items():
            row = rows_by_state.get(state, {})
            workflows, _source = workflows_for_state(request, art_direction, state, entry)
            if workflows or int(entry.get("frames", row.get("frames", 0)) or 0) > 1:
                result.append(state)
        return result
    return [state.strip() for state in mode.split(",") if state.strip()]


def load_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def load_frames(run_dir: Path, row: dict[str, Any]) -> list[Image.Image]:
    frames = []
    for rel in row.get("files", []):
        with Image.open(run_dir / rel) as opened:
            frames.append(opened.convert("RGBA"))
    return frames


def alpha_mask_bytes(frame: Image.Image, threshold: int = 16) -> bytes:
    return frame.getchannel("A").point(lambda value: 255 if value > threshold else 0).tobytes()


def alpha_bbox(frame: Image.Image, threshold: int = 16) -> tuple[int, int, int, int] | None:
    return frame.getchannel("A").point(lambda value: 255 if value > threshold else 0).getbbox()


def bbox_metrics(frame: Image.Image) -> dict[str, float]:
    bbox = alpha_bbox(frame)
    mask = alpha_mask_bytes(frame)
    area = sum(1 for value in mask if value)
    if not bbox:
        return {
            "x0": 0.0,
            "y0": 0.0,
            "x1": 0.0,
            "y1": 0.0,
            "width": 0.0,
            "height": 0.0,
            "center_x": 0.0,
            "center_y": 0.0,
            "bottom": 0.0,
            "alpha_area": 0.0,
        }
    x0, y0, x1, y1 = bbox
    width = max(1, x1 - x0)
    height = max(1, y1 - y0)
    return {
        "x0": x0 / frame.width,
        "y0": y0 / frame.height,
        "x1": x1 / frame.width,
        "y1": y1 / frame.height,
        "width": width / frame.width,
        "height": height / frame.height,
        "center_x": (x0 + x1) / (2 * frame.width),
        "center_y": (y0 + y1) / (2 * frame.height),
        "bottom": y1 / frame.height,
        "alpha_area": area / (frame.width * frame.height),
    }


def normalized_pair_diff(left: Image.Image, right: Image.Image, y_start_ratio: float = 0.0) -> float:
    if left.size != right.size:
        return 1.0
    width, height = left.size
    y_start = max(0, min(height - 1, round(height * y_start_ratio)))
    left_mask = alpha_mask_bytes(left.crop((0, y_start, width, height)))
    right_mask = alpha_mask_bytes(right.crop((0, y_start, width, height)))
    union = 0
    xor = 0
    for left_value, right_value in zip(left_mask, right_mask):
        left_on = bool(left_value)
        right_on = bool(right_value)
        if left_on or right_on:
            union += 1
            if left_on != right_on:
                xor += 1
    return xor / union if union else 0.0


def normalized_visual_pair_diff(
    left: Image.Image,
    right: Image.Image,
    *,
    channel_threshold: int = 24,
) -> float:
    """Measure visible interior changes that do not alter the alpha silhouette."""
    if left.size != right.size:
        return 1.0
    left_pixels = left.convert("RGBA").get_flattened_data()
    right_pixels = right.convert("RGBA").get_flattened_data()
    union = 0
    changed = 0
    for left_pixel, right_pixel in zip(left_pixels, right_pixels):
        if left_pixel[3] == 0 and right_pixel[3] == 0:
            continue
        union += 1
        if max(abs(left_pixel[index] - right_pixel[index]) for index in range(3)) >= channel_threshold:
            changed += 1
    return changed / union if union else 0.0


def metric_range(metrics: list[dict[str, float]], key: str) -> float:
    values = [metric[key] for metric in metrics]
    return max(values) - min(values) if values else 0.0


def alpha_area_range_ratio(metrics: list[dict[str, float]]) -> float:
    values = [metric["alpha_area"] for metric in metrics]
    high = max(values) if values else 0.0
    low = min(values) if values else 0.0
    return (high - low) / high if high > 0 else 0.0


def support_balance(frame: Image.Image) -> float:
    bbox = alpha_bbox(frame)
    if not bbox:
        return 0.0
    x0, y0, x1, y1 = bbox
    width = max(1, x1 - x0)
    center_x = (x0 + x1) / 2
    y_start = y0 + round((y1 - y0) * 0.68)
    total = 0
    weighted = 0.0
    alpha = frame.getchannel("A")
    for y in range(y_start, y1):
        for x in range(x0, x1):
            if alpha.getpixel((x, y)) > 16:
                total += 1
                weighted += (x - center_x) / width
    return weighted / total if total else 0.0


def support_side(value: float, threshold: float) -> str:
    if value <= -threshold:
        return "left"
    if value >= threshold:
        return "right"
    return "center/ambiguous"


def contact_phase_check(
    frames: list[Image.Image],
    args: argparse.Namespace,
    *,
    shared_idle: bool = False,
    min_pose_diff: float | None = None,
) -> dict[str, Any] | None:
    if len(frames) < 4:
        return None
    balances = [support_balance(frame) for frame in frames]
    first_index = 1 if shared_idle and len(frames) == 4 else 0
    opposite_index = 3 if shared_idle and len(frames) == 4 else (
        len(frames) // 2 if len(frames) >= 6 else 2
    )
    first = balances[first_index]
    opposite = balances[opposite_index]
    first_side = support_side(first, args.min_contact_balance_abs)
    opposite_side = support_side(opposite, args.min_contact_balance_abs)
    contact_delta = abs(opposite - first)
    contact_pose_diff = normalized_pair_diff(
        frames[first_index], frames[opposite_index], args.lower_body_start
    )
    effective_min_pose_diff = (
        args.min_opposite_contact_pose_diff if min_pose_diff is None else min_pose_diff
    )
    ok = contact_pose_diff >= effective_min_pose_diff
    reason = "distinct opposite-contact lower-body poses"
    if not ok:
        reason = "opposite contact lower-body pose is duplicated or too similar"
    return {
        "ok": ok,
        "phase_layout": "idle-phase-a-idle-phase-b" if first_index == 1 else "standard-contact-cycle",
        "first_contact_index": first_index,
        "first_contact_frame": first_index + 1,
        "frame_1_index": first_index,
        "frame_1_support_balance": round(first, 4),
        "frame_1_support_side": first_side,
        "opposite_contact_index": opposite_index,
        "opposite_contact_frame": opposite_index + 1,
        "opposite_contact_support_balance": round(opposite, 4),
        "opposite_contact_support_side": opposite_side,
        "contact_delta": round(contact_delta, 4),
        "opposite_contact_pose_diff": round(contact_pose_diff, 4),
        "min_opposite_contact_pose_diff": effective_min_pose_diff,
        "min_contact_balance_abs": args.min_contact_balance_abs,
        "min_contact_opposition": args.min_contact_opposition,
        "screen_side_is_diagnostic_only": True,
        "anatomical_leg_alternation_requires_visual_review": True,
        "reason": reason,
    }


def loop_closure_diff(frames: list[Image.Image]) -> float:
    if len(frames) < 2:
        return 0.0
    return normalized_pair_diff(frames[-1], frames[0])


def inspect_locomotion(
    workflows: list[str],
    frames: list[Image.Image],
    metrics: list[dict[str, float]],
    args: argparse.Namespace,
    shared_idle: bool = False,
    creature_motion: dict[str, Any] | None = None,
) -> tuple[list[str], list[str], dict[str, Any]]:
    errors: list[str] = []
    warnings: list[str] = []
    lower_diffs = [
        normalized_pair_diff(frames[index], frames[(index + 1) % len(frames)], args.lower_body_start)
        for index in range(len(frames))
    ] if len(frames) > 1 else []
    balances = [support_balance(frame) for frame in frames]
    support_range = max(balances) - min(balances) if balances else 0.0
    anatomy = str((creature_motion or {}).get("anatomy", "")).strip().lower()
    locomotion = str((creature_motion or {}).get("locomotion", "")).strip().lower()
    is_amorphous_pulse = anatomy == "amorphous" and locomotion == "pulse"
    min_average_lower_diff = 0.05 if is_amorphous_pulse else args.min_average_lower_diff
    min_pair_lower_diff = 0.03 if is_amorphous_pulse else args.min_pair_lower_diff
    min_opposite_contact_pose_diff = (
        0.05 if is_amorphous_pulse else args.min_opposite_contact_pose_diff
    )
    threshold_policy = "amorphous-pulse" if is_amorphous_pulse else "default"
    phase = contact_phase_check(
        frames,
        args,
        shared_idle=shared_idle,
        min_pose_diff=min_opposite_contact_pose_diff,
    )

    average_lower = sum(lower_diffs) / len(lower_diffs) if lower_diffs else 0.0
    min_lower = min(lower_diffs) if lower_diffs else 0.0
    if len(frames) >= 2 and average_lower < min_average_lower_diff:
        errors.append(
            f"lower-body silhouette barely changes (avg {average_lower:.3f}; expected >= {min_average_lower_diff:.3f})"
        )
    if len(frames) >= 3 and min_lower < min_pair_lower_diff:
        errors.append(
            f"one or more lower-body transitions are too similar (min {min_lower:.3f}; expected >= {min_pair_lower_diff:.3f})"
        )
    if len(frames) >= 4 and phase and not phase["ok"]:
        errors.append(
            "opposite-contact candidate duplicates the first lower-body pose "
            f"(frame {phase['first_contact_frame']} vs frame "
            f"{phase['opposite_contact_frame']} lower-body diff "
            f"{phase['opposite_contact_pose_diff']:.3f}; expected >= "
            f"{phase['min_opposite_contact_pose_diff']:.3f}; {phase['reason']})"
        )
    if len(frames) >= 3 and support_range < args.min_support_range:
        warnings.append(
            f"lower-body screen-space balance barely varies (range {support_range:.3f}; "
            f"diagnostic target >= {args.min_support_range:.3f})"
        )
    if "run-gun-layered-motion" in workflows and metric_range(metrics, "center_y") < args.min_center_range:
        warnings.append("run-gun row has little torso/body bob; verify upper-body layer is not frozen")

    return errors, warnings, {
        "average_lower_body_diff": round(average_lower, 4),
        "min_lower_body_diff": round(min_lower, 4),
        "support_balance_range": round(support_range, 4),
        "support_balances": [round(value, 4) for value in balances],
        "contact_phase_check": phase,
        "threshold_policy": threshold_policy,
        "creature_anatomy": anatomy or None,
        "creature_locomotion": locomotion or None,
        "min_average_lower_diff": min_average_lower_diff,
        "min_pair_lower_diff": min_pair_lower_diff,
    }


def inspect_action(
    workflows: list[str],
    metrics: list[dict[str, float]],
    pair_diffs: list[float],
    args: argparse.Namespace,
    visual_pair_diffs: list[float] | None = None,
) -> tuple[list[str], list[str], dict[str, Any]]:
    errors: list[str] = []
    warnings: list[str] = []
    width_range = metric_range(metrics, "width")
    height_range = metric_range(metrics, "height")
    center_x_range = metric_range(metrics, "center_x")
    center_y_range = metric_range(metrics, "center_y")
    area_range = alpha_area_range_ratio(metrics)
    area_values = [metric["alpha_area"] for metric in metrics]
    extent_scores = [metric["width"] * metric["height"] for metric in metrics]
    peak_area_index = area_values.index(max(area_values)) if area_values else None
    peak_extent_index = extent_scores.index(max(extent_scores)) if extent_scores else None
    average_diff = sum(pair_diffs) / len(pair_diffs) if pair_diffs else 0.0
    average_visual_diff = (
        sum(visual_pair_diffs) / len(visual_pair_diffs)
        if visual_pair_diffs
        else 0.0
    )
    min_visual_diff = float(getattr(args, "min_action_visual_diff", 0.003))
    max_motion_range = max(width_range, height_range, center_x_range, center_y_range, area_range)

    if (
        max_motion_range < args.min_action_motion_range
        and average_diff < args.min_action_pair_diff
        and average_visual_diff < min_visual_diff
    ):
        errors.append(
            "action row is too static to prove startup/active/recovery phases "
            f"(motion range {max_motion_range:.3f}, alpha diff {average_diff:.3f}, "
            f"visual diff {average_visual_diff:.3f})"
        )
    if peak_extent_index in {0, len(metrics) - 1} and len(metrics) >= 4:
        warnings.append("strongest extent is on the first or last frame; verify active/contact is not missing")
    if "topdown-weapon-attack" in workflows and center_x_range < 0.015 and center_y_range < 0.015:
        warnings.append("top-down attack has little reach displacement; verify hitbox range visually")

    return errors, warnings, {
        "bbox_width_range": round(width_range, 4),
        "bbox_height_range": round(height_range, 4),
        "center_x_range": round(center_x_range, 4),
        "center_y_range": round(center_y_range, 4),
        "alpha_area_range_ratio": round(area_range, 4),
        "average_pair_diff": round(average_diff, 4),
        "average_visual_pair_diff": round(average_visual_diff, 4),
        "min_action_visual_diff": min_visual_diff,
        "peak_area_frame": None if peak_area_index is None else peak_area_index + 1,
        "peak_extent_frame": None if peak_extent_index is None else peak_extent_index + 1,
    }


def inspect_jump(metrics: list[dict[str, float]], args: argparse.Namespace) -> tuple[list[str], list[str], dict[str, Any]]:
    errors: list[str] = []
    warnings: list[str] = []
    center_y_range = metric_range(metrics, "center_y")
    bottom_range = metric_range(metrics, "bottom")
    width_range = metric_range(metrics, "width")
    height_range = metric_range(metrics, "height")
    if max(center_y_range, bottom_range) < args.min_jump_vertical_range:
        errors.append(
            f"jump/fall row has too little vertical placement change (range {max(center_y_range, bottom_range):.3f})"
        )
    if width_range > args.max_scale_range or height_range > args.max_scale_range:
        warnings.append("jump/fall bbox changes a lot; verify this is pose compression, not whole-character rescale")
    return errors, warnings, {
        "center_y_range": round(center_y_range, 4),
        "bottom_range": round(bottom_range, 4),
        "bbox_width_range": round(width_range, 4),
        "bbox_height_range": round(height_range, 4),
    }


def inspect_reaction(
    metrics: list[dict[str, float]],
    pair_diffs: list[float],
    args: argparse.Namespace,
) -> tuple[list[str], list[str], dict[str, Any]]:
    errors: list[str] = []
    warnings: list[str] = []
    center_x_range = metric_range(metrics, "center_x")
    center_y_range = metric_range(metrics, "center_y")
    height_range = metric_range(metrics, "height")
    average_diff = sum(pair_diffs) / len(pair_diffs) if pair_diffs else 0.0
    if max(center_x_range, center_y_range, height_range) < args.min_reaction_motion_range and average_diff < args.min_action_pair_diff:
        errors.append("reaction/knockdown row is too static to prove impact, recoil, and settle phases")
    if center_x_range < 0.01 and center_y_range < 0.01:
        warnings.append("force direction may be unreadable; verify recoil/drag visually")
    return errors, warnings, {
        "center_x_range": round(center_x_range, 4),
        "center_y_range": round(center_y_range, 4),
        "bbox_height_range": round(height_range, 4),
        "average_pair_diff": round(average_diff, 4),
    }


def vfx_signal_area(frame: Image.Image) -> int:
    rgba = frame.convert("RGBA")
    total = 0
    data = rgba.tobytes()
    for index in range(0, len(data), 4):
        red, green, blue, alpha = data[index : index + 4]
        if alpha <= 16:
            continue
        value = max(red, green, blue)
        saturation = value - min(red, green, blue)
        cool_energy = blue >= 140 and green >= 96 and blue >= red + 18
        hot_energy = red >= 150 and green >= 80 and red >= blue + 18
        saturated_energy = value >= 128 and saturation >= 48
        if cool_energy or hot_energy or saturated_energy:
            total += 1
    return total


def range_ratio(values: list[int | float]) -> float:
    if not values:
        return 0.0
    peak = max(values)
    if peak <= 0:
        return 0.0
    return (peak - min(values)) / peak


def inspect_vfx(
    frames: list[Image.Image],
    metrics: list[dict[str, float]],
    pair_diffs: list[float],
    args: argparse.Namespace,
) -> tuple[list[str], list[str], dict[str, Any]]:
    errors: list[str] = []
    warnings: list[str] = []
    area_values = [metric["alpha_area"] for metric in metrics]
    area_range = alpha_area_range_ratio(metrics)
    peak_index = area_values.index(max(area_values)) if area_values else None
    signal_values = [vfx_signal_area(frame) for frame in frames]
    signal_range = range_ratio(signal_values)
    max_pair_diff = max(pair_diffs) if pair_diffs else 0.0
    if (
        area_range < args.min_vfx_area_range
        and signal_range < args.min_vfx_area_range
        and max_pair_diff < args.min_action_pair_diff
    ):
        errors.append(
            "VFX area/signal barely changes; buildup/peak/decay is not readable "
            f"(alpha range {area_range:.3f}, signal range {signal_range:.3f}, max pair diff {max_pair_diff:.3f})"
        )
    if peak_index in {0, len(metrics) - 1} and len(metrics) >= 4:
        warnings.append("VFX peak is at the first or last frame; verify buildup/decay staging")
    return errors, warnings, {
        "alpha_area_range_ratio": round(area_range, 4),
        "signal_area_range_ratio": round(signal_range, 4),
        "signal_areas": signal_values,
        "max_pair_diff": round(max_pair_diff, 4),
        "peak_area_frame": None if peak_index is None else peak_index + 1,
    }


def inspect_loop(
    workflows: list[str],
    frames: list[Image.Image],
    metrics: list[dict[str, float]],
    pair_diffs: list[float],
    args: argparse.Namespace,
) -> tuple[list[str], list[str], dict[str, Any]]:
    errors: list[str] = []
    warnings: list[str] = []
    closure = loop_closure_diff(frames)
    area_range = alpha_area_range_ratio(metrics)
    average_diff = sum(pair_diffs) / len(pair_diffs) if pair_diffs else 0.0
    transition_diffs = pair_diffs[:-1] if len(pair_diffs) > 1 else pair_diffs
    transition_average = (
        sum(transition_diffs) / len(transition_diffs) if transition_diffs else 0.0
    )
    if closure > args.max_loop_closure_diff:
        warnings.append(f"loop seam has high alpha difference ({closure:.3f}); verify end-to-start playback")
    if "gesture-loop" in workflows and closure > max(0.18, transition_average * 1.35):
        errors.append(
            "gesture loop does not return cleanly to its identity anchor "
            f"(closure {closure:.3f}, in-loop average {transition_average:.3f})"
        )
    if "water-loop" in workflows or "wind-ambient-loop" in workflows:
        if average_diff < args.min_ambient_pair_diff:
            errors.append(f"ambient loop barely moves (avg diff {average_diff:.3f})")
        if area_range > args.max_ambient_area_range:
            warnings.append("ambient loop alpha area changes a lot; verify flow is not popping or stealing focus")
    if workflows and set(workflows).issubset({"idle-breath", "fighting-stance-idle", "pickup-feedback"}) and average_diff < 0.01:
        warnings.append("loop is nearly static; verify this was intended and not a missing animation row")
    return errors, warnings, {
        "loop_closure_diff": round(closure, 4),
        "alpha_area_range_ratio": round(area_range, 4),
        "average_pair_diff": round(average_diff, 4),
        "average_in_loop_transition_diff": round(transition_average, 4),
    }


def lower_body_center_x(frame: Image.Image, y_start_ratio: float) -> float | None:
    width, height = frame.size
    y_start = max(0, min(height - 1, round(height * y_start_ratio)))
    bbox = alpha_bbox(frame.crop((0, y_start, width, height)))
    if not bbox:
        return None
    return (bbox[0] + bbox[2]) / (2 * width)


def inspect_gesture_planted_lower_body(
    frames: list[Image.Image],
    args: argparse.Namespace,
) -> tuple[list[str], list[str], dict[str, Any]]:
    errors: list[str] = []
    warnings: list[str] = []
    anchor_diffs = [
        normalized_pair_diff(
            frames[0], frame, args.gesture_lower_body_start
        )
        for frame in frames
    ] if frames else []
    centers = [
        lower_body_center_x(frame, args.gesture_lower_body_start)
        for frame in frames
    ]
    valid_centers = [value for value in centers if value is not None]
    max_anchor_diff = max(anchor_diffs) if anchor_diffs else 0.0
    center_range = (
        max(valid_centers) - min(valid_centers)
        if valid_centers
        else 0.0
    )
    if len(valid_centers) != len(frames):
        errors.append("gesture lower body disappears in one or more frames")
    if max_anchor_diff > args.max_gesture_lower_body_diff:
        errors.append(
            "gesture lower body changes or travels away from the planted first-frame pose "
            f"(max anchor diff {max_anchor_diff:.3f}; expected <= "
            f"{args.max_gesture_lower_body_diff:.3f})"
        )
    if center_range > args.max_gesture_lower_center_range:
        errors.append(
            "gesture lower body/contact footprint slides horizontally "
            f"(center-x range {center_range:.3f}; expected <= "
            f"{args.max_gesture_lower_center_range:.3f})"
        )
    return errors, warnings, {
        "ok": not errors,
        "lower_body_start": args.gesture_lower_body_start,
        "max_anchor_diff": round(max_anchor_diff, 4),
        "anchor_diffs": [round(value, 4) for value in anchor_diffs],
        "lower_center_x_range": round(center_range, 4),
        "lower_center_x": [
            None if value is None else round(value, 4) for value in centers
        ],
        "max_lower_body_diff": args.max_gesture_lower_body_diff,
        "max_center_x_range": args.max_gesture_lower_center_range,
    }


def inspect_tiny(
    frames: list[Image.Image],
    pair_diffs: list[float],
    args: argparse.Namespace,
) -> tuple[list[str], list[str], dict[str, Any]]:
    errors: list[str] = []
    warnings: list[str] = []
    average_diff = sum(pair_diffs) / len(pair_diffs) if pair_diffs else 0.0
    if len(frames) > 4:
        warnings.append("tiny-motion has more than four frames; verify every frame changes the runtime read")
    if len(frames) >= 2 and average_diff < args.min_tiny_pair_diff:
        errors.append(f"tiny-motion frame changes are too small to read (avg diff {average_diff:.3f})")
    return errors, warnings, {"average_pair_diff": round(average_diff, 4)}


def inspect_state(
    state: str,
    entry: dict[str, Any],
    workflows: list[str],
    workflow_source: str,
    frames: list[Image.Image],
    args: argparse.Namespace,
    shared_idle: bool = False,
    creature_motion: dict[str, Any] | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    metrics = [bbox_metrics(frame) for frame in frames]
    pair_count = len(frames) if entry.get("loop", True) and len(frames) > 2 else max(0, len(frames) - 1)
    pair_diffs = [
        normalized_pair_diff(frames[index], frames[(index + 1) % len(frames)])
        for index in range(pair_count)
    ]
    visual_pair_diffs = [
        normalized_visual_pair_diff(frames[index], frames[(index + 1) % len(frames)])
        for index in range(pair_count)
    ]
    metric_blocks: dict[str, Any] = {
        "frame_count": len(frames),
        "pair_diffs": [round(value, 4) for value in pair_diffs],
        "visual_pair_diffs": [round(value, 4) for value in visual_pair_diffs],
        "bbox_width_range": round(metric_range(metrics, "width"), 4),
        "bbox_height_range": round(metric_range(metrics, "height"), 4),
        "center_x_range": round(metric_range(metrics, "center_x"), 4),
        "center_y_range": round(metric_range(metrics, "center_y"), 4),
        "alpha_area_range_ratio": round(alpha_area_range_ratio(metrics), 4),
    }

    for workflow in workflows:
        contract = WORKFLOW_CONTRACTS[workflow]
        min_frames = int(contract.get("min_frames", 1))
        max_frames = contract.get("max_frames")
        if len(frames) < min_frames:
            errors.append(f"{workflow} needs at least {min_frames} frames to prove required phases; found {len(frames)}")
        if isinstance(max_frames, int) and len(frames) > max_frames:
            warnings.append(f"{workflow} is usually {max_frames} frames or fewer; verify extra frames are not smooth filler")

    if workflows and not frames:
        errors.append("row has animation workflow metadata but no extracted frames")

    if frames:
        if LOCOMOTION_WORKFLOWS & set(workflows):
            step_errors, step_warnings, step_metrics = inspect_locomotion(
                workflows,
                frames,
                metrics,
                args,
                shared_idle=shared_idle,
                creature_motion=creature_motion,
            )
            errors.extend(step_errors)
            warnings.extend(step_warnings)
            metric_blocks["locomotion"] = step_metrics
        if ACTION_WORKFLOWS & set(workflows):
            step_errors, step_warnings, step_metrics = inspect_action(
                workflows,
                metrics,
                pair_diffs,
                args,
                visual_pair_diffs,
            )
            errors.extend(step_errors)
            warnings.extend(step_warnings)
            metric_blocks["action"] = step_metrics
        if "responsive-jump" in workflows:
            step_errors, step_warnings, step_metrics = inspect_jump(metrics, args)
            errors.extend(step_errors)
            warnings.extend(step_warnings)
            metric_blocks["jump"] = step_metrics
        if "hit-reaction-knockdown" in workflows:
            step_errors, step_warnings, step_metrics = inspect_reaction(metrics, pair_diffs, args)
            errors.extend(step_errors)
            warnings.extend(step_warnings)
            metric_blocks["reaction"] = step_metrics
        if "vfx-buildup-peak-decay" in workflows:
            step_errors, step_warnings, step_metrics = inspect_vfx(frames, metrics, pair_diffs, args)
            errors.extend(step_errors)
            warnings.extend(step_warnings)
            metric_blocks["vfx"] = step_metrics
        if LOOP_WORKFLOWS & set(workflows):
            step_errors, step_warnings, step_metrics = inspect_loop(workflows, frames, metrics, pair_diffs, args)
            errors.extend(step_errors)
            warnings.extend(step_warnings)
            metric_blocks["loop"] = step_metrics
        if "gesture-loop" in workflows:
            step_errors, step_warnings, step_metrics = (
                inspect_gesture_planted_lower_body(frames, args)
            )
            errors.extend(step_errors)
            warnings.extend(step_warnings)
            metric_blocks["gesture_planted_lower_body"] = step_metrics
        if "tiny-motion" in workflows:
            step_errors, step_warnings, step_metrics = inspect_tiny(frames, pair_diffs, args)
            errors.extend(step_errors)
            warnings.extend(step_warnings)
            metric_blocks["tiny"] = step_metrics

    phase_contract = dedupe_ordered(
        [phase for workflow in workflows for phase in WORKFLOW_CONTRACTS[workflow].get("phases", [])]
    )
    visual_checklist = dedupe_ordered(
        [check for workflow in workflows for check in WORKFLOW_CONTRACTS[workflow].get("visual_checks", [])]
    )
    return {
        "state": state,
        "frames": len(frames),
        "loop": bool(entry.get("loop", True)),
        "workflows": workflows,
        "workflow_source": workflow_source,
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "phase_contract": phase_contract,
        "visual_review_required": bool(workflows),
        "visual_review_checklist": visual_checklist,
        "metrics": metric_blocks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--states", default="animated", help="'animated', 'all', or comma-separated state names")
    parser.add_argument("--report", default="qa/animation-contract-report.json")
    parser.add_argument("--lower-body-start", type=float, default=0.45)
    parser.add_argument("--min-average-lower-diff", type=float, default=0.10)
    parser.add_argument("--min-pair-lower-diff", type=float, default=0.04)
    parser.add_argument("--min-support-range", type=float, default=0.045)
    parser.add_argument("--min-contact-balance-abs", type=float, default=0.012)
    parser.add_argument("--min-contact-opposition", type=float, default=0.035)
    parser.add_argument("--min-opposite-contact-pose-diff", type=float, default=0.08)
    parser.add_argument("--min-center-range", type=float, default=0.015)
    parser.add_argument("--min-action-motion-range", type=float, default=0.045)
    parser.add_argument("--min-action-pair-diff", type=float, default=0.055)
    parser.add_argument("--min-action-visual-diff", type=float, default=0.003)
    parser.add_argument("--min-jump-vertical-range", type=float, default=0.035)
    parser.add_argument("--min-reaction-motion-range", type=float, default=0.035)
    parser.add_argument("--min-vfx-area-range", type=float, default=0.20)
    parser.add_argument("--min-ambient-pair-diff", type=float, default=0.025)
    parser.add_argument("--min-tiny-pair-diff", type=float, default=0.015)
    parser.add_argument("--max-scale-range", type=float, default=0.25)
    parser.add_argument("--max-loop-closure-diff", type=float, default=0.55)
    parser.add_argument("--max-ambient-area-range", type=float, default=0.65)
    parser.add_argument("--gesture-lower-body-start", type=float, default=0.55)
    parser.add_argument("--max-gesture-lower-body-diff", type=float, default=0.25)
    parser.add_argument("--max-gesture-lower-center-range", type=float, default=0.025)
    parser.add_argument("--warn-only", action="store_true")
    args = parser.parse_args()

    run_dir = args.run_dir.expanduser().resolve()
    request = load_json(run_dir / "sprite-request.json", {})
    creature_motion = request.get("creature_motion")
    shared_idle = bool(
        isinstance(creature_motion, dict) and creature_motion.get("shared_idle")
    )
    frames_manifest = load_json(run_dir / "frames" / "frames-manifest.json", {})
    art_direction = load_json(run_dir / "references" / "art-direction.json", {})
    if not request:
        raise SystemExit(f"missing sprite-request.json in {run_dir}")
    if not frames_manifest.get("ok"):
        raise SystemExit("frames/frames-manifest.json is missing or not ok; fix extraction before animation contract QA")

    states = request.get("states") if isinstance(request.get("states"), dict) else {}
    rows_by_state = {row["state"]: row for row in frames_manifest.get("rows", []) if isinstance(row, dict) and "state" in row}
    results = []
    errors = []
    warnings = []
    try:
        states_to_check = selected_states(request, rows_by_state, art_direction, args.states)
    except ValueError as exc:
        states_to_check = []
        errors.append(str(exc))
    for state in states_to_check:
        if state not in states:
            errors.append(f"unknown state: {state}")
            continue
        if state not in rows_by_state:
            errors.append(f"missing extracted frames for state: {state}")
            continue
        entry = states[state]
        try:
            workflows, workflow_source = workflows_for_state(
                request, art_direction, state, entry
            )
        except ValueError as exc:
            errors.append(f"{state}: {exc}")
            continue
        if not workflows and args.states == "animated":
            continue
        result = inspect_state(
            state,
            entry,
            workflows,
            workflow_source,
            load_frames(run_dir, rows_by_state[state]),
            args,
            shared_idle=shared_idle,
            creature_motion=creature_motion if isinstance(creature_motion, dict) else None,
        )
        results.append(result)
        errors.extend(f"{state}: {error}" for error in result["errors"])
        warnings.extend(f"{state}: {warning}" for warning in result["warnings"])

    if args.states == "animated" and not results and not errors:
        errors.append("no animated workflow states matched; zero expected states were checked")

    ok = not errors or args.warn_only
    report = {
        "ok": ok,
        "engine": "animation-contract-heuristic",
        "run_dir": str(run_dir),
        "states_mode": args.states,
        "checked_states": [result["state"] for result in results],
        "visual_review_required": any(result.get("visual_review_required") for result in results),
        "quality_gate_note": (
            "Automated checks catch obvious phase failures. Visual playback/contact review remains required "
            "for row semantics before final approval."
        ),
        "errors": errors,
        "warnings": warnings,
        "results": results,
    }
    report_path = run_dir / args.report
    report_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(report_path, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({key: value for key, value in report.items() if key != "results"}, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
