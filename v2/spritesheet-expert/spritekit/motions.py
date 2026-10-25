"""Frame-by-frame phase descriptions for common motions.

Each motion is a keyframe list for one cycle. ``phases(motion, n)`` samples it
for any frame count, so a 6-frame walk and an 8-frame walk share one source.
``ground`` says how build places frames vertically: ``ground`` puts every
frame on the baseline; ``keep`` keeps the source's vertical motion (jumps, VFX).
``align_x`` is ``feet`` for actions in place (planted feet stay put), ``mass``
for locomotion cycles, and ``keep`` for motion that travels (jumps, VFX).
"""

from __future__ import annotations

MOTIONS: dict[str, dict] = {
    "idle": {
        "label": "idle breathing loop",
        "loop": True, "ground": "ground", "align_x": "feet",
        "keys": [
            ("rest", "neutral stance, weight centered, relaxed"),
            ("inhale", "chest and shoulders rise slightly, head lifts a few pixels"),
            ("hold", "top of the breath, small secondary motion in hair, cloth or tail"),
            ("exhale", "shoulders settle back down, slight knee give"),
        ],
    },
    "walk": {
        "label": "walk cycle",
        "loop": True, "ground": "ground", "align_x": "mass",
        "keys": [
            ("contact R", "right foot forward touching the ground heel first, left foot back, arms opposite to legs, body at mid height"),
            ("down", "weight lands on the right leg, knee bends, body at its lowest point"),
            ("passing", "left leg swings past the right supporting leg, body rising"),
            ("up", "pushing off the right foot, body at its highest point, left leg reaching forward"),
            ("contact L", "left foot forward touching the ground heel first, right foot back, arms swapped"),
            ("down", "weight lands on the left leg, knee bends, body at its lowest point"),
            ("passing", "right leg swings past the left supporting leg, body rising"),
            ("up", "pushing off the left foot, body at its highest point, right leg reaching forward"),
        ],
    },
    "walk-quadruped": {
        "label": "four-legged walk cycle",
        "loop": True, "ground": "ground", "align_x": "mass",
        "keys": [
            ("pair A plant", "front-left and back-right legs planted, front-right and back-left legs lifted and swinging forward"),
            ("pair A push", "planted pair pushes back, body slightly lowered, swinging pair halfway forward"),
            ("switch", "all four legs near the ground, body at its highest point"),
            ("pair B plant", "front-right and back-left legs planted, front-left and back-right legs lifted and swinging forward"),
            ("pair B push", "planted pair pushes back, body slightly lowered, swinging pair halfway forward"),
            ("switch", "all four legs near the ground, body at its highest point"),
        ],
    },
    "run": {
        "label": "run cycle",
        "loop": True, "ground": "ground", "align_x": "mass",
        "keys": [
            ("contact R", "right foot strikes the ground under the body, torso leaning forward, arms pumping"),
            ("down", "right knee compresses, body at its lowest point"),
            ("push", "right leg drives back, left knee drives forward and high"),
            ("flight", "both feet off the ground, body at its highest point"),
            ("contact L", "left foot strikes the ground under the body, arms swapped"),
            ("down", "left knee compresses, body at its lowest point"),
            ("push", "left leg drives back, right knee drives forward and high"),
            ("flight", "both feet off the ground, body at its highest point"),
        ],
    },
    "attack": {
        "label": "attack",
        "loop": False, "ground": "ground", "align_x": "feet",
        "keys": [
            ("ready", "combat stance, weapon or fist ready"),
            ("anticipation", "body winds back away from the target, weight on the back foot"),
            ("wind-up", "maximum coil, limb or weapon pulled fully back"),
            ("strike", "fast extension toward the target, full reach, weight on the front foot"),
            ("follow-through", "limb or weapon continues past the target, body rotated"),
            ("recover", "returning to the combat stance"),
        ],
    },
    "attack-overhead": {
        "label": "overhead attack",
        "loop": False, "ground": "ground", "align_x": "feet",
        "keys": [
            ("ready", "combat stance, weapon raised at shoulder height"),
            ("anticipation", "weight shifts back, weapon lifts higher"),
            ("wind-up", "weapon raised fully over and behind the head, body coiled"),
            ("strike", "weapon brought down hard in front, full reach, weight on the front foot"),
            ("follow-through", "weapon continues down toward the ground, body bent forward"),
            ("recover", "returning to the combat stance"),
        ],
    },
    "jump": {
        "label": "jump",
        "loop": False, "ground": "keep", "align_x": "keep",
        "keys": [
            ("crouch", "knees bent deep, arms back, feet on the ground"),
            ("takeoff", "legs extending, feet leaving the ground, arms swinging up"),
            ("rise", "airborne and rising, legs tucked"),
            ("apex", "highest point of the jump, body compact"),
            ("fall", "descending, legs reaching down for the landing"),
            ("land", "feet back on the ground, knees absorbing the impact"),
        ],
    },
    "hurt": {
        "label": "hit reaction",
        "loop": False, "ground": "ground", "align_x": "feet",
        "keys": [
            ("impact", "body jolts back from the hit, face strained"),
            ("recoil", "head and torso thrown back, one foot sliding"),
            ("stagger", "off balance, arms loose"),
            ("recover", "regaining the neutral stance"),
        ],
    },
    "cast": {
        "label": "spell cast",
        "loop": False, "ground": "ground", "align_x": "feet",
        "keys": [
            ("ready", "neutral stance, hands low"),
            ("gather", "hands draw together, energy begins to gather"),
            ("charge", "energy at its brightest between the hands, body tense"),
            ("release", "arms thrust forward, energy leaves the hands"),
            ("recover", "arms lowering, returning to the neutral stance"),
        ],
    },
    "vfx": {
        "label": "effect",
        "loop": False, "ground": "keep", "align_x": "keep",
        "keys": [
            ("spark", "a tiny bright point at the emitter"),
            ("build", "the effect grows quickly from the emitter"),
            ("peak", "largest and brightest moment, full shape"),
            ("break", "the shape breaks into pieces moving outward"),
            ("fade", "pieces shrink and dim"),
            ("vanish", "only a few faint specks remain"),
        ],
    },
}


