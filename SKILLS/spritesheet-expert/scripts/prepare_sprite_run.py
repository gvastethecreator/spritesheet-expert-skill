#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Prepare a sprite-gen component-row run.

This script owns the numeric sprite recipe. It writes one request JSON, one
layout guide per state, and one prompt per state. Image generation should read
these files instead of hand-copying frame counts into ad hoc prompts.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from runio import acquire_run_dir_lock
from spritecore.contracts import ContractError, normalize_contract
from spritecore.models import is_state_slug
from spritecore.paths import (
    RUN_MARKER_FILENAME,
    PathSafetyError,
    create_run_marker,
    remove_known_outputs,
)


DEFAULT_STATES: dict[str, dict[str, Any]] = {
    "idle": {"frames": 4, "fps": 4, "loop": True, "action": "subtle breathing and blinking"},
    "attack": {
        "frames": 4,
        "fps": 8,
        "loop": False,
        "action": "simple windup, strike, recovery attack pose sequence with no detached effects",
    },
    "jump": {"frames": 4, "fps": 8, "loop": False, "action": "jump arc through body position only"},
    "wave": {
        "frames": 4,
        "fps": 6,
        "loop": False,
        "action": "friendly hand wave gesture; arm changes clearly while feet stay planted",
    },
}

STYLE_PRESETS: dict[str, dict[str, str]] = {
    "pixel-art": {
        "contract": (
            "pixel-art-adjacent low-resolution game sprite, compact chibi/mascot-friendly "
            "proportions when the base allows it, chunky whole-body silhouette, thick dark "
            "1-2 px outline, visible stepped/pixel edges, limited palette, flat cel shading "
            "with at most one small highlight and one shadow step, simple readable face, "
            "clear limbs, and no detail that disappears at small runtime size. Avoid polished "
            "illustration, painterly rendering, anime key art, 3D render, vector app-icon "
            "polish, glossy lighting, soft gradients, anti-aliased high-detail edges, and "
            "complex tiny accessories."
        ),
        "rendering": "Keep the rendering sprite-like: chunky silhouette, dark pixel-style outline, limited palette, flat shading, minimal tiny detail.",
        "avoid": "Do not expand it into a polished illustration, painterly character image, anime key art, 3D render, vector mascot, glossy app icon, realistic portrait, or marketing artwork.",
    },
    "illustration": {
        "contract": (
            "clean 2D game illustration sprite, readable full-body silhouette, consistent "
            "linework, controlled cel shading, clear expression and limbs, moderate detail "
            "that remains readable at runtime size. Anti-aliased edges are allowed."
        ),
        "rendering": "Keep the rendering as a clean 2D illustrated game asset: readable silhouette, consistent linework, controlled cel shading, no tiny noisy detail.",
        "avoid": "Do not turn it into photorealism, 3D render, marketing key art, or scene illustration; keep it as isolated animation frames.",
    },
    "painterly": {
        "contract": (
            "stylized painterly game sprite, readable silhouette, soft brush texture, coherent "
            "lighting, controlled value grouping, and enough simplification to remain legible "
            "at runtime size."
        ),
        "rendering": "Keep the rendering as a stylized painterly game asset: brush texture is allowed, but silhouette and frame readability must stay clear.",
        "avoid": "Do not add scenery, cinematic background, detached particles, or over-rendered detail that breaks atlas readability.",
    },
    "realistic": {
        "contract": (
            "semi-realistic game sprite/animation frame style, natural materials and anatomy "
            "when the subject allows it, coherent lighting, anti-aliased edges, and readable "
            "full-body silhouette for runtime use."
        ),
        "rendering": "Keep the rendering as an isolated semi-realistic game sprite: anti-aliased detail is allowed, but every frame must stay readable inside its cell.",
        "avoid": "Do not add scene backgrounds, floor shadows, cinematic lighting rigs, text, UI, or cropped portrait composition.",
    },
    "anime": {
        "contract": (
            "anime-inspired 2D game sprite, clean contour lines, simplified cel shading, "
            "expressive face and poses, controlled detail, and consistent character identity."
        ),
        "rendering": "Keep the rendering as an anime-inspired 2D game sprite: clean outlines, cel shading, strong pose readability.",
        "avoid": "Do not turn it into poster/key art, bust portrait, manga panel, scene background, or text-bearing image.",
    },
    "vector": {
        "contract": (
            "flat vector-like game sprite, crisp simplified shapes, clear silhouette, minimal "
            "gradients, consistent colors, and strong readability at small sizes."
        ),
        "rendering": "Keep the rendering as a flat vector-like game asset: crisp shapes, simple values, strong silhouette.",
        "avoid": "Do not include SVG/grid marks, UI labels, scene backgrounds, or decorative layout elements.",
    },
    "custom": {
        "contract": "custom user-provided game sprite style.",
        "rendering": "Keep the rendering compatible with game atlas use: isolated full-body frame, readable silhouette, consistent identity.",
        "avoid": "Do not add text, scene backgrounds, guide marks, UI panels, or cropped portrait composition.",
    },
}
STYLE_DEFAULT_PRESET = "pixel-art"
STYLE_DEFAULT = STYLE_PRESETS[STYLE_DEFAULT_PRESET]["contract"]
BACKGROUND_REMOVAL_METHODS = {"none", "chroma", "matte", "rembg", "ben2", "auto"}
DEFAULT_REMBG_MODEL = "birefnet-general-lite"
DEFAULT_BEN2_MODEL = "PramaLLC/BEN2"
ART_DIRECTION_MODES = {"none", "pixel-art"}
ART_DIRECTION_MODE_ALIASES: dict[str, str] = {}
ART_PROFILE_AUTO = "auto"
PREPARE_KNOWN_OUTPUTS = (
    "prompts",
    "references/layout-guides",
    "references/art-direction.json",
    "frames",
    "qa",
    "sprite-request.json",
    "sprite-sheet-alpha.png",
    "sprite-sheet-alpha.webp",
    "manifest.json",
    "preview.gif",
    "preview.png",
)

TRANSPARENCY_ARTIFACT_RULES = [
    "Prefer pose, expression, and silhouette changes over decorative effects.",
    "Effects are allowed only when state-relevant, opaque, controlled, fully inside the same frame slot, and physically touching or overlapping the character silhouette.",
    "Do not draw detached effects: floating stars, loose sparkles, floating punctuation, floating icons, separated smoke clouds, loose dust, disconnected outline bits, or stray pixels.",
    "Do not draw wave marks, motion arcs, speed lines, action streaks, afterimages, blur, smears, halos, glows, auras, floor patches, cast shadows, contact shadows, drop shadows, oval floor shadows, landing marks, or impact bursts.",
    "Do not include text, labels, frame numbers, visible grids, guide marks, speech bubbles, thought bubbles, UI panels, code snippets, scenery, checkerboard transparency, white backgrounds, or black backgrounds.",
    "Reject any pose that is cropped, overlaps another pose, crosses into a neighboring frame slot, or creates a separate disconnected component that is not attached to the character.",
]

ASSET_ARTIFACT_RULES = [
    "Do not include text, labels, frame numbers, visible grids, guide marks, UI mockups, contact-sheet captions, checkerboard transparency, white backgrounds, or black backgrounds.",
    "Do not merge slots into one scene. Each slot must be one complete runtime asset, tile, texture sample, icon, prop, decal, or effect frame.",
    "Keep every asset inside its slot. No artwork may cross into a neighboring slot or rely on another slot to read correctly.",
    "For textures and tiles, keep tile edges intentional and runtime-usable; for props/icons/VFX, keep the outside area pure chroma-key background.",
    "Effects are allowed only when the row action asks for them, and must stay fully inside the same slot.",
]

SPRITE_PRODUCTION_RULES = [
    "Plan the row as animation keys, not unrelated poses: use anticipation/setup, action/contact/extreme, and recovery/settle when the state calls for it.",
    "Every frame needs a clear silhouette and line of action readable at runtime size; face, hands, feet, weapons, and contact points should not hide the action.",
    "Preserve character volume and anatomy: head, torso, hands, feet, limb thickness, outline weight, costume details, and props keep the same runtime scale unless a local squash/stretch is intentionally volume-preserving.",
    "Show weight and body mechanics through center of mass, planted support side, hip/shoulder counter-motion, arcs, overlap, and follow-through; avoid stiff puppet posing unless the character design explicitly requires it.",
    "Keep joints plausible for the design. Knees, elbows, wrists, ankles, shoulders, hips, and neck should bend where the character's body explains the pose.",
]

ASSET_PRODUCTION_RULES = {
    "tileset": [
        "Each slot must fit the tile grid exactly and preserve consistent projection, palette, scale, and collision readability.",
        "Edges must be intentional and compatible with neighboring tiles; do not paint a mini scene that only works as a contact sheet.",
    ],
    "texture": [
        "Each slot is a flat orthographic material sample with consistent texel density and tileable/seamless intent.",
        "Do not include perspective objects, labels, lighting vignettes, or scene context; make the material itself usable at runtime.",
    ],
    "asset": [
        "Each slot is a separate centered runtime asset with readable silhouette, coherent set language, and stable scale hierarchy.",
        "Respect practical pivots: props/icons centered, pickups balanced, decals isolated, and VFX anchored at their emitter/contact point.",
    ],
    "prop": [
        "Each prop must be centered, isolated, readable at runtime size, and consistent with the row's material and scale language.",
        "Preserve practical pivots and avoid catalog-page staging or shared scenic shadows.",
    ],
    "props": [
        "Each prop must be centered, isolated, readable at runtime size, and consistent with the row's material and scale language.",
        "Preserve practical pivots and avoid catalog-page staging or shared scenic shadows.",
    ],
    "icon": [
        "Each icon must read instantly at runtime size with strong silhouette, consistent stroke/fill language, and centered optical balance.",
        "Avoid tiny interior detail, labels, UI mockup frames, and scene-like backgrounds.",
    ],
    "ui": [
        "Each UI icon must read instantly at runtime size with strong silhouette, consistent stroke/fill language, and centered optical balance.",
        "Avoid tiny interior detail, labels, UI mockup frames, and scene-like backgrounds.",
    ],
    "vfx": [
        "Treat frames as a temporal VFX sequence: buildup, peak, decay, and fade must be readable without labels or motion arrows.",
        "Keep opacity alpha-friendly, avoid chroma-colored cores, and preserve a stable emitter/contact anchor across frames.",
    ],
}

LOCOMOTION_REQUIREMENTS = [
    "This is a full-body locomotion row, not a portrait, bust, emote, celebration, or UI avatar row.",
    "Every frame must show the entire body and both feet/leg contacts inside the slot.",
    "Do not crop the head, torso, legs, or feet. Do not zoom in to the face or hands.",
    "Do not raise both arms/flippers into a cheer pose unless the state name explicitly asks for celebration.",
    "Use arms/flippers only as counter-swing support for the gait.",
    "Foot placement must visibly change: contact frames need one foot forward and one foot back, passing frames need one foot under the body, and the support side must alternate.",
    "If the character has tiny legs or blob feet, exaggerate foot pads and lower-body silhouette enough that the gait reads without labels or motion lines.",
]

STATE_REQUIREMENTS = {
    "running-right": [
        "Show rightward locomotion through body, arm, leg, hair, and prop movement only.",
        "Use distinct gait poses that create a readable cycle instead of repeated standing or static bobbing.",
        "Do not draw speed lines, dust clouds, floor shadows, motion trails, or detached motion effects.",
    ],
    "running-left": [
        "Show leftward locomotion through body, arm, leg, hair, and prop movement only.",
        "Use distinct gait poses that create a readable cycle instead of repeated standing or static bobbing.",
        "If an additional rightward gait row is attached, use it only as a motion-rhythm reference for limb phase and body bounce; do not copy its facing direction or redraw the character from that row.",
        "Do not draw speed lines, dust clouds, floor shadows, motion trails, or detached motion effects.",
    ],
    "running-front-right": [
        "Show 45-degree diagonal locomotion toward camera-right and slightly toward the viewer.",
        "Keep the body three-quarter-front, not pure side view and not straight front view.",
        "Use alternating foot-contact phases so the left and right legs clearly trade forward reach.",
        "Do not draw speed lines, dust clouds, floor shadows, motion trails, or detached motion effects.",
    ],
    "running-front-left": [
        "Show 45-degree diagonal locomotion toward camera-left and slightly toward the viewer.",
        "Keep the body three-quarter-front, not pure side view and not straight front view.",
        "Use alternating foot-contact phases so the left and right legs clearly trade forward reach.",
        "Do not draw speed lines, dust clouds, floor shadows, motion trails, or detached motion effects.",
    ],
    "running-back-right": [
        "Show 45-degree diagonal locomotion away from the viewer toward camera-right.",
        "Keep the body three-quarter-back, with the face partly hidden but the character still identifiable.",
        "Use alternating foot-contact phases so the left and right legs clearly trade backward/forward reach.",
        "Do not draw speed lines, dust clouds, floor shadows, motion trails, or detached motion effects.",
    ],
    "running-back-left": [
        "Show 45-degree diagonal locomotion away from the viewer toward camera-left.",
        "Keep the body three-quarter-back, with the face partly hidden but the character still identifiable.",
        "Use alternating foot-contact phases so the left and right legs clearly trade backward/forward reach.",
        "Do not draw speed lines, dust clouds, floor shadows, motion trails, or detached motion effects.",
    ],
    "run": [
        "Show locomotion through body, arm, leg, hair, and prop movement only.",
        "Use distinct gait poses that create a readable cycle instead of repeated standing or static bobbing.",
        "Do not draw speed lines, dust clouds, floor shadows, motion trails, or detached motion effects.",
    ],
    "walk": [
        "Show locomotion through body, arm, leg, hair, and prop movement only.",
        "Use distinct gait poses that create a readable cycle instead of repeated standing or static bobbing.",
        "Do not draw speed lines, dust clouds, floor shadows, motion trails, or detached motion effects.",
    ],
    "frontwalk": [
        "Show front-view walking through alternating leg, arm, shoulder, and body-height changes.",
        "This is difficult: make the foot-contact and passing poses visibly different without changing identity.",
        "Do not draw speed lines, dust clouds, floor shadows, motion trails, or detached motion effects.",
    ],
    "45_frontwalk": [
        "Show three-quarter-front walking through alternating leg, arm, shoulder, and body-height changes.",
        "This is difficult: make the foot-contact and passing poses visibly different without changing identity.",
        "Do not draw speed lines, dust clouds, floor shadows, motion trails, or detached motion effects.",
    ],
    "wave": [
        "Show the gesture through arm pose only: arm down, arm raised, hand tilted, arm returning.",
        "Keep the feet planted unless the action explicitly requests stepping.",
        "Do not draw wave marks, motion arcs, lines, sparkles, symbols, or floating effects around the hand.",
    ],
    "jump": [
        "Show the jump through pose and vertical body position only: anticipation, lift, airborne peak, descent, settle.",
        "Do not draw ground shadows, contact shadows, oval shadows, landing marks, dust, smears, or motion marks under the character.",
    ],
    "jumping": [
        "Show the jump through pose and vertical body position only: anticipation, lift, airborne peak, descent, settle.",
        "Do not draw ground shadows, contact shadows, oval shadows, landing marks, dust, smears, or motion marks under the character.",
    ],
    "fall": [
        "Show falling through airborne body placement and pose only; keep the same character scale as idle/jump.",
        "Do not draw speed lines, ground shadows, dust, impact marks, or detached motion effects.",
    ],
    "land": [
        "Show landing through grounded compression and recovery only; feet return to the shared baseline.",
        "Do not enlarge the character to fill the slot and do not draw impact marks, dust, or ground shadows.",
    ],
    "crouch": [
        "Show crouching through grounded body compression only; feet stay planted on the shared baseline.",
        "Do not zoom in, enlarge the head/torso, or fill the standing-height slot with a scaled-up crouch.",
    ],
}

