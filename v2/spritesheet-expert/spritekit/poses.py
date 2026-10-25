"""Gray mannequin pose guides, one per frame, for side-view motions.

A pose is a set of joints on a 512x512 canvas with the ground at y=460, facing
right. Rear limbs are dark, lead limbs light, so depth reads at a glance.
`frame_poses` samples a motion's poses the same way `motions.phases` samples
its keyframes, and mirrors them when the character faces left.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from .motions import MOTIONS

SIZE, GROUND = 512, 460
REAR, LEAD, TORSO = (96, 96, 104), (150, 150, 158), (122, 122, 130)

_READY = dict(head=(262, 150), neck=(255, 185), pelvis=(240, 300),
              rear_arm=[(248, 200), (270, 255), (292, 205)], lead_arm=[(262, 200), (302, 240), (322, 195)],
              rear_leg=[(200, 375), (175, 455), (205, 458)], lead_leg=[(300, 375), (330, 455), (360, 458)])


def _shift(pose: dict, dy: int = 0, arms_dy: int = 0) -> dict:
    move = lambda pts, d: [(x, y + d) for x, y in pts]
    return {**pose, "head": (pose["head"][0], pose["head"][1] + dy), "neck": (pose["neck"][0], pose["neck"][1] + dy),
            "rear_arm": move(pose["rear_arm"], arms_dy), "lead_arm": move(pose["lead_arm"], arms_dy)}


POSES: dict[str, list[dict]] = {
    "idle": [_READY, _shift(_READY, -5, -5), _shift(_READY, -6, -7), _shift(_READY, 2, 2)],
    "attack": [  # straight thrust with the rear hand: punch, palm, stab
        _READY,
        dict(head=(238, 155), neck=(236, 190), pelvis=(230, 302),
             rear_arm=[(232, 205), (248, 258), (268, 215)], lead_arm=[(244, 205), (286, 245), (308, 205)],
             rear_leg=[(192, 372), (172, 455), (202, 458)], lead_leg=[(295, 378), (330, 455), (360, 458)]),
        dict(head=(228, 158), neck=(232, 192), pelvis=(232, 302),
             rear_arm=[(224, 208), (192, 245), (212, 285)], lead_arm=[(246, 206), (284, 240), (306, 205)],
             rear_leg=[(196, 380), (172, 455), (202, 458)], lead_leg=[(296, 378), (330, 455), (360, 458)]),
        dict(head=(300, 156), neck=(287, 190), pelvis=(256, 302),
             rear_arm=[(282, 204), (350, 200), (418, 198)], lead_arm=[(292, 206), (270, 248), (288, 214)],
             rear_leg=[(214, 382), (184, 452), (206, 456)], lead_leg=[(322, 372), (348, 455), (378, 458)]),
        dict(head=(314, 162), neck=(298, 194), pelvis=(262, 304),
             rear_arm=[(292, 208), (362, 212), (428, 222)], lead_arm=[(300, 210), (276, 252), (284, 222)],
             rear_leg=[(222, 382), (196, 440), (218, 456)], lead_leg=[(326, 372), (350, 455), (380, 458)]),
        _shift(_READY, 1, 1),
    ],
    "attack-overhead": [  # weapon raised over the head and brought down in front
        dict(_READY, rear_arm=[(248, 200), (232, 222), (240, 172)], lead_arm=[(262, 200), (300, 238), (330, 215)]),
        dict(head=(240, 152), neck=(238, 188), pelvis=(232, 302),
             rear_arm=[(240, 202), (222, 182), (232, 132)], lead_arm=[(250, 204), (290, 236), (320, 214)],
             rear_leg=[(192, 372), (172, 455), (202, 458)], lead_leg=[(295, 378), (330, 455), (360, 458)]),
        dict(head=(236, 152), neck=(236, 190), pelvis=(232, 302),
             rear_arm=[(240, 205), (220, 150), (190, 108)], lead_arm=[(250, 206), (290, 238), (322, 216)],
             rear_leg=[(194, 376), (172, 455), (202, 458)], lead_leg=[(296, 378), (330, 455), (360, 458)]),
        dict(head=(300, 166), neck=(288, 200), pelvis=(256, 304),
             rear_arm=[(282, 212), (345, 215), (400, 252)], lead_arm=[(292, 214), (292, 248), (312, 228)],
             rear_leg=[(214, 382), (184, 452), (206, 456)], lead_leg=[(324, 372), (350, 455), (380, 458)]),
        dict(head=(306, 176), neck=(292, 208), pelvis=(258, 306),
             rear_arm=[(286, 218), (330, 262), (358, 322)], lead_arm=[(296, 220), (296, 254), (316, 234)],
             rear_leg=[(218, 382), (190, 446), (212, 456)], lead_leg=[(326, 372), (350, 455), (380, 458)]),
        dict(_READY, rear_arm=[(248, 200), (232, 222), (240, 172)], lead_arm=[(262, 200), (300, 238), (330, 215)]),
    ],
}


def frame_poses(motion: str, frames: int) -> list[dict] | None:
    keys = POSES.get(motion)
    if keys is None:
        return None
    if MOTIONS.get(motion, {}).get("loop"):
        return [keys[round(i * len(keys) / frames) % len(keys)] for i in range(frames)]
    return [keys[round(i * (len(keys) - 1) / max(frames - 1, 1))] for i in range(frames)]


def faces_left(view: str) -> bool:
    return "left" in view.lower()


# OpenPose COCO-18 order: nose, neck, R shoulder/elbow/wrist, L shoulder/elbow/wrist,
# R hip/knee/ankle, L hip/knee/ankle, R eye, L eye, R ear, L ear. In side view the
# rear limbs are the character's right side and the lead limbs the left side.
OPENPOSE_LIMBS = [(1, 2), (1, 5), (2, 3), (3, 4), (5, 6), (6, 7), (1, 8), (8, 9), (9, 10),
                  (1, 11), (11, 12), (12, 13), (1, 0), (0, 14), (14, 16), (0, 15), (15, 17)]
OPENPOSE_COLORS = [(255, 0, 0), (255, 85, 0), (255, 170, 0), (255, 255, 0), (170, 255, 0), (85, 255, 0),
                   (0, 255, 0), (0, 255, 85), (0, 255, 170), (0, 255, 255), (0, 170, 255), (0, 85, 255),
                   (0, 0, 255), (85, 0, 255), (170, 0, 255), (255, 0, 255), (255, 0, 170), (255, 0, 85)]


def openpose_keypoints(pose: dict, mirror: bool = False) -> list[tuple[float, float]]:
    hx, hy = pose["head"]
    px, py = pose["pelvis"]
    pts = [
        (hx + 22, hy + 4), pose["neck"], *pose["rear_arm"], *pose["lead_arm"],
        (px - 6, py), *pose["rear_leg"][:2], (px + 6, py), *pose["lead_leg"][:2],
        (hx + 14, hy - 8), (hx + 16, hy - 10), (hx - 6, hy - 4), (hx - 4, hy - 6),
    ]
    return [((SIZE - x) if mirror else x, y) for x, y in pts]


def openpose_json(pose: dict, mirror: bool = False) -> dict:
    flat = [v for x, y in openpose_keypoints(pose, mirror) for v in (round(x, 1), round(y, 1), 1.0)]
    return {"version": 1.3, "canvas_width": SIZE, "canvas_height": SIZE, "people": [{"pose_keypoints_2d": flat}]}


def draw_openpose(pose: dict, mirror: bool = False) -> Image.Image:
    """Standard OpenPose skeleton render: colored limbs and joints on black."""
    kp = openpose_keypoints(pose, mirror)
    img = Image.new("RGB", (SIZE, SIZE), (0, 0, 0))
    d = ImageDraw.Draw(img)
    for i, (a, b) in enumerate(OPENPOSE_LIMBS):
        c = tuple(int(v * 0.6) for v in OPENPOSE_COLORS[i])
        d.line([kp[a], kp[b]], fill=c, width=8)
    for i, (x, y) in enumerate(kp):
        d.ellipse([x - 5, y - 5, x + 5, y + 5], fill=OPENPOSE_COLORS[i])
    return img


def draw(pose: dict, mirror: bool = False) -> Image.Image:
    fx = (lambda x: SIZE - x) if mirror else (lambda x: x)
    pt = lambda p: (fx(p[0]), p[1])
    img = Image.new("RGB", (SIZE, SIZE), (238, 238, 234))
    d = ImageDraw.Draw(img)
    d.line([20, GROUND, SIZE - 20, GROUND], fill=(210, 90, 70), width=3)

    def limb(points, color, width):
        pts = [pt(p) for p in points]
        d.line(pts, fill=color, width=width, joint="curve")
        for x, y in pts:
            d.ellipse([x - width / 2, y - width / 2, x + width / 2, y + width / 2], fill=color)

    limb(pose["rear_arm"], REAR, 26)
    limb([pose["pelvis"], *pose["rear_leg"]], REAR, 30)
    limb([pose["neck"], pose["pelvis"]], TORSO, 64)
    limb([pose["pelvis"], *pose["lead_leg"]], LEAD, 30)
    hx, hy = pt(pose["head"])
    d.ellipse([hx - 30, hy - 32, hx + 30, hy + 32], fill=TORSO)
    nose = -1 if mirror else 1
    d.polygon([(hx + 24 * nose, hy - 6), (hx + 40 * nose, hy + 4), (hx + 24 * nose, hy + 12)], fill=TORSO)
    limb(pose["lead_arm"], LEAD, 26)
    return img