# How long each phase holds, relative to one frame at the state's fps. Anticipation
# and impact read better slower; the fast part of an action stays at 1.
HOLDS = {
    "attack": {"ready": 1.5, "anticipation": 1.5, "strike": 1.5, "recover": 2},
    "attack-overhead": {"ready": 1.5, "anticipation": 1.5, "wind-up": 1.5, "strike": 1.5, "recover": 2},
    "jump": {"crouch": 1.5, "apex": 1.5, "land": 1.5},
    "hurt": {"impact": 1.5, "recover": 2},
    "cast": {"charge": 2, "release": 1.5},
    "vfx": {"peak": 1.5},
}


def hold(motion: str, label: str) -> float:
    return HOLDS.get(motion, {}).get(label, 1.0)


def phases(motion: str, frames: int, action: str = "") -> list[tuple[str, str]]:
    """Return ``frames`` (short label, description) pairs for one cycle."""
    if frames < 1:
        raise ValueError("frames must be at least 1")
    spec = MOTIONS.get(motion)
    if spec is None:
        what = action or motion
        return [(f"{i + 1}/{frames}", f"step {i + 1} of {frames} of: {what}") for i in range(frames)]
    keys = spec["keys"]
    if spec["loop"]:
        picks = [round(i * len(keys) / frames) % len(keys) for i in range(frames)]
    else:
        picks = [round(i * (len(keys) - 1) / max(frames - 1, 1)) for i in range(frames)]
    return [keys[p] for p in picks]


def motion_spec(motion: str) -> dict:
    return MOTIONS.get(motion, {"label": motion, "loop": False, "ground": "ground", "align_x": "keep"})