ACTION_PHASE_REQUIREMENTS = {
    "idle": [
        "Keep the idle alive with subtle breathing, weight shift, guard/hand readiness, blink or small overlap; avoid drifting scale or random redesign.",
    ],
    "block": [
        "Make the defensive pose readable: guard covers the body, feet are planted, center of mass is braced, and silhouette still exposes face/hands.",
    ],
    "attack": [
        "Use clear gameplay phases: startup/windup, active contact or maximum extension, then recovery.",
        "The active frame must be the strongest silhouette and show threat direction through the line of action.",
    ],
    "punch": [
        "Use clear fighting phases: guard/startup, fist extension/contact, and recovery back toward stance.",
        "The punching arm, shoulder, torso twist, and feet must support the same direction of force.",
    ],
    "kick": [
        "Use clear fighting phases: chamber/startup, leg extension/contact, and recovery with balance regained.",
        "The support foot, hips, torso lean, and kicking leg must explain the force and not look like a resized idle.",
    ],
    "special": [
        "Use clear fighting phases: startup tell, active/peak action, and recovery. Effects are secondary to body pose readability.",
        "Keep any effect attached to the character or emitter and inside the same slot.",
    ],
    "hit": [
        "Show impact direction, balance loss, drag/overshoot, and recovery or settle; do not use a generic surprised idle.",
    ],
    "hurt": [
        "Show impact direction, balance loss, drag/overshoot, and recovery or settle; do not use a generic surprised idle.",
    ],
    "hitstun": [
        "Show force direction and readable stun posture across frames: impact, held recoil, overshoot/drag, then partial recovery.",
    ],
    "knockdown": [
        "Stage the fall clearly: loss of balance, airborne or collapsing body, ground contact, and final down pose without cropping.",
    ],
    "death": [
        "Stage the action clearly: final hit or collapse setup, loss of support, fall/settle, and readable final silhouette.",
    ],
    "dodge": [
        "Show a purposeful evasive path with weight transfer, torso lean, planted/takeoff contact, and recovery.",
    ],
    "cast": [
        "Show preparation, focused active gesture, and recovery; hands/prop/emitter must clearly lead the action.",
    ],
    "taunt": [
        "Show a confident readable gesture through body attitude, face, and hands without changing identity or turning into a portrait.",
    ],
    "win": [
        "Show victory as a staged action with clear gesture, balance, and recovery/hold; keep the character full-body and at idle scale.",
    ],
}

ART_PROFILES: dict[str, dict[str, Any]] = {
    "pixel-core": {
        "label": "Pixel core fundamentals",
        "sources": ["01-color-palettes", "02-texture", "05-back-to-basics", "06-light-and-shadow", "07-developing-style"],
        "rules": [
            "Use a small coherent sub-palette, hue-shift ramps, and value contrast as the readability backbone; avoid saturated high-brightness color spam.",
            "Think in intentional clusters, not fuzzy low-res painting: simplify detail into repeated cluster shapes and remove orphan pixels.",
            "Use one consistent light direction, usually upper corner or top light, with highlight/midtone/shadow per readable volume; no pillow shading.",
            "Keep the sprite/gameplay scale modest. More detail, color, and frame count must earn their cost at runtime size.",
        ],
    },
    "pixel-character": {
        "label": "Pixel character construction",
        "sources": ["17-human-anatomy", "22-top-down-character-sprites", "25-motion-cycles", "57-knights-monsters-castles", "58-top-down-character-animation-part-3"],
        "rules": [
            "Build motion from a simple dummy or color-blocked anatomy first, then add costume/detail only after proportions and pose rhythm work.",
            "Design for animation, not a single static pose: simplify noisy gear, preserve feature scale, and let expression come from posture and motion.",
            "Keep silhouette readable before interior detail; face, hands, feet, weapon, and contact points must not merge into the body.",
            "For asymmetric gear, hair, weapons, scars, shields, or handed props, do not mirror blindly; preserve side logic or generate unique directions.",
        ],
    },
    "pixel-motion": {
        "label": "Pixel motion and frame economy",
        "sources": ["08-intro-to-animation", "25-motion-cycles", "50-human-walk-cycle", "55-top-down-character-animation", "60-side-view-run-n-gun"],
        "rules": [
            "Keyframes carry the animation. Protect contact, pass, action, and recovery poses before adding or deleting in-betweens.",
            "Energy beats smoothness: too many soft in-betweens make the action sluggish; adjust playback speed when reducing frames.",
            "Animate section by section, usually legs, arms, head, then body/secondary motion, so the core cycle is solid before polish.",
            "Loops must reconnect without a visible pop; check full-speed playback, not only static contact sheets.",
        ],
    },
    "pixel-sideview": {
        "label": "Pixel side-view/platformer/run-n-gun",
        "sources": ["28-side-view-tiles", "37-castlevania-study", "38-metroid-study", "50-human-walk-cycle", "60-side-view-run-n-gun"],
        "rules": [
            "For side-view characters, anchor the center of gravity and feet so jumps, runs, crouches, and knockback read in tile/gameplay units.",
            "Walk/run cycles need contact, down, pass, and swing logic with opposite arm-leg momentum; run can be a leaned, faster walk, not a total redesign.",
            "Responsive jump rows should avoid long anticipation unless the state explicitly sells a heavy committed move.",
            "For side-view tile or environment rows, require clean collision silhouettes, cabinet/depth tilt where useful, variants for repeated tiles, and support structures under static platforms.",
        ],
    },
    "pixel-topdown": {
        "label": "Pixel top-down characters, props, and tiles",
        "sources": ["20-top-down-tiles", "21-top-down-objects", "22-top-down-character-sprites", "55-top-down-character-animation", "56-top-down-character-attack-animation"],
        "rules": [
            "Keep one 3/4 top-down projection system across characters, props, tiles, and shadows; never mix side-view geometry into the row.",
            "Use tile-unit sizing: common characters are about one tile wide by two tiles tall, with Y-overlap allowed and X-overlap avoided.",
            "For 4/8 direction characters, build front/up/side first, then diagonals; use flippability only when lighting and asymmetry allow it.",
            "For top-down tile or terrain rows, require edge-compatibility and 3x3 repetition review, with negative space to hide pattern seams.",
        ],
    },
    "pixel-isometric": {
        "label": "Pixel isometric/dimetric construction",
        "sources": ["04-graphical-projection-part-2", "41-isometric-pixel-art", "54-more-isometric-pixels", "61-isometric-mecha-tactics"],
        "rules": [
            "Use the 2:1 pixel line convention as the hard grid; count pixels or use a ruler instead of eyeballing angled edges.",
            "Map volumes as cuboids/wireframes first, including hidden construction lines, then color planes by light direction and material.",
            "Tiles must be seamless on the relevant isometric surfaces, not only on the visible top plane.",
            "Round organic forms still need projection anchors: trunks, roots, bases, feet, or hard-surface parts should carry the 2:1 read.",
        ],
    },
    "pixel-texture": {
        "label": "Pixel texture, tiles, and materials",
        "sources": ["02-texture", "13-rocks", "15-plant-life", "20-top-down-tiles", "28-side-view-tiles", "45-bricks-walls-doors-and-more"],
        "rules": [
            "Texture is suggestion, not literal detail: repeat a few cluster motifs with varied spacing and clear negative space.",
            "Cluster density must match scale: small cells need only a few strong clusters; high-frequency detail becomes blurry noise.",
            "Seamless tiles require matching edges plus a zoomed-out 3x3 review to catch crosses, diagonals, and obvious repeated clusters.",
            "Materials should respect subject logic: rocks need geological color/form, plants need biomes and repeated leaf clusters, bricks need selective gaps rather than every brick outlined.",
        ],
    },
    "pixel-combat": {
        "label": "Pixel combat, melee, and fighting rows",
        "sources": ["09-melee-attacks", "52-idle-fighting-stance", "53-punches-and-kicks", "56-top-down-character-attack-animation"],
        "rules": [
            "Start from stance and biomechanics: weapon, guard, center of mass, support foot, hips, and shoulders must explain the attack.",
            "For attack rows, use clear phases: load or anticipation when needed, smear with the strike direction, hit/contact, follow-through, recovery, and overshoot.",
            "For attack rows, the hit/contact frame should be the clearest silhouette and may hold slightly longer; the visual range should match the intended hitbox.",
            "For attack rows, frame count encodes risk/reward: jab-like actions stay snappy, heavy weapons get more anticipation/follow-through/recovery, and smears stay brief.",
            "For attack rows, do not put smears counter to the main motion or hide a weak body pose behind detached effects.",
        ],
    },
    "pixel-items-ui": {
        "label": "Pixel items, pickups, and UI icons",
        "sources": ["24-items", "26-uxui-design-basics", "30-food"],
        "rules": [
            "Recognize items by silhouette plus local color first; interior detail is secondary, especially around 16x16.",
            "Idle animation is affordance: bounce, bob, shine, or rotate only when it fits the item type and does not distract.",
            "Use a consistent feedback grammar: currency, pickups, powerups, health, and UI confirmation should not use random unrelated effects.",
            "UI and icons must be readable at a glance and must not compete with the player/action focal point.",
        ],
    },
    "pixel-vfx": {
        "label": "Pixel VFX, water, wind, and explosions",
        "sources": ["10-water-in-motion", "31-shmup-design-part-1", "33-wind-effects"],
        "rules": [
            "VFX sequences need readable buildup, peak, decay, and fade; the emitter or contact point should stay stable.",
            "Water, fire, electricity, wind, and similar periodic effects need loop math: equal spacing, consistent displacement, and no end-to-start pop.",
            "Wind and ambient effects must add life without stealing focus or changing composition; use flow points and propagation instead of random motion.",
            "Explosions and impacts should expand fast at first, then cool/fade from hot colors toward smoke or alpha; avoid linear growth.",
        ],
    },
    "pixel-shmup": {
        "label": "Pixel shmup/readability systems",
        "sources": ["31-shmup-design-part-1", "32-shmup-design-part-2", "48-military-shmup"],
        "rules": [
            "Projectiles and hazards must be the most vivid/readable elements and must remain legible on every expected background.",
            "Faction units need shared visual language plus distinct silhouettes, colors, size, speed, and behavior roles.",
            "Ships need roll/tilt and thruster feedback; directional lighting may require unique left/right frames instead of mirroring.",
            "Pickups require distinct meaning, rarity, movement, and affordance so they never read as hazards.",
        ],
    },
    "pixel-tiny": {
        "label": "Pixel tiny-scale economy",
        "sources": ["36-8-bit-adventure", "47-tiny-pixels", "59-tiny-sci-fi-pixels"],
        "rules": [
            "At tiny scale, beauty comes from missing information. Preserve only necessary silhouette, local color, and one or two telling pixels.",
            "Use outlines when the palette/background can swallow the sprite, especially NES-like or 8x8 sci-fi work.",
            "One-pixel movement is already large. Use minimal shifts for turns, posture, gait, and expression instead of smooth sub-frame drift.",
            "Avoid 8-frame cycles when 2, 3, 4, or 6 strong frames communicate the same idea with less noise.",
        ],
    },
    "pixel-environment": {
        "label": "Pixel environment and background support",
        "sources": ["11-landscape-pixeling", "14-cityscapes", "23-parallax-scrolling", "35-top-down-interiors", "62-landscape-backgrounds"],
        "rules": [
            "Backgrounds serve the scene: action games need muted/supportive layers; RPG/adventure scenes can carry richer mood.",
            "Use atmospheric perspective and color reuse: distant layers are lighter, less saturated, and lower contrast than near gameplay layers.",
            "Prefer a few modular tiles plus occasional landmarks over either all-generic repetition or all-custom expense.",
            "Keep collision/gameplay surfaces visually distinct from decorative texture and parallax layers.",
        ],
    },
}
ART_PROFILE_ORDER = list(ART_PROFILES)
ART_PROFILE_CHOICES = {ART_PROFILE_AUTO, *ART_PROFILES}
ANIMATION_WORKFLOW_AUTO = "auto"
TEMPORAL_FRAME_SEMANTICS = {"animation", "effects"}
STATIC_FRAME_SEMANTICS = {
    "variants",
    "tiles",
    "still-assets",
    "seamless-textures",
}

ANIMATION_WORKFLOWS: dict[str, dict[str, Any]] = {
    "idle-breath": {
        "label": "Idle breathing workflow",
        "sources": ["08-intro-to-animation", "52-idle-fighting-stance"],
        "rules": [
            "Anchor the loop on torso breathing or weight shift, then propagate smaller delayed motion into head, hands, hair, cloth, or props.",
            "Use asymmetric timing: a slower rise/hold and a faster downward gravity accent usually reads more alive than a uniform sine bob.",
            "Keep the bounding box and feet stable unless the state asks for stepping; subtle cluster shifts can sell motion below one pixel.",
            "The final frame must reconnect to the first without jitter, orphan pixels, or random detail flicker.",
        ],
    },
    "fighting-stance-idle": {
        "label": "Fighting stance idle workflow",
        "sources": ["52-idle-fighting-stance", "53-punches-and-kicks"],
        "rules": [
            "Treat idle as personality and readiness, not neutral standing: guard, knees, center of mass, and stance width must match the fighter and weapon.",
            "Torso motion is the anchor; fists, hair, loose cloth, and guard amplify it slightly instead of moving with identical pixel distance.",
            "Keep the stance biomechanically plausible: boxer-like upper-body guard, lower-center kick stance, weapon balance, or equivalent character-specific logic.",
            "Avoid a robotic up/down bounce; use holds and offset timing so relaxed muscles still feel alert.",
        ],
    },
    "sideview-locomotion": {
        "label": "Side-view locomotion workflow",
        "sources": ["08-intro-to-animation", "25-motion-cycles", "50-human-walk-cycle", "60-side-view-run-n-gun"],
        "rules": [
            "Plan the cycle around contact, down, pass, and swing. Contact/pass are protected key poses when reducing frame count.",
            "Arms and legs move cross-laterally: opposite arm and leg share momentum, with torso/hip/shoulder counter-motion supporting the gait.",
            "Use a triangle-like head/body bob with accents, not a perfect sine wave; run is usually a leaned, faster, higher-energy walk.",
            "Frame economy matters: 8 frames is fluid, 6 is a strong default, 4 keeps core energy, and 3 can work only with strong stride/pass keys.",
            "Check the loop at playback speed for anchor jitter, foot sliding, same-leg repetition, and noisy pixel flicker.",
        ],
    },
    "topdown-locomotion": {
        "label": "Top-down locomotion workflow",
        "sources": ["55-top-down-character-animation", "58-top-down-character-animation-part-3"],
        "rules": [
            "Choose direction strategy first: 4 directions, 5 flippable orientations, or 8 unique orientations when asymmetry/handedness requires it.",
            "Build front/up/side first and diagonals last; rotation playback should reveal thickness, limb length, and projection errors.",
            "Use a 6-frame variable bounce when possible: down, down, then a faster rise into the pass/tall frame rather than uniform bobbing.",
            "Animate one anatomy/equipment layer at a time. Base motion should work before adding cape, hair, weapon, shield, or loadout details.",
            "For asymmetric gear, do not flip blindly; preserve the weapon/shield/marking side across directions.",
        ],
    },
    "combat-quick-strike": {
        "label": "Combat quick-strike workflow",
        "sources": ["09-melee-attacks", "53-punches-and-kicks"],
        "rules": [
            "Use immediate gameplay feedback: jab/front-kick style actions should have little or no windup, then smear, hit/contact, follow-through, recover, and overshoot.",
            "The smear follows the main motion direction and is brief; do not smear counter to the strike or hide a weak body pose behind effects.",
            "The hit/contact frame is the clearest silhouette and may hold slightly longer for impact.",
            "Recover back toward guard quickly; overshoot can shift the idle/stance back by about one pixel to create snap.",
        ],
    },
    "combat-power-strike": {
        "label": "Combat power-strike workflow",
        "sources": ["09-melee-attacks", "53-punches-and-kicks"],
        "rules": [
            "Use load/pull or anticipation only when the move is meant to trade responsiveness for power, range, or commitment.",
            "Sequence the action as load or pull, fast smear, hit/contact, follow-through, recover, and overshoot/settle.",
            "Heavy weapons and finishers can hold anticipation or follow-through longer, but smears stay few and fast.",
            "Weapon, hips, shoulders, support foot, and line of action must all explain the same force direction.",
        ],
    },
    "topdown-weapon-attack": {
        "label": "Top-down weapon attack workflow",
        "sources": ["56-top-down-character-attack-animation", "58-top-down-character-animation-part-3"],
        "rules": [
            "Use the five-phase attack structure: anticipation, forward smear, optional rebound on ground/contact weapons, follow-through, and recover.",
            "Six frames is a practical default; timing encodes weight, with quick swords, more committed spears, and slower hammer-like weapons.",
            "Smear only with the forward strike, not during anticipation or recovery, so the attack direction remains readable.",
            "Preserve handedness across all directions. A weapon should not jump hands because a row was flipped.",
            "Balance the visual hitbox across directions so no angle looks unfairly longer, shorter, or weaker unless gameplay asks for it.",
        ],
    },
    "responsive-jump": {
        "label": "Responsive jump workflow",
        "sources": ["08-intro-to-animation", "60-side-view-run-n-gun"],
        "rules": [
            "For action/platformer/run-n-gun jumps, avoid long anticipation; input response matters more than a realistic crouch windup.",
            "Use at least distinct up and down poses when frames allow, with the same body scale moving vertically through the slot.",
            "Landing can recycle crouch/compression plus a brief head/arms dip or overshoot when the fall distance justifies it.",
            "Do not draw motion marks, dust, or shadows to compensate for weak body placement.",
        ],
    },
    "hit-reaction-knockdown": {
        "label": "Hit reaction and knockdown workflow",
        "sources": ["09-melee-attacks", "53-punches-and-kicks"],
        "rules": [
            "Show force direction first: impact, recoil/drag, overshoot, fall/contact or partial recovery, then settle.",
            "Keep the same character scale while changing pose, center of mass, and orientation; do not zoom the hurt pose.",
            "A reaction is not a surprised idle. The body should lose balance or brace according to the incoming hit.",
            "Knockdowns need readable ground contact and final down silhouette without cropping.",
        ],
    },
    "run-gun-layered-motion": {
        "label": "Run-and-gun layered motion workflow",
        "sources": ["60-side-view-run-n-gun"],
        "rules": [
            "Treat legs and torso/weapon as separable motion layers: legs keep locomotion flow while the upper body carries aim/shoot expression.",
            "Run is a modified walk: lean forward, increase stride and bounce, and speed up playback instead of inventing an unrelated cycle.",
            "Weapon sway should ride the shoulder/body bounce without breaking the leg cycle.",
            "Hair or cloth secondary motion should obey the main locomotion rhythm; suppress noisy competing flips during running.",
        ],
    },
    "vfx-buildup-peak-decay": {
        "label": "VFX buildup-peak-decay workflow",
        "sources": ["10-water-in-motion", "31-shmup-design-part-1", "33-wind-effects"],
        "rules": [
            "Stage effects as buildup, peak, decay, and fade/cooling; avoid linear growth where every frame has equal energy.",
            "Keep emitter/contact anchor stable so the effect reads as attached to the source or impact point.",
            "Use alpha-friendly opacity and colors that will not collide with the chroma key.",
            "Review at playback speed for pop, focus stealing, and end-to-start discontinuity.",
        ],
    },
    "water-loop": {
        "label": "Water loop workflow",
        "sources": ["10-water-in-motion"],
        "rules": [
            "Build the wave or flow guide first, then animate it; do not hope animation will fix a bad static water shape.",
            "Loop math must close: total displacement across N frames should be an integer multiple of the tile or repeated band width.",
            "Waterfalls need synchronized mouth, vertical flow, and splash components; bands sag/darken as they fall and break near the bottom.",
            "Reflections start from good static art, then add subtle directional ripple from an off-area source.",
        ],
    },
    "wind-ambient-loop": {
        "label": "Wind ambient loop workflow",
        "sources": ["33-wind-effects"],
        "rules": [
            "Wind adds life without taking focus; choose particle swirls, dust clouds, hair/fabric waves, plant waving, falling leaves, or rustling based on the scene material.",
            "Use flow points as the line of action. Random per-frame shifts read as noise, not wind.",
            "Layered plants/fabric should propagate one wave per loop with offset timing rather than moving every leaf at once.",
            "Small sprites often need flat color for wind motion; extra shading can become flicker.",
        ],
    },
    "pickup-feedback": {
        "label": "Pickup feedback workflow",
        "sources": ["24-items", "26-uxui-design-basics", "31-shmup-design-part-1"],
        "rules": [
            "Idle affordance should match item meaning: bob, bounce, shine, rotate, pulse, or hover only if it helps recognition.",
            "Feedback must read as collectible/confirmation, not as hazard, projectile, or environmental noise.",
            "Use silhouette and local color before detail; small icons should be recognizable in one glance.",
            "Keep loops short and stable so pickups are noticeable without competing with player action.",
        ],
    },
    "tiny-motion": {
        "label": "Tiny sprite motion workflow",
        "sources": ["36-8-bit-adventure", "47-tiny-pixels", "59-tiny-sci-fi-pixels"],
        "rules": [
            "At tiny scale, one pixel is a large move. Use 1px offsets, cluster swaps, and 2-4 strong keys instead of smooth over-animation.",
            "Remove detail that turns into noise during playback; missing information is often more readable than literal anatomy.",
            "Use outline or local color contrast when the expected background could swallow the sprite.",
            "Do not spend frames on transitions that do not change the runtime read.",
        ],
    },
}
ANIMATION_WORKFLOW_ORDER = list(ANIMATION_WORKFLOWS)
ANIMATION_WORKFLOW_CHOICES = {ANIMATION_WORKFLOW_AUTO, *ANIMATION_WORKFLOWS}

RUN_PHASE_CYCLE = [
    {
        "name": "contact",
        "body_y": 0,
        "front_leg": "forward_straight",
        "back_leg": "back_extended",
        "note": "front foot contacts ground, back foot pushes off",
    },
    {
        "name": "down",
        "body_y": 6,
        "front_leg": "under_bent",
        "back_leg": "back_bent",
        "note": "weight drops over planted foot",
    },
    {
        "name": "passing",
        "body_y": 2,
        "front_leg": "under_vertical",
        "back_leg": "passing_forward",
        "note": "swing leg passes under body",
    },
    {
        "name": "up",
        "body_y": -6,
        "front_leg": "back_lifted",
        "back_leg": "forward_lifted",
        "note": "body lifts before the opposite contact",
    },
    {
        "name": "opposite_contact",
        "body_y": 0,
        "front_leg": "back_extended",
        "back_leg": "forward_straight",
        "note": "opposite foot contacts ground",
    },
    {
        "name": "opposite_down",
        "body_y": 6,
        "front_leg": "back_bent",
        "back_leg": "under_bent",
        "note": "weight drops over the opposite planted foot",
    },
    {
        "name": "opposite_passing",
        "body_y": 2,
        "front_leg": "passing_forward",
        "back_leg": "under_vertical",
        "note": "first leg passes under body",
    },
    {
        "name": "opposite_up",
        "body_y": -6,
        "front_leg": "forward_lifted",
        "back_leg": "back_lifted",
        "note": "body lifts back toward frame 1",
    },
]

CHROMA_CANDIDATES = [
    ("green", "#00FF00"),
    ("cyan", "#00FFFF"),
    ("blue", "#004DFF"),
    ("magenta", "#FF00FF"),
]

RUN_PHASE_INDICES_BY_FRAME_COUNT = {
    4: [0, 2, 4, 6],
    6: [0, 1, 2, 4, 5, 6],
    8: list(range(8)),
}


def parse_hex_color(value: str) -> tuple[int, int, int]:
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        raise SystemExit(f"invalid chroma key color: {value}; expected #RRGGBB")
    return tuple(int(value[index : index + 2], 16) for index in (1, 3, 5))


def rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"


def color_distance(left: tuple[int, int, int], right: tuple[int, int, int]) -> float:
    return math.sqrt(sum((left[index] - right[index]) ** 2 for index in range(3)))


def sampled_reference_pixels(path: Path | None) -> list[tuple[int, int, int]]:
    if path is None or not path.is_file():
        return []
    pixels: list[tuple[int, int, int]] = []
    with Image.open(path) as opened:
        image = opened.convert("RGBA")
        image.thumbnail((128, 128), Image.Resampling.LANCZOS)
        data = image.tobytes()
        for index in range(0, len(data), 4):
            red, green, blue, alpha = data[index : index + 4]
            if alpha <= 16:
                continue
            if red > 244 and green > 244 and blue > 244:
                continue
            pixels.append((red, green, blue))
    return pixels


def choose_chroma_key(reference: Path | None, requested: str) -> dict[str, Any]:
    if requested.lower() != "auto":
        rgb = parse_hex_color(requested)
        hex_value = rgb_to_hex(rgb)
        name = next((candidate_name for candidate_name, candidate_hex in CHROMA_CANDIDATES if candidate_hex == hex_value), "manual")
        return {"name": name, "hex": hex_value, "rgb": list(rgb), "selection": "manual"}

    pixels = sampled_reference_pixels(reference)
    if not pixels:
        rgb = parse_hex_color("#00FF00")
        return {"name": "green", "hex": "#00FF00", "rgb": list(rgb), "selection": "fallback"}

    scored: list[tuple[float, int, str, tuple[int, int, int]]] = []
    for preference_index, (name, hex_color) in enumerate(CHROMA_CANDIDATES):
        rgb = parse_hex_color(hex_color)
        distances = sorted(color_distance(rgb, pixel) for pixel in pixels)
        percentile_index = max(0, min(len(distances) - 1, int(len(distances) * 0.01)))
        scored.append((distances[percentile_index], -preference_index, name, rgb))
    score, _preference, name, rgb = max(scored)
    return {
        "name": name,
        "hex": rgb_to_hex(rgb),
        "rgb": list(rgb),
        "selection": "auto",
        "score": round(score, 2),
    }


def normalize_background_removal(raw: dict[str, Any], args: argparse.Namespace, asset_kind: str, extraction_mode: str) -> dict[str, Any]:
    source = raw.get("background_removal") if isinstance(raw.get("background_removal"), dict) else {}
    default_method = "none" if extraction_mode == "slots" and asset_kind in {"texture", "tileset"} else "auto"
    method = args.background_removal or str(source.get("method", default_method))
    if method not in BACKGROUND_REMOVAL_METHODS:
        raise SystemExit("background_removal.method must be none, chroma, rembg, ben2, or auto")
    default_model = DEFAULT_BEN2_MODEL if method == "ben2" else DEFAULT_REMBG_MODEL
    model = args.background_model or str(source.get("model", default_model))
    device = args.background_device or str(source.get("device", "auto"))
    alpha_matting = source.get("alpha_matting", False)
    if args.alpha_matting is not None:
        alpha_matting = args.alpha_matting
    if not isinstance(alpha_matting, bool):
        raise SystemExit("background_removal.alpha_matting must be boolean")
    return {"method": method, "model": model, "device": device, "alpha_matting": alpha_matting}


def normalize_states(raw: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    source = DEFAULT_STATES if raw is None else raw
    if not isinstance(source, dict) or not source:
        raise SystemExit("states must be a non-empty object")
    normalized: dict[str, dict[str, Any]] = {}
    for state, entry in source.items():
        if not is_state_slug(state):
            raise SystemExit(
                f"invalid state id {state!r}; use a 1-64 character lowercase kebab slug"
            )
        if not isinstance(entry, dict):
            raise SystemExit(f"state {state!r} must be an object")
        frames = int(entry.get("frames", 0))
        if frames <= 0:
            raise SystemExit(f"state {state!r} must have positive frames")
        fps = int(entry.get("fps", DEFAULT_STATES.get(state, {}).get("fps", 6)))
        if fps <= 0:
            raise SystemExit(f"state {state!r} must have positive fps")
        normalized[state] = {
            "frames": frames,
            "fps": fps,
            "loop": bool(entry.get("loop", True)),
            "action": str(entry.get("action", DEFAULT_STATES.get(state, {}).get("action", state))),
        }
        if "durations_ms" in entry:
            normalized[state]["durations_ms"] = entry["durations_ms"]
        if "animation_workflows" in entry:
            normalized[state]["animation_workflows"] = entry["animation_workflows"]
        if "pose_geometry" in entry:
            normalized[state]["pose_geometry"] = entry["pose_geometry"]
        if "raw_layout" in entry:
            normalized[state]["raw_layout"] = entry["raw_layout"]
        for key in ("label", "labels", "asset_labels", "asset_names"):
            if key in entry:
                normalized[state][key] = entry[key]
    return normalized


def normalize_cell(raw_cell: dict[str, Any], size: int, safe_margin: int) -> dict[str, Any]:
    width = int(raw_cell.get("width", raw_cell.get("cell_width", raw_cell.get("size", size))))
    height = int(raw_cell.get("height", raw_cell.get("cell_height", raw_cell.get("size", size))))
    margin_x = int(raw_cell.get("safe_margin_x", raw_cell.get("safe_margin", safe_margin)))
    margin_y = int(raw_cell.get("safe_margin_y", raw_cell.get("safe_margin", safe_margin)))
    if width <= 0 or height <= 0:
        raise SystemExit("cell width and height must be positive")
    if margin_x < 0 or margin_y < 0 or margin_x * 2 >= width or margin_y * 2 >= height:
        raise SystemExit("cell safe margins must fit inside cell width/height")
    cell: dict[str, Any] = {
        "shape": "rect" if width != height else "square",
        "width": width,
        "height": height,
        "safe_margin_x": margin_x,
        "safe_margin_y": margin_y,
    }
    if width == height and margin_x == margin_y:
        cell["size"] = width
        cell["safe_margin"] = margin_x
    return cell


def load_request(path: Path | None, inline_json: str | None) -> dict[str, Any]:
    if path and inline_json:
        raise SystemExit("use only one of --request or --request-json")
    if path:
        return json.loads(path.read_text(encoding="utf-8"))
    if inline_json:
        return json.loads(inline_json)
    return {}


def is_locomotion_state(state: str, entry: dict[str, Any] | None = None) -> bool:
    tokens = state_tokens(state, entry)
    workflows = entry.get("animation_workflows", []) if isinstance(entry, dict) else []
    workflow_text = " ".join(str(item) for item in workflows) if isinstance(workflows, list) else str(workflows)
    if "locomotion" in workflow_text:
        return True
    if re.search(r"(^|-)(walk|walking|run|running|move|moving|advance|retreat|dash|dashing)(-|$)", state.lower()):
        return True
    return bool(tokens & {"walk", "walking", "run", "running", "move", "moving", "advance", "retreat", "dash", "dashing"})


def state_tokens(state: str, entry: dict[str, Any] | None = None) -> set[str]:
    text = state
    if entry:
        text = f"{text} {entry.get('action', '')}"
    return {token for token in re.split(r"[^a-z0-9]+", text.lower()) if token}


def is_fighting_context(request: dict[str, Any], state: str, entry: dict[str, Any]) -> bool:
    preset = request.get("preset") if isinstance(request.get("preset"), dict) else {}
    preset_id = str(preset.get("id", "")).lower()
    camera = str(preset.get("camera", "")).lower()
    character = request.get("character") if isinstance(request.get("character"), dict) else {}
    descriptor = " ".join(
        [
            preset_id,
            camera,
            str(character.get("description", "")).lower(),
            state,
            str(entry.get("action", "")).lower(),
        ]
    )
    tokens = state_tokens(state, entry)
    if "fighting" in descriptor or "fighter" in descriptor or "combat" in descriptor:
        return True
    return bool(tokens & {"punch", "kick", "block", "guard", "hitstun", "knockdown", "special", "combo"})


def request_descriptor(request: dict[str, Any], state: str = "", entry: dict[str, Any] | None = None) -> str:
    preset = request.get("preset") if isinstance(request.get("preset"), dict) else {}
    character = request.get("character") if isinstance(request.get("character"), dict) else {}
    parts = [
        str(request.get("asset_kind", "")),
        str(request.get("style_preset", "")),
        str(request.get("style", "")),
        str(preset.get("id", "")),
        str(preset.get("camera", "")),
        str(character.get("description", "")),
        state,
    ]
    if entry:
        parts.append(str(entry.get("action", "")))
    return " ".join(parts).lower()


def normalize_profile_list(value: Any, source: str) -> list[str]:
    if value in (None, False):
        return []
    if isinstance(value, str):
        items = [item.strip() for item in value.split(",") if item.strip()]
    elif isinstance(value, list):
        items = [str(item).strip() for item in value if str(item).strip()]
    else:
        raise SystemExit(f"{source} must be a string or list")
    for profile in items:
        if profile not in ART_PROFILE_CHOICES:
            choices = ", ".join(sorted(ART_PROFILE_CHOICES))
            raise SystemExit(f"unknown art profile {profile!r}; choices: {choices}")
    return items


def normalize_workflow_list(value: Any, source: str) -> list[str]:
    if value in (None, False):
        return []
    if isinstance(value, str):
        items = [item.strip() for item in value.split(",") if item.strip()]
    elif isinstance(value, list):
        items = [str(item).strip() for item in value if str(item).strip()]
    else:
        raise SystemExit(f"{source} must be a string or list")
    for workflow in items:
        if workflow not in ANIMATION_WORKFLOW_CHOICES:
            choices = ", ".join(sorted(ANIMATION_WORKFLOW_CHOICES))
            raise SystemExit(f"unknown animation workflow {workflow!r}; choices: {choices}")
    return items


def dedupe_ordered(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def normalize_art_direction(raw: dict[str, Any], args: argparse.Namespace, asset_kind: str, style_preset: str) -> dict[str, Any]:
    raw_direction = raw.get("art_direction")
    mode = args.art_direction
    profiles: list[str] = []
    if isinstance(raw_direction, dict):
        if raw_direction.get("mode") is not None:
            mode = str(raw_direction.get("mode"))
        profiles.extend(normalize_profile_list(raw_direction.get("profiles"), "art_direction.profiles"))
    elif isinstance(raw_direction, str):
        mode = raw_direction
    elif raw_direction not in (None, False):
        raise SystemExit("art_direction must be a string or object")
    profiles.extend(normalize_profile_list(raw.get("art_profiles"), "art_profiles"))
    if args.art_profile:
        profiles.extend(args.art_profile)
    explicit_profiles = bool(profiles)

    if mode is None:
        mode = "pixel-art" if (explicit_profiles or style_preset == "pixel-art" or asset_kind in {"tileset", "texture"}) else "none"
    if mode in {"off", "false"}:
        mode = "none"
    mode = ART_DIRECTION_MODE_ALIASES.get(mode, mode)
    if mode not in ART_DIRECTION_MODES:
        choices = ", ".join(sorted(ART_DIRECTION_MODES))
        raise SystemExit(f"unknown art_direction mode {mode!r}; choices: {choices}")
    profiles = dedupe_ordered(profiles) if profiles else [ART_PROFILE_AUTO]
    if mode == "none":
        profiles = []
    return {
        "mode": mode,
        "source": "pixel-art-wiki-derived",
        "reference": "references/pixel-art-direction.md",
        "workflow_reference": "references/pixel-animation-workflows.md",
        "profiles": profiles,
    }


def infer_art_profiles(request: dict[str, Any], state: str, entry: dict[str, Any], asset_kind: str) -> list[str]:
    descriptor = request_descriptor(request, state, entry)
    tokens = state_tokens(state, entry)
    profiles = ["pixel-core"]
    cell = request.get("cell") if isinstance(request.get("cell"), dict) else {}
    cell_width = int(cell.get("width", 999))
    cell_height = int(cell.get("height", 999))
    catalog = request.get("asset_catalog") if isinstance(request.get("asset_catalog"), dict) else {}
    projection_text = " ".join(
        str(value).lower()
        for value in (request.get("projection"), catalog.get("projection"))
        if isinstance(value, str)
    )
    is_isometric = (
        "isometric" in descriptor
        or "dimetric" in descriptor
        or "isometric" in projection_text
        or "dimetric" in projection_text
        or "2:1" in projection_text
        or bool(request.get("iso"))
    )

    if asset_kind == "sprite":
        profiles.extend(["pixel-character", "pixel-motion"])
        if cell_width <= 32 or cell_height <= 32 or "tiny" in descriptor or "8-bit" in descriptor or "nes" in descriptor:
            profiles.append("pixel-tiny")
        if is_isometric or tokens & {"se", "sw", "ne", "nw"}:
            profiles.append("pixel-isometric")
        if "topdown" in descriptor or "top-down" in descriptor or tokens & {"up", "down"}:
            profiles.append("pixel-topdown")
        if "side" in descriptor or "platformer" in descriptor or "run-n-gun" in descriptor:
            profiles.append("pixel-sideview")
        if is_fighting_context(request, state, entry):
            profiles.append("pixel-combat")
        if "shmup" in descriptor or tokens & {"ship", "projectile", "bullet", "laser"}:
            profiles.append("pixel-shmup")
        if tokens & {"vfx", "fx", "effect", "explosion", "impact", "spark", "smoke", "fire", "water", "wind"}:
            profiles.append("pixel-vfx")
        return order_art_profiles(profiles)

    if asset_kind in {"tileset", "texture"}:
        profiles.append("pixel-texture")
    if asset_kind == "tileset":
        if is_isometric:
            profiles.append("pixel-isometric")
        elif "side" in descriptor or "platformer" in descriptor:
            profiles.append("pixel-sideview")
        else:
            profiles.append("pixel-topdown")
    if asset_kind in {"asset", "prop", "props", "icon", "ui"}:
        profiles.append("pixel-texture")
        if asset_kind in {"icon", "ui"} or tokens & {"pickup", "pickups", "item", "items", "icon", "icons", "heart", "coin", "gem", "ui"}:
            profiles.append("pixel-items-ui")
    if asset_kind == "vfx" or tokens & {"vfx", "fx", "effect", "explosion", "impact", "spark", "smoke", "fire", "water", "wind", "decal", "decals"}:
        profiles.append("pixel-vfx")
    if "shmup" in descriptor or tokens & {"ship", "projectile", "bullet", "laser", "pickup", "pickups"}:
        profiles.append("pixel-shmup")
    if is_isometric or "mecha" in descriptor:
        profiles.append("pixel-isometric")
    if any(word in descriptor for word in ["background", "landscape", "city", "interior", "parallax", "environment"]):
        profiles.append("pixel-environment")
    return order_art_profiles(profiles)


def order_art_profiles(profiles: list[str]) -> list[str]:
    requested = dedupe_ordered(profiles)
    return [profile for profile in ART_PROFILE_ORDER if profile in requested]


def validate_isometric_catalog_contract(request: dict[str, Any]) -> None:
    asset_kind = str(request.get("asset_kind", "sprite"))
    catalog = request.get("asset_catalog") if isinstance(request.get("asset_catalog"), dict) else {}
    projection = str(catalog.get("projection", request.get("projection", ""))).lower()
    if asset_kind != "tileset" or not any(marker in projection for marker in ("isometric", "dimetric", "2:1")):
        return
    tile = catalog.get("tile") if isinstance(catalog.get("tile"), dict) else {}
    if not tile:
        raise SystemExit("isometric tilesets require asset_catalog.tile before generation")
    tile_w = float(tile.get("width", 0))
    tile_h = float(tile.get("height", 0))
    if tile_w <= 0 or tile_h <= 0:
        raise SystemExit("isometric asset_catalog.tile width/height must be positive before generation")
    if abs((tile_w / tile_h) - 2.0) > 0.12:
        raise SystemExit(f"isometric asset_catalog.tile must be 2:1 before generation, got {tile_w:g}x{tile_h:g}")
    cell = request.get("cell") if isinstance(request.get("cell"), dict) else {}
    runtime_cell = tile.get("runtimeCell") or tile.get("runtime_cell")
    if isinstance(runtime_cell, list) and len(runtime_cell) == 2:
        expected = [int(runtime_cell[0]), int(runtime_cell[1])]
        actual = [int(cell.get("width", 0)), int(cell.get("height", 0))]
        if expected != actual:
            raise SystemExit(f"isometric asset_catalog.tile.runtimeCell {expected} must match request.cell {actual} before generation")


def order_animation_workflows(workflows: list[str]) -> list[str]:
    requested = dedupe_ordered(workflows)
    return [workflow for workflow in ANIMATION_WORKFLOW_ORDER if workflow in requested]


def active_art_profiles(request: dict[str, Any], state: str, entry: dict[str, Any], asset_kind: str) -> list[str]:
    art_direction = request.get("art_direction") if isinstance(request.get("art_direction"), dict) else {}
    if art_direction.get("mode") != "pixel-art":
        return []
    requested = normalize_profile_list(art_direction.get("profiles") or [ART_PROFILE_AUTO], "art_direction.profiles")
    profiles: list[str] = []
    if ART_PROFILE_AUTO in requested:
        profiles.extend(infer_art_profiles(request, state, entry, asset_kind))
    profiles.extend(profile for profile in requested if profile != ART_PROFILE_AUTO)
    return order_art_profiles(profiles)


def infer_animation_workflows(request: dict[str, Any], state: str, entry: dict[str, Any], asset_kind: str) -> list[str]:
    if request.get("frame_semantics", "animation") not in TEMPORAL_FRAME_SEMANTICS:
        return []
    descriptor = request_descriptor(request, state, entry)
    tokens = state_tokens(state, entry)
    state_only_tokens = set(re.findall(r"[a-z0-9]+", state.lower()))
    profiles = active_art_profiles(request, state, entry, asset_kind)
    workflows: list[str] = []
    is_topdown = "pixel-topdown" in profiles and "pixel-sideview" not in profiles
    if "topdown" in descriptor or "top-down" in descriptor:
        is_topdown = True
    is_sideview = "pixel-sideview" in profiles or "side" in descriptor or "platformer" in descriptor or "run-n-gun" in descriptor
    action_tokens = {
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
    }
    quick_tokens = {"jab", "punch", "punching", "frontkick", "front-kick"}
    power_tokens = {
        "cross",
        "heavy",
        "power",
        "round",
        "roundhouse",
        "slash",
        "slashing",
        "swing",
        "sword",
        "spear",
        "hammer",
        "mace",
        "attack",
        "special",
        "cast",
    }
    water_tokens = {"water", "waterfall", "river", "ripple", "splash", "lake", "ocean", "wave", "waves"}
    wind_tokens = {"wind", "fabric", "cloth", "hair", "leaf", "leaves", "grass", "tree", "trees", "dust", "cloud", "swirl"}
    pickup_tokens = {"pickup", "pickups", "item", "items", "coin", "coins", "gem", "gems", "heart", "powerup", "powerups", "icon", "icons"}
    vfx_tokens = {"vfx", "fx", "effect", "effects", "explosion", "spark", "sparks", "smoke", "fire", "electric", "electricity"}

    if asset_kind == "sprite":
        if "pixel-tiny" in profiles:
            workflows.append("tiny-motion")
        if state_only_tokens & {"idle", "stance"}:
            workflows.append("fighting-stance-idle" if is_fighting_context(request, state, entry) else "idle-breath")
        if is_locomotion_state(state):
            workflows.append("topdown-locomotion" if is_topdown and not is_sideview else "sideview-locomotion")
            if "run-n-gun" in descriptor or tokens & {"gun", "guns", "shoot", "shooting", "aim", "aiming"}:
                workflows.append("run-gun-layered-motion")
        if state_only_tokens & {"jump", "jumping", "leap", "leaping", "land", "landing"}:
            workflows.append("responsive-jump")
        if tokens & {"hit", "hurt", "hitstun", "knockdown", "death", "die", "dying"}:
            workflows.append("hit-reaction-knockdown")
        if tokens & action_tokens or any(word in descriptor for word in ["attack", "melee", "punch", "kick", "slash", "sword", "spear", "hammer", "mace"]):
            if is_topdown:
                workflows.append("topdown-weapon-attack")
            elif tokens & quick_tokens and not tokens & power_tokens:
                workflows.append("combat-quick-strike")
            else:
                workflows.append("combat-power-strike")

    if asset_kind == "vfx" or tokens & vfx_tokens:
        workflows.append("vfx-buildup-peak-decay")
    if tokens & water_tokens or any(word in descriptor for word in ["waterfall", "river", "ripple", "water loop"]):
        workflows.append("water-loop")
    if tokens & wind_tokens or any(word in descriptor for word in ["wind", "flutter", "rustling", "waving plant"]):
        workflows.append("wind-ambient-loop")
    if asset_kind in {"icon", "ui", "asset", "prop", "props"} and (tokens & pickup_tokens or any(word in descriptor for word in ["pickup", "collectible", "powerup"])):
        workflows.append("pickup-feedback")
    return order_animation_workflows(workflows)


def active_animation_workflows(request: dict[str, Any], state: str, entry: dict[str, Any], asset_kind: str) -> list[str]:
    art_direction = request.get("art_direction") if isinstance(request.get("art_direction"), dict) else {}
    request_declared = "animation_workflows" in request
    row_declared = "animation_workflows" in entry
    requested: list[str] = []
    requested.extend(normalize_workflow_list(request.get("animation_workflows"), "animation_workflows"))
    requested.extend(normalize_workflow_list(entry.get("animation_workflows"), f"states.{state}.animation_workflows"))
    frame_semantics = str(request.get("frame_semantics", "animation"))
    if frame_semantics in STATIC_FRAME_SEMANTICS:
        if requested:
            raise SystemExit(
                f"states.{state}: static frame_semantics {frame_semantics!r} "
                "cannot declare animation workflows"
            )
        return []
    explicit = [workflow for workflow in requested if workflow != ANIMATION_WORKFLOW_AUTO]
    use_auto = (
        frame_semantics in TEMPORAL_FRAME_SEMANTICS
        and (
            (not request_declared and not row_declared)
            or ANIMATION_WORKFLOW_AUTO in requested
        )
    )
    workflows: list[str] = []
    if use_auto and art_direction.get("mode") == "pixel-art":
        workflows.extend(infer_animation_workflows(request, state, entry, asset_kind))
    workflows.extend(explicit)
    return order_animation_workflows(workflows)


def art_direction_requirements_for_row(request: dict[str, Any], state: str, entry: dict[str, Any], asset_kind: str) -> list[str]:
    requirements: list[str] = []
    for profile_id in active_art_profiles(request, state, entry, asset_kind):
        profile = ART_PROFILES[profile_id]
        label = profile["label"]
        for rule in profile["rules"]:
            requirements.append(f"{label}: {rule}")
    return dedupe_ordered(requirements)


def animation_workflow_requirements_for_row(request: dict[str, Any], state: str, entry: dict[str, Any], asset_kind: str) -> list[str]:
    requirements: list[str] = []
    for workflow_id in active_animation_workflows(request, state, entry, asset_kind):
        workflow = ANIMATION_WORKFLOWS[workflow_id]
        label = workflow["label"]
        for rule in workflow["rules"]:
            requirements.append(f"{label}: {rule}")
    return dedupe_ordered(requirements)


def art_direction_summary(request: dict[str, Any], states: dict[str, dict[str, Any]], asset_kind: str) -> dict[str, Any]:
    art_direction = request.get("art_direction") if isinstance(request.get("art_direction"), dict) else {"mode": "none", "profiles": []}
    rows: dict[str, Any] = {}
    for state, entry in states.items():
        profiles = active_art_profiles(request, state, entry, asset_kind)
        workflows = active_animation_workflows(request, state, entry, asset_kind)
        rows[state] = {
            "profiles": profiles,
            "sources": dedupe_ordered([source for profile_id in profiles for source in ART_PROFILES[profile_id]["sources"]]),
            "animation_workflows": workflows,
            "workflow_sources": dedupe_ordered([source for workflow_id in workflows for source in ANIMATION_WORKFLOWS[workflow_id]["sources"]]),
        }
    return {
        "mode": art_direction.get("mode", "none"),
        "source": art_direction.get("source"),
        "reference": art_direction.get("reference"),
        "workflow_reference": art_direction.get("workflow_reference", "references/pixel-animation-workflows.md"),
        "requested_profiles": art_direction.get("profiles", []),
        "requested_workflows": request.get("animation_workflows", [ANIMATION_WORKFLOW_AUTO]),
        "rows": rows,
    }


def action_phase_requirements(state: str, entry: dict[str, Any]) -> list[str]:
    tokens = state_tokens(state, entry)
    requirements: list[str] = []
    ordered_keys = [
        "idle",
        "block",
        "attack",
        "punch",
        "kick",
        "special",
        "hit",
        "hurt",
        "hitstun",
        "knockdown",
        "death",
        "dodge",
        "cast",
        "taunt",
        "win",
    ]
    for key in ordered_keys:
        if key in tokens:
            requirements.extend(ACTION_PHASE_REQUIREMENTS[key])
    return requirements


def professional_requirements_for_row(
    request: dict[str, Any],
    state: str,
    entry: dict[str, Any],
    asset_kind: str,
) -> list[str]:
    if asset_kind == "sprite":
        requirements = [*SPRITE_PRODUCTION_RULES]
        if is_fighting_context(request, state, entry):
            requirements.append(
                "Treat this as a gameplay-readable fighting/combat state: prioritize stance, hit direction, contact timing, and recovery clarity over a pretty poster pose."
            )
        requirements.extend(action_phase_requirements(state, entry))
        return requirements
    return ASSET_PRODUCTION_RULES.get(asset_kind, ASSET_PRODUCTION_RULES["asset"])


def inferred_pose_geometry(state: str, entry: dict[str, Any]) -> dict[str, Any] | None:
    tokens = state_tokens(state, entry)
    if tokens & {"crouch", "crouching", "duck", "ducking", "squat", "squatting"}:
        return {
            "kind": "crouch",
            "grounded": True,
            "height_curve": "compress",
            "start_height_vs_reference": 1.00,
            "guide_height_ratio": 0.70,
            "target_height_vs_reference": 0.70,
            "min_height_vs_reference": 0.62,
            "min_width_vs_reference": 0.78,
            "min_head_width_vs_reference": 0.84,
            "min_upper_width_vs_reference": 0.84,
            "max_height_vs_reference": 1.05,
            "baseline": "feet",
        }
    if tokens & {"knockdown", "downed", "collapse", "collapsing"}:
        return {
            "kind": "knockdown",
            "grounded": False,
            "guide_height_ratio": 0.62,
            "target_height_vs_reference": 0.70,
            "max_height_vs_reference": 1.12,
            "min_height_vs_reference": 0.45,
            "baseline": "collapse",
        }
    if tokens & {"jump", "jumping", "leap", "leaping", "airborne"}:
        return {
            "kind": "jump",
            "grounded": False,
            "guide_height_ratio": 0.74,
            "target_height_vs_reference": 1.00,
            "max_height_vs_reference": 1.12,
            "min_head_width_vs_reference": 0.90,
            "min_upper_width_vs_reference": 0.72,
            "arc_peak_ratio": 0.22,
            "baseline": "jump-arc",
        }
    if tokens & {"fall", "falling"}:
        return {
            "kind": "fall",
            "grounded": False,
            "guide_height_ratio": 0.74,
            "target_height_vs_reference": 1.00,
            "max_height_vs_reference": 1.12,
            "min_head_width_vs_reference": 0.90,
            "min_upper_width_vs_reference": 0.88,
            "airborne_bottom_ratio": 0.18,
            "baseline": "airborne",
        }
    if tokens & {"land", "landing"}:
        return {
            "kind": "land",
            "grounded": True,
            "guide_height_ratio": 0.70,
            "target_height_vs_reference": 0.78,
            "max_height_vs_reference": 0.95,
            "min_head_width_vs_reference": 0.86,
            "min_upper_width_vs_reference": 0.86,
            "baseline": "feet",
        }
    return None


def state_pose_geometry(state: str, entry: dict[str, Any]) -> dict[str, Any] | None:
    raw = entry.get("pose_geometry")
    if raw is False or raw == "none":
        return None
    inferred = inferred_pose_geometry(state, entry) or {}
    if raw is None:
        return inferred or None
    if not isinstance(raw, dict):
        raise SystemExit(f"state {state!r} pose_geometry must be an object, false, or 'none'")
    if raw.get("enabled") is False:
        return None
    merged = {**inferred, **raw}
    if merged.get("kind") == "crouch" and str(merged.get("height_curve", "")) == "compress":
        start_ratio = float(merged.get("start_height_vs_reference", 1.0))
        max_ratio = float(merged.get("max_height_vs_reference", start_ratio))
        if max_ratio < start_ratio:
            merged["max_height_vs_reference"] = start_ratio
        if isinstance(raw, dict) and "height_curve" not in raw:
            inferred_target = float(inferred.get("target_height_vs_reference", 0.70))
            target_ratio = float(merged.get("target_height_vs_reference", inferred_target))
            if target_ratio < inferred_target:
                merged["target_height_vs_reference"] = inferred_target
                merged["guide_height_ratio"] = inferred_target
    return merged or None


def state_motion_phases(state: str, frames: int, entry: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    if is_locomotion_state(state, entry):
        phase_indices = RUN_PHASE_INDICES_BY_FRAME_COUNT.get(frames)
        if not phase_indices:
            return []
        return [RUN_PHASE_CYCLE[index] for index in phase_indices]
    return []


def wants_motion_phase_guides(request: dict[str, Any], states: dict[str, dict[str, Any]], cli_enabled: bool) -> bool:
    if "motion_phase_guides" in request:
        return bool(request["motion_phase_guides"])
    return cli_enabled or any(state_motion_phases(state, int(entry["frames"]), entry) for state, entry in states.items())


def compact_grid_dimensions(frames: int) -> tuple[int, int]:
    if frames <= 1:
        return 1, 1
    fixed = {
        2: (2, 1),
        3: (3, 1),
        4: (2, 2),
        5: (3, 2),
        6: (3, 2),
        7: (4, 2),
        8: (4, 2),
        9: (3, 3),
        10: (5, 2),
        11: (4, 3),
        12: (4, 3),
        16: (4, 4),
    }
    if frames in fixed:
        return fixed[frames]
    columns = max(1, math.ceil(math.sqrt(frames)))
    rows = math.ceil(frames / columns)
    return columns, rows


def raw_layout_grid(entry: dict[str, Any], frames: int) -> tuple[int, int]:
    raw = entry.get("raw_layout")
    if isinstance(raw, dict):
        columns = int(raw.get("columns", raw.get("cols", frames)))
        rows = int(raw.get("rows", 1))
        if columns > 0 and rows > 0:
            return columns, rows
    return frames, 1


def is_body_animation_row(request: dict[str, Any], state: str, entry: dict[str, Any], asset_kind: str) -> bool:
    if asset_kind != "sprite" or int(entry.get("frames", 0)) <= 3:
        return False
    descriptor = request_descriptor(request, state, entry)
    if any(word in descriptor for word in ("portrait", "avatar", "ui-avatar")):
        return False
    return True


def apply_raw_layout_policy(request: dict[str, Any], states: dict[str, dict[str, Any]], asset_kind: str) -> None:
    policy = str(request.get("raw_layout_policy", "compact-body-grids"))
    if policy in {"strip", "legacy-strip", "off"}:
        return
    for state, entry in states.items():
        frames = int(entry["frames"])
        if isinstance(entry.get("raw_layout"), dict):
            continue
        if is_body_animation_row(request, state, entry, asset_kind):
            columns, rows = compact_grid_dimensions(frames)
            entry["raw_layout"] = {
                "kind": "compact-grid" if rows > 1 else "strip",
                "columns": columns,
                "rows": rows,
                "order": "row-major",
                "delivery": "compose-runtime-row",
                "reason": "body-animation-anti-drift",
            }
        else:
            entry["raw_layout"] = {
                "kind": "strip",
                "columns": frames,
                "rows": 1,
                "order": "left-to-right",
                "delivery": "compose-runtime-row",
            }


def directional_parts(state: str) -> tuple[str, str] | None:
    match = re.search(r"-(front|back)-(left|right)$", state)
    if not match:
        return None
    return match.group(1), match.group(2)


def directional_requirements(state: str) -> list[str]:
    parts = directional_parts(state)
    if not parts:
        return []
    depth, side = parts
    toward = "toward the viewer" if depth == "front" else "away from the viewer"
    body_view = "three-quarter-front" if depth == "front" else "three-quarter-back"
    camera_side = f"camera-{side}"
    opposite_side = "left" if side == "right" else "right"
    requirements = [
        f"Lock the whole row to a 45-degree {body_view} view facing {camera_side} and slightly {toward}.",
        f"Do not average this into a straight front, straight back, or pure side-view sprite.",
        f"Make {camera_side} readable through face/body orientation, hair silhouette, shoulder overlap, hand/foot placement, and prop angle.",
        "If a 4-direction reference sheet is attached, use it as the direction SSoT for facing only; do not copy its pose or state.",
        "If a single target-direction anchor is attached, its facing direction is authoritative and overrides any paired-row reference.",
    ]
    if side == "left":
        requirements.append(
            f"If a generated {depth}-{opposite_side} basis row is attached, use it only for timing, scale, and pose-family consistency; change the facing to camera-left."
        )
    return requirements


def mirrored_x(center_x: int, x: int, facing: str) -> int:
    if facing == "left":
        return center_x - (x - center_x)
    return x


def leg_points(root: tuple[int, int], pose: str, facing: str, scale: float) -> tuple[tuple[int, int], tuple[int, int]]:
    root_x, root_y = root
    forward = round(34 * scale)
    back = round(32 * scale)
    down = round(54 * scale)
    bend = round(24 * scale)
    lift = round(22 * scale)
    if pose == "forward_straight":
        knee = (root_x + round(forward * 0.45), root_y + round(down * 0.48))
        foot = (root_x + forward, root_y + down)
    elif pose == "back_extended":
        knee = (root_x - round(back * 0.45), root_y + round(down * 0.48))
        foot = (root_x - back, root_y + down)
    elif pose == "under_bent":
        knee = (root_x + round(bend * 0.2), root_y + round(down * 0.45))
        foot = (root_x + round(bend * 0.55), root_y + round(down * 0.82))
    elif pose == "back_bent":
        knee = (root_x - round(bend * 0.65), root_y + round(down * 0.42))
        foot = (root_x - round(bend * 0.2), root_y + round(down * 0.78))
    elif pose == "passing_forward":
        knee = (root_x + round(bend * 0.45), root_y + round(down * 0.35))
        foot = (root_x + round(bend * 0.1), root_y + round(down * 0.63))
    elif pose == "under_vertical":
        knee = (root_x, root_y + round(down * 0.42))
        foot = (root_x, root_y + round(down * 0.88))
    elif pose == "forward_lifted":
        knee = (root_x + round(forward * 0.45), root_y + round(down * 0.18))
        foot = (root_x + round(forward * 0.7), root_y + round(down * 0.35))
    elif pose == "back_lifted":
        knee = (root_x - round(back * 0.45), root_y + round(down * 0.18))
        foot = (root_x - round(back * 0.7), root_y + round(down * 0.35))
    else:
        knee = (root_x, root_y + round(down * 0.45))
        foot = (root_x, root_y + down)
    if facing == "left":
        knee = (root_x - (knee[0] - root_x), knee[1])
        foot = (root_x - (foot[0] - root_x), foot[1])
    return knee, foot


def draw_motion_phase(
    draw: ImageDraw.ImageDraw,
    slot_left: int,
    slot_top: int,
    cell_width: int,
    cell_height: int,
    phase: dict[str, Any],
    facing: str,
) -> None:
    scale = min(cell_width / 192, cell_height / 208)
    center_x = slot_left + cell_width // 2
    hip_y = slot_top + round(cell_height * 0.52 + int(phase["body_y"]) * scale)
    shoulder_y = hip_y - round(42 * scale)
    head_y = shoulder_y - round(26 * scale)
    hip = (center_x, hip_y)
    shoulder = (center_x, shoulder_y)
    head_bbox = (
        center_x - round(11 * scale),
        head_y - round(11 * scale),
        center_x + round(11 * scale),
        head_y + round(11 * scale),
    )
    draw.ellipse(head_bbox, outline="#6b7280", width=max(1, round(2 * scale)))
    draw.line((shoulder, hip), fill="#6b7280", width=max(2, round(3 * scale)))
    front_arm = (mirrored_x(center_x, center_x - round(26 * scale), facing), shoulder_y + round(30 * scale))
    back_arm = (mirrored_x(center_x, center_x + round(26 * scale), facing), shoulder_y + round(18 * scale))
    draw.line((shoulder, front_arm), fill="#94a3b8", width=max(1, round(2 * scale)))
    draw.line((shoulder, back_arm), fill="#cbd5e1", width=max(1, round(2 * scale)))
    front_knee, front_foot = leg_points(hip, str(phase["front_leg"]), facing, scale)
    back_knee, back_foot = leg_points(hip, str(phase["back_leg"]), facing, scale)
    draw.line((hip, front_knee, front_foot), fill="#ef4444", width=max(2, round(4 * scale)))
    draw.line((hip, back_knee, back_foot), fill="#2563eb", width=max(2, round(4 * scale)))
    ground_y = slot_top + round(cell_height * 0.52 + 54 * scale + int(phase["body_y"]) * scale)
    draw.line((slot_left + round(34 * scale), ground_y, slot_left + cell_width - round(34 * scale), ground_y), fill="#cbd5e1", width=1)


def jump_arc_offset(frame_index: int, frames: int, safe_height: int, peak_ratio: float) -> int:
    if frames <= 1:
        return 0
    return round(math.sin(math.pi * frame_index / (frames - 1)) * safe_height * peak_ratio)


def smooth_progress(frame_index: int, frames: int) -> float:
    if frames <= 1:
        return 1.0
    progress = max(0.0, min(1.0, frame_index / (frames - 1)))
    return progress * progress * (3 - 2 * progress)


def pose_guide_height_ratio(pose_geometry: dict[str, Any], frame_index: int, frames: int) -> float:
    kind = str(pose_geometry.get("kind", ""))
    curve = str(pose_geometry.get("height_curve", ""))
    if kind == "crouch" or curve == "compress":
        start_ratio = float(pose_geometry.get("start_height_vs_reference", 1.0))
        target_ratio = float(pose_geometry.get("guide_height_ratio", pose_geometry.get("target_height_vs_reference", 0.70)))
        max_ratio = float(pose_geometry.get("max_height_vs_reference", 1.05))
        progress = smooth_progress(frame_index, frames)
        return min(max_ratio, start_ratio + (target_ratio - start_ratio) * progress)
    return float(pose_geometry.get("guide_height_ratio", pose_geometry.get("target_height_ratio", 0.74)))


def pose_bottom_y(pose_geometry: dict[str, Any], frame_index: int, frames: int, cell_height: int, safe_margin_y: int) -> int:
    safe_height = cell_height - safe_margin_y * 2
    baseline_y = cell_height - safe_margin_y
    kind = str(pose_geometry.get("kind", ""))
    if kind == "jump":
        peak_ratio = float(pose_geometry.get("arc_peak_ratio", 0.22))
        return baseline_y - jump_arc_offset(frame_index, frames, safe_height, peak_ratio)
    if kind == "fall":
        return baseline_y - round(safe_height * float(pose_geometry.get("airborne_bottom_ratio", 0.18)))
    return baseline_y


def draw_pose_geometry(
    draw: ImageDraw.ImageDraw,
    slot_left: int,
    slot_top: int,
    frame_index: int,
    frames: int,
    cell_width: int,
    cell_height: int,
    safe_margin_x: int,
    safe_margin_y: int,
    pose_geometry: dict[str, Any],
) -> None:
    safe_height = cell_height - safe_margin_y * 2
    baseline_y = slot_top + cell_height - safe_margin_y
    bottom_y = slot_top + pose_bottom_y(pose_geometry, frame_index, frames, cell_height, safe_margin_y)
    target_height = round(safe_height * pose_guide_height_ratio(pose_geometry, frame_index, frames))
    top_y = max(slot_top + safe_margin_y, bottom_y - target_height)
    left = slot_left + safe_margin_x
    right = slot_left + cell_width - safe_margin_x
    center_x = slot_left + cell_width // 2
    draw.line((left, baseline_y, right, baseline_y), fill="#f59e0b", width=1)
    draw.rectangle((left, top_y, right, bottom_y), outline="#f59e0b", width=1)
    draw.line((center_x, top_y, center_x, bottom_y), fill="#fbbf24", width=1)


def entry_asset_labels(entry: dict[str, Any]) -> list[str]:
    for key in ("labels", "asset_labels", "asset_names"):
        raw = entry.get(key)
        if isinstance(raw, list):
            return [str(item) for item in raw]
    return []


def isometric_slot_pivot(
    request: dict[str, Any],
    entry: dict[str, Any] | None,
    frame_index: int,
    cell_width: int,
    cell_height: int,
    safe_margin_y: int,
) -> tuple[int, int]:
    catalog = request.get("asset_catalog") if isinstance(request.get("asset_catalog"), dict) else {}
    items = catalog.get("items") if isinstance(catalog.get("items"), dict) else {}
    labels = entry_asset_labels(entry or {})
    if frame_index < len(labels):
        meta = items.get(labels[frame_index], {})
        raw = meta.get("pivot") if isinstance(meta, dict) else None
        if isinstance(raw, list) and len(raw) == 2:
            return round(float(raw[0])), round(float(raw[1]))
    return cell_width // 2, cell_height - safe_margin_y


def isometric_tile_size(request: dict[str, Any], cell_width: int, cell_height: int, safe_margin_x: int, safe_margin_y: int) -> tuple[int, int]:
    catalog = request.get("asset_catalog") if isinstance(request.get("asset_catalog"), dict) else {}
    tile = catalog.get("tile") if isinstance(catalog.get("tile"), dict) else {}
    width = int(tile.get("width", 0)) if isinstance(tile, dict) else 0
    height = int(tile.get("height", 0)) if isinstance(tile, dict) else 0
    if width > 0 and height > 0:
        return width, height
    width = min(cell_width - safe_margin_x * 2, (cell_height - safe_margin_y * 2) * 2)
    width = max(2, width - (width % 2))
    return width, max(1, width // 2)


def draw_isometric_slot_guide(
    draw: ImageDraw.ImageDraw,
    request: dict[str, Any],
    entry: dict[str, Any] | None,
    frame_index: int,
    slot_left: int,
    slot_top: int,
    cell_width: int,
    cell_height: int,
    safe_margin_x: int,
    safe_margin_y: int,
) -> None:
    tile_w, tile_h = isometric_tile_size(request, cell_width, cell_height, safe_margin_x, safe_margin_y)
    px, py = isometric_slot_pivot(request, entry, frame_index, cell_width, cell_height, safe_margin_y)
    cx = slot_left + px
    py = slot_top + py
    cy = py - tile_h / 2
    points = [
        (cx, cy - tile_h / 2),
        (cx + tile_w / 2, cy),
        (cx, cy + tile_h / 2),
        (cx - tile_w / 2, cy),
    ]
    draw.polygon(points, outline="#10b981")
    draw.line((cx - 6, py, cx + 6, py), fill="#ef4444", width=1)
    draw.line((cx, py - 6, cx, py + 6), fill="#ef4444", width=1)
    draw.line((slot_left + safe_margin_x, py, slot_left + cell_width - safe_margin_x, py), fill="#f97316", width=1)


def draw_guide(
    path: Path,
    state: str,
    frames: int,
    cell: dict[str, Any],
    request: dict[str, Any],
    motion_phase_guides: bool = False,
    entry: dict[str, Any] | None = None,
    pose_geometry: dict[str, Any] | None = None,
    isometric_guides: bool = False,
) -> None:
    cell_width = int(cell["width"])
    cell_height = int(cell["height"])
    safe_margin_x = int(cell["safe_margin_x"])
    safe_margin_y = int(cell["safe_margin_y"])
    columns, rows = raw_layout_grid(entry or {}, frames)
    width = columns * cell_width
    height = rows * cell_height
    image = Image.new("RGB", (width, height), "#f6f6f6")
    draw = ImageDraw.Draw(image)
    for index in range(frames):
        column = index % columns
        row = index // columns
        left = column * cell_width
        top = row * cell_height
        right = left + cell_width - 1
        bottom = top + cell_height - 1
        draw.rectangle((left, top, right, bottom), outline="#333333", width=3)
        safe = (
            left + safe_margin_x,
            top + safe_margin_y,
            right - safe_margin_x,
            bottom - safe_margin_y,
        )
        draw.rectangle(safe, outline="#2f80ed", width=2)
        draw.line((left + cell_width // 2, top + safe_margin_y, left + cell_width // 2, bottom + 1 - safe_margin_y), fill="#b8c8e8", width=1)
        if pose_geometry:
            draw_pose_geometry(draw, left, top, index, frames, cell_width, cell_height, safe_margin_x, safe_margin_y, pose_geometry)
        if isometric_guides:
            draw_isometric_slot_guide(draw, request, entry, index, left, top, cell_width, cell_height, safe_margin_x, safe_margin_y)
    if motion_phase_guides:
        phases = state_motion_phases(state, frames, entry)
        facing = "left" if state.endswith("left") else "right"
        for index, phase in enumerate(phases):
            column = index % columns
            row = index // columns
            draw_motion_phase(draw, column * cell_width, row * cell_height, cell_width, cell_height, phase, facing)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def row_prompt(request: dict[str, Any], state: str, entry: dict[str, Any]) -> str:
    cell = request["cell"]
    chroma = request["chroma_key"]
    character = request["character"]
    asset_kind = str(request.get("asset_kind", "sprite"))
    is_sprite = asset_kind == "sprite"
    frames = int(entry["frames"])
    cell_width = int(cell["width"])
    cell_height = int(cell["height"])
    safe_margin_x = int(cell["safe_margin_x"])
    safe_margin_y = int(cell["safe_margin_y"])
    layout_columns, layout_rows = raw_layout_grid(entry, frames)
    layout_is_grid = layout_rows > 1 or layout_columns != frames
    layout_name = "compact sprite grid" if is_sprite and layout_is_grid else ("compact asset grid" if layout_is_grid else ("sprite strip" if is_sprite else f"{asset_kind} strip"))
    layout_shape = (
        f"{layout_rows} rows by {layout_columns} columns in row-major order"
        if layout_is_grid
        else f"one left-to-right row of {frames} slots"
    )
    layout_delivery_note = (
        "The final runtime atlas will be assembled later; this raw generation must use the compact grid layout to reduce long-row drift."
        if layout_is_grid
        else "The final runtime atlas will use this same left-to-right frame order."
    )
    state_requirements = [*directional_requirements(state)] if is_sprite else []
    if is_sprite and is_locomotion_state(state, entry):
        state_requirements.extend(LOCOMOTION_REQUIREMENTS)
    if is_sprite:
        state_requirements.extend(STATE_REQUIREMENTS.get(state, []))
    pose_geometry = state_pose_geometry(state, entry) if is_sprite else None
    production_requirements = professional_requirements_for_row(request, state, entry, asset_kind)
    production_requirement_text = "\n\nProfessional production requirements:\n" + "\n".join(
        f"- {requirement}" for requirement in production_requirements
    )
    active_profile_ids = active_art_profiles(request, state, entry, asset_kind)
    art_requirements = art_direction_requirements_for_row(request, state, entry, asset_kind)
    art_direction_text = ""
    if art_requirements:
        active_profiles = ", ".join(active_profile_ids)
        art_direction_text = (
            f"\n\nPixel-art direction profiles: {active_profiles}.\n"
            "Use these as production constraints and critique lenses, not as a request to copy a specific artist.\n"
            + "\n".join(f"- {requirement}" for requirement in art_requirements)
        )
    workflow_requirements = animation_workflow_requirements_for_row(request, state, entry, asset_kind)
    animation_workflow_text = ""
    if workflow_requirements:
        active_workflows = ", ".join(active_animation_workflows(request, state, entry, asset_kind))
        animation_workflow_text = (
            f"\n\nAnimation workflow requirements: {active_workflows}.\n"
            "Use these as row-specific phase and playback constraints. Preserve the user's subject and gameplay intent.\n"
            + "\n".join(f"- {requirement}" for requirement in workflow_requirements)
        )
    state_requirement_text = ""
    if state_requirements:
        state_requirement_text = "\n\nState-specific requirements:\n" + "\n".join(
            f"- {requirement}" for requirement in state_requirements
        )
    phase_prompt_text = ""
    phases = state_motion_phases(state, frames, entry) if is_sprite and request.get("motion_phase_guides") else []
    if phases:
        phase_lines = [
            f"- frame {index + 1}: {phase['name']} - {phase['note']}"
            for index, phase in enumerate(phases)
        ]
        phase_prompt_text = (
            "\n\nMotion phase requirements:\n"
            "- The layout guide includes simple stick-pose motion hints inside each slot. Use those hints only for body height, foot contact, and leg phase. Do not copy guide colors or guide lines into the artwork.\n"
            "- Make the sequence loop as one continuous locomotion cycle, not eight unrelated poses.\n"
            "- The motion phase guide and any multi-pose contact sheet override a single running/walking pose anchor for leg phase. Do not repeat one anchor's forward leg across every frame.\n"
            "- Opposite contact frames must visibly trade which leg reaches forward; passing frames must not look like duplicate contact frames.\n"
            "- If the character has tiny legs, exaggerated feet, or non-human limbs, still alternate contact side, body weight, and swing timing. Never keep both feet leaning the same way for every frame.\n"
            + "\n".join(phase_lines)
        )
    frame_economy_text = ""
    if is_sprite and frames <= 3:
        frame_economy_text = (
            "\n\nLow-frame animation requirements:\n"
            "- Treat this as deliberate limited animation, not a failed full cycle.\n"
            "- With 2 frames, use two readable extremes: idle up/down, blink open/closed, hit before/after, or attack start/impact.\n"
            "- With 3 frames, use clear key poses: anticipation, action, recovery; or contact, passing, contact for tiny locomotion.\n"
            "- Do not add fake motion blur or detached streaks to compensate for low frame count."
        )
    elif is_sprite and frames == 4:
        frame_economy_text = (
            "\n\nCompact animation requirements:\n"
            "- Use four distinct key poses. Keep timing readable and loopable, but do not pretend this has the smoothness of a 6-8 frame cycle.\n"
            "- For locomotion, make contact and passing poses visibly alternate."
        )
    pose_geometry_text = ""
    if pose_geometry:
        kind = str(pose_geometry.get("kind", "pose"))
        if kind == "crouch":
            pose_geometry_text = (
                "\n\nPose scale and placement requirements:\n"
                "- Camera distance and character scale are locked to the accepted idle/direction anchor. Do not zoom in to fill the crouch slot.\n"
                "- Feet stay on the shared baseline. The crouch reads as a lower compressed body, not a larger head/torso.\n"
                "- The first crouch frame may begin near standing height, then each later frame should compress lower until the final crouched key pose is roughly 65-75% of idle height.\n"
                "- Crouch frames preserve the same outline weight, face size, head scale, hand/foot scale, limb thickness, and costume scale; only body pose and vertical height change.\n"
                "- Do not make the final crouch a uniformly smaller whole character. Knees bend, torso lowers, and the silhouette may widen, but the character scale remains locked.\n"
                "- The layout guide includes an orange baseline and per-frame target pose boxes. Use them only for scale and placement; do not draw them."
            )
        elif kind == "jump":
            pose_geometry_text = (
                "\n\nPose scale and placement requirements:\n"
                "- Camera distance and character scale are locked to the accepted idle/direction anchor. The airborne body must not become larger than idle.\n"
                "- Show the jump by moving the same-sized body vertically through the slot: anticipation on the baseline, airborne frames higher, return toward the baseline.\n"
                "- Do not stretch, zoom, shrink, or enlarge the character at the jump peak. Keep head, face, hands, torso, limbs, outline weight, and props at the same runtime scale.\n"
                "- The layout guide includes an orange baseline and arc pose boxes. Use them only for scale and placement; do not draw them."
            )
        elif kind == "fall":
            pose_geometry_text = (
                "\n\nPose scale and placement requirements:\n"
                "- Camera distance and character scale are locked to the accepted idle/direction anchor. Falling changes vertical placement, not sprite size.\n"
                "- Keep the same full-body scale as idle/jump rows, with the body airborne inside the slot and no floor shadow or impact mark.\n"
                "- The layout guide includes an orange airborne pose box. Use it only for scale and placement; do not draw it."
            )
        elif kind == "knockdown":
            pose_geometry_text = (
                "\n\nPose scale and placement requirements:\n"
                "- Camera distance and character scale are locked to the accepted idle/direction anchor. Knockdown changes pose and orientation, not camera zoom.\n"
                "- Show loss of balance, collapse, and final down pose with the same head, limb, outline, and costume scale as idle.\n"
                "- The body may become much lower and wider because it is falling or grounded, but it must not become a tiny uniformly scaled-down character."
            )
        elif kind == "land":
            pose_geometry_text = (
                "\n\nPose scale and placement requirements:\n"
                "- Camera distance and character scale are locked to the accepted idle/direction anchor. Landing compresses the pose without enlarging the character.\n"
                "- Feet return to the shared baseline; knees/body may compress, but the head/torso must not inflate to fill the slot.\n"
                "- The layout guide includes an orange baseline and pose box. Use it only for scale and placement; do not draw it."
            )
    isometric_asset_text = ""
    if not is_sprite and "pixel-isometric" in active_profile_ids:
        catalog = request.get("asset_catalog") if isinstance(request.get("asset_catalog"), dict) else {}
        tile = catalog.get("tile") if isinstance(catalog.get("tile"), dict) else {}
        footprint = f'{tile.get("width", "declared")}x{tile.get("height", "declared")}' if tile else "the declared 2:1 footprint"
        runtime_cell = tile.get("runtimeCell") or tile.get("runtime_cell") or [cell_width, cell_height] if tile else [cell_width, cell_height]
        isometric_asset_text = (
            "\n\nIsometric slot requirements:\n"
            f"- Treat each invisible slot as runtime cell {runtime_cell}; the visual floor/contact footprint is {footprint}, not the full rectangle.\n"
            "- The layout guide shows a green 2:1 diamond and red floor/contact pivot. Use it only to align the tile or object; do not draw the guide.\n"
            "- Place terrain so the bottom point of the diamond sits on the pivot. Place props/buildings so their ground-contact point sits on the same pivot.\n"
            "- Do not center by the rectangular image cell, do not make a full scene, and do not let shadows or silhouettes cross slot borders.\n"
            "- Leave enough transparent/chroma padding above and around tall geometry while keeping the contact point stable."
        )
    transparency_artifact_text = "\n".join(f"- {rule}" for rule in (TRANSPARENCY_ARTIFACT_RULES if is_sprite else ASSET_ARTIFACT_RULES))
    runtime_size = f"{cell_width}x{cell_height}"
    if is_sprite:
        reference_contract = (
            "Use the attached accepted idle/direction anchor as the canonical character design for this row. "
            "If a state anchor is attached for a non-locomotion state, treat it as approved state vocabulary only. "
            "Use the attached layout guide image only for frame count, slot spacing, centering, scale, baseline/airborne placement, and safe padding. "
            "If an additional generated row strip is attached, use it only as a motion reference, never as a replacement identity source. "
            "Do not simply copy the still reference pose. Generate distinct animation poses that create a readable cycle or action."
        )
    else:
        reference_contract = (
            "Use attached references as approved art direction for palette, material language, projection, scale, and silhouette vocabulary. "
            "Use the attached layout guide image only for slot count, spacing, centering, and safe padding. "
            "Do not copy the guide, labels, or boxes into the artwork. Do not turn the row into a preview scene or catalog page."
        )
    if is_sprite and character.get("base_image"):
        reference_contract = (
            "If this is a pre-idle/simple run, the attached base image may be used as the canonical character design. "
            "In direction-anchor mode, do not use base images for final action rows; accepted idle/direction anchors own row identity. "
            + reference_contract
        )
    style_preset = request.get("style_preset", STYLE_DEFAULT_PRESET)
    style_notes = STYLE_PRESETS.get(style_preset, STYLE_PRESETS["custom"])
    frame_noun = {
        "tileset": "tile",
        "texture": "tileable texture sample",
        "asset": "asset",
        "prop": "prop",
        "props": "prop",
        "icon": "icon",
        "ui": "UI icon",
        "vfx": "effect frame",
    }.get(asset_kind, "asset")
    strip_noun = layout_name
    subject_noun = "game character" if is_sprite else f"{asset_kind} asset pack"
    subject_label = "Character" if is_sprite else "Asset pack"
    production_label = "sprite-production" if is_sprite else f"{asset_kind}-production"
    style_contract = str(request["style"]).rstrip(".")
    rendering_note = style_notes["rendering"] if is_sprite else {
        "tileset": "Keep the rendering tilemap-ready: consistent scale, projection, palette, edge logic, and runtime readability.",
        "texture": "Keep each sample material-focused and tileable; avoid perspective scenes, baked labels, and hero objects.",
        "asset": "Keep every asset game-ready: consistent scale, readable silhouette, compatible palette, and clean runtime isolation.",
        "prop": "Keep every prop game-ready: readable silhouette, consistent scale, compatible palette, and clean runtime isolation.",
        "props": "Keep every prop game-ready: readable silhouette, consistent scale, compatible palette, and clean runtime isolation.",
        "icon": "Keep every icon crisp, centered, readable at runtime size, and visually consistent with the set.",
        "ui": "Keep every UI icon crisp, centered, readable at runtime size, and visually consistent with the set.",
        "vfx": "Keep every effect frame readable, self-contained, and alpha-friendly for runtime compositing.",
    }.get(asset_kind, "Keep every asset readable at runtime size, centered, and visually consistent with the set.")
    anchor_block = f"""Anchor lock:
- Accepted idle/direction anchors own character identity, outfit details, colors, face design, asymmetric markings, and side-specific accessories for final action rows.
- Base character images and original character sheets are pre-idle sources only. Do not reinterpret or reintroduce base-character details inside a direction-anchor action row.
- This row owns motion only. Spend the variation budget on limb contacts, arm counter-swing, body height, torso lean, head bob, hair bounce, and loop continuity.
- Do not redesign or reinterpret identity details while animating. Keep face, hair shape, markings, palette, outline weight, body proportions, outfit, props, and silhouette copied from the approved anchors.
- Preserve side-specific features exactly as the approved anchors show them. Do not solve hairpin side, earring side, logos, handed props, scars, one-sided markings, asymmetric clothing, or lighting cues from scratch inside the row.
- When generating a paired left/right row, use the paired row reference only for timing, scale, and animation intensity. Rotate the body, feet, shoulders, face angle, and gaze to the target facing, but keep identity details attached according to the accepted target-direction anchor.
- For cyclic locomotion, do not let a single running/walking pose anchor determine every frame's leg phase. Use multi-pose motion references and the layout phase guide for foot contacts.
- Prefer a subtler animation over any change that mutates the character identity."""
    if not is_sprite:
        anchor_block = f"""Asset consistency:
- Keep palette, outline weight, material language, projection, lighting direction, and runtime scale consistent across the row.
- This row owns variation only. Do not redesign the pack identity from slot to slot.
- Each slot is one separate {frame_noun}; do not make a scene, collage, menu, catalog page, or labeled reference board.
- For tiles/textures, preserve grid alignment and edge compatibility. For props/icons/VFX, preserve clean isolation and readable silhouette."""
    slot_fill = "complete full-body pose" if is_sprite else f"complete {frame_noun}"
    clip_text = "No character body part should be clipped by the frame slot." if is_sprite else "No asset edge should be accidentally clipped unless the row is explicitly a full-cell tile or seamless texture."
    preserve_text = "Preserve the same silhouette, face, proportions, palette, material, and props across every frame." if is_sprite else "Preserve set-level palette, projection, material logic, scale, and edge treatment across every slot."
    return f"""Create a single {strip_noun} for the {subject_noun} `{character["id"]}` in the state `{state}`.

{reference_contract}

{subject_label}: {character.get("description") or character["id"]}.
Asset kind: {asset_kind}.
Style preset: {style_preset}.
Style contract: {style_contract}.

Use this prompt as an authoritative {production_label} spec. {style_notes["avoid"]}

Row action: {entry["action"]}.

{anchor_block}
{production_requirement_text}
{art_direction_text}
{animation_workflow_text}
{state_requirement_text}
{phase_prompt_text}
{frame_economy_text}
{pose_geometry_text}
{isometric_asset_text}

Transparency and artifact rules:
{transparency_artifact_text}

Layout requirements:
- Exactly {frames} {slot_fill}s arranged as {layout_shape}.
- Use row-major order: fill the first row left-to-right, then the next row left-to-right until all requested frames are present.
- {layout_delivery_note}
- The attached layout guide shows the {frames} frame boxes, inner safe area, optional orange pose scale/baseline boxes, and optional motion phase hints for this layout. Follow its slot count, spacing, centering, scale, padding, baseline/airborne placement, and phase timing.
- Do not reproduce the layout guide itself: no visible boxes, guide lines, center marks, labels, stick figures, guide colors, or guide background may appear in the output.
- Treat the image as {frames} equal-width invisible {runtime_size} frame slots. Fill every slot: each requested slot must contain exactly one {slot_fill}.
- Spread the {frames} items evenly across the declared layout. Do not leave any requested slot blank or create large empty gaps between slots.
- Center one {slot_fill} in each slot. No item may cross into the neighboring slot.
- Use a perfectly flat pure {chroma["name"]} {chroma["hex"]} chroma-key background across the whole image.
- Do not use {chroma["hex"]}, pure {chroma["name"]}, or chroma-adjacent colors in the artwork, highlights, props, shadows, or effects.
- {rendering_note}
- Keep every frame self-contained with at least {safe_margin_x} px horizontal and {safe_margin_y} px vertical safe padding. {clip_text}
- Avoid motion blur. Use clear pose changes readable at {runtime_size}.
- {preserve_text}

Output only the sheet image."""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--character-id", required=True)
    parser.add_argument("--base-image", type=Path)
    parser.add_argument("--description", default="")
    parser.add_argument("--asset-kind", default=None)
    parser.add_argument("--style-preset", default=STYLE_DEFAULT_PRESET, choices=sorted(STYLE_PRESETS))
    parser.add_argument("--style", default=None)
    parser.add_argument("--cell-size", type=int, default=256)
    parser.add_argument("--cell-width", type=int)
    parser.add_argument("--cell-height", type=int)
    parser.add_argument("--safe-margin", type=int, default=24)
    parser.add_argument("--chroma-key", default="auto", help="auto or #RRGGBB")
    parser.add_argument("--extraction-mode", choices=["components", "slots"], default=None)
    parser.add_argument("--background-removal", choices=sorted(BACKGROUND_REMOVAL_METHODS), default=None)
    parser.add_argument("--background-model", default=None, help=f"model name; rembg default {DEFAULT_REMBG_MODEL}; ben2 default {DEFAULT_BEN2_MODEL}")
    parser.add_argument("--background-device", default=None, help="model-backed background removal device: auto, cpu, cuda, cuda:0, etc.")
    parser.add_argument("--alpha-matting", dest="alpha_matting", action="store_true", default=None)
    parser.add_argument("--no-alpha-matting", dest="alpha_matting", action="store_false")
    parser.add_argument("--motion-phase-guides", action="store_true", help="draw simple per-frame motion phase hints into locomotion layout guides")
    parser.add_argument("--art-direction", choices=sorted(ART_DIRECTION_MODES), default=None, help="add Pixel-art direction or disable it")
    parser.add_argument("--art-profile", action="append", choices=sorted(ART_PROFILE_CHOICES), help="repeatable Pixel-art profile id; use auto for inferred profiles")
    parser.add_argument("--request", type=Path)
    parser.add_argument("--request-json")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    out_dir = args.out_dir.expanduser().resolve()
    if out_dir.exists() and any(out_dir.iterdir()) and not args.force:
        raise SystemExit(f"output dir exists and is not empty: {out_dir}; pass --force")

    raw_request = load_request(args.request, args.request_json)
    declared_kind = raw_request.get("kind")
    if declared_kind is not None and declared_kind != "sprite-gen-request":
        raise SystemExit(f"request kind must be 'sprite-gen-request', got {declared_kind!r}")
    if "kind" in raw_request or "version" in raw_request:
        try:
            raw_request = normalize_contract(raw_request, expected_kind="sprite-request").to_dict()
        except ContractError as exc:
            raise SystemExit(str(exc)) from exc
    states = normalize_states(raw_request.get("states"))
    raw_cell = dict(raw_request.get("cell", {}))
    if args.cell_width is not None:
        raw_cell["width"] = args.cell_width
    if args.cell_height is not None:
        raw_cell["height"] = args.cell_height
    cell = normalize_cell(raw_cell, args.cell_size, args.safe_margin)

    base_source = args.base_image.expanduser().resolve() if args.base_image else None
    if base_source is not None and not base_source.is_file():
        raise SystemExit(f"missing base image: {base_source}")

    base_dest_name = f"base-source{base_source.suffix.lower() or '.png'}" if base_source else None
    chroma_key = choose_chroma_key(base_source, args.chroma_key)
    style_preset = str(raw_request.get("style_preset") or args.style_preset)
    if style_preset not in STYLE_PRESETS:
        raise SystemExit(f"unknown style_preset {style_preset!r}; choices: {', '.join(sorted(STYLE_PRESETS))}")
    if raw_request.get("style"):
        style = raw_request["style"]
    elif args.style:
        style = args.style
        if "style_preset" not in raw_request and args.style_preset == STYLE_DEFAULT_PRESET:
            style_preset = "custom"
    else:
        style = STYLE_PRESETS[style_preset]["contract"]
    asset_kind = str(raw_request.get("asset_kind") or args.asset_kind or "sprite")
    requested_extraction_mode = raw_request.get("extraction_mode") or args.extraction_mode
    extraction_mode = str(requested_extraction_mode or ("components" if asset_kind == "sprite" else "slots"))
    if extraction_mode not in {"components", "slots"}:
        raise SystemExit("extraction_mode must be components or slots")
    art_direction = normalize_art_direction(raw_request, args, asset_kind, style_preset)
    if asset_kind == "sprite":
        for state, entry in states.items():
            pose_geometry = state_pose_geometry(state, entry)
            if pose_geometry:
                entry["pose_geometry"] = pose_geometry

    request = {
        "version": 1,
        "kind": "sprite-gen-request",
        "engine": "component-row",
        "asset_kind": asset_kind,
        "extraction_mode": extraction_mode,
        "character": {
            "id": args.character_id,
            "description": args.description,
            "base_image": base_dest_name,
        },
        "cell": cell,
        "chroma_key": chroma_key,
        "background_removal": normalize_background_removal(raw_request, args, asset_kind, extraction_mode),
        "states": states,
        "style_preset": style_preset,
        "style": style,
        "motion_phase_guides": wants_motion_phase_guides(raw_request, states, args.motion_phase_guides),
        "art_direction": art_direction,
        "raw_layout_policy": str(raw_request.get("raw_layout_policy", "compact-body-grids")),
    }
    for key in (
        "preset",
        "output",
        "frame_budget",
        "asset_catalog",
        "iso",
        "tile",
        "projection",
        "frame_semantics",
        "sampling_policy",
    ):
        if key in raw_request:
            request[key] = raw_request[key]
    apply_raw_layout_policy(request, states, asset_kind)
    try:
        request = normalize_contract(request, expected_kind="sprite-request").to_dict()
    except ContractError as exc:
        raise SystemExit(str(exc)) from exc
    validate_isometric_catalog_contract(request)

    try:
        create_run_marker(out_dir, run_id=args.character_id)
        acquire_run_dir_lock(out_dir, "prepare_sprite_run")
        if out_dir.exists() and any(out_dir.iterdir()) and args.force:
            known_outputs = list(PREPARE_KNOWN_OUTPUTS)
            known_outputs.extend(path.name for path in out_dir.glob("base-source.*") if path.is_file())
            remove_known_outputs(out_dir, known_outputs)
    except PathSafetyError as exc:
        raise SystemExit(str(exc)) from exc

    if base_source is not None and base_dest_name is not None:
        shutil.copy2(base_source, out_dir / base_dest_name)

    references = out_dir / "references" / "layout-guides"
    reference_root = out_dir / "references"
    prompts = out_dir / "prompts"
    raw = out_dir / "raw"
    frames = out_dir / "frames"
    for directory in (reference_root, references, prompts, raw, frames):
        directory.mkdir(parents=True, exist_ok=True)

    for state, entry in states.items():
        draw_guide(
            references / f"{state}.png",
            state,
            int(entry["frames"]),
            cell,
            request,
            motion_phase_guides=bool(request["motion_phase_guides"]),
            entry=entry,
            pose_geometry=state_pose_geometry(state, entry) if asset_kind == "sprite" else None,
            isometric_guides=asset_kind != "sprite" and "pixel-isometric" in active_art_profiles(request, state, entry, asset_kind),
        )
        (prompts / f"{state}.txt").write_text(row_prompt(request, state, entry).rstrip() + "\n", encoding="utf-8")

    (reference_root / "art-direction.json").write_text(
        json.dumps(art_direction_summary(request, states, asset_kind), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    (out_dir / "sprite-request.json").write_text(
        json.dumps(request, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(json.dumps({"ok": True, "run_dir": str(out_dir), "states": list(states)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
