# Creature Animation Contract

For non-human creatures, frontal retro-FPS enemies, compact `2x2` cycles, and anatomy-specific registration.

## Request Contract

Declare motion before generation:

```json
{
  "creature_motion": {
    "anatomy": "biped",
    "locomotion": "walk",
    "camera": "front-fps",
    "registration_anchor": "body-bottom",
    "shared_idle": true,
    "screen_side_labels": true,
    "movement_source": "alternating legs with opposite arm swing",
    "attack_source": "both hands",
    "preserve": ["head size", "torso volume", "frontal face"],
    "reject": ["three-quarter view", "side sway", "one-hand generic strike"]
  }
}
```

Use `screen_side_labels: true` for frontal work. Name the advancing screen-side limb in each active frame.

## Anatomy Rules

| Anatomy | Movement source | Stable anchor | Reject |
| --- | --- | --- | --- |
| Biped | Full alternating steps + opposite arm swing | `body-bottom` or `footprint` | Knee-only motion, repeated lead foot, torso flattening |
| Quadruped | Declared support groups + weight transfer | `footprint` or `body-bottom` | Side sway, mirrored two-leg pose |
| Multi-legged | Declared diagonal or alternating leg groups | `body-bottom` | One moving leg, one moving side, alignment from a leg tip |
| Winged | Coordinated bilateral wing phases | `center` | One-wing alternation, static wings, body shrink |
| Hovering | Shroud, tendrils, vapor, or lower-body pulse | `center` | Terrestrial steps, whole-body side sway |
| Amorphous | Localized folds, waves, or contractions | `body-bottom` or `center` | Fake biped steps, mirrored tail motion, mass loss |
| Serpentine | Propagated body wave | `body-bottom` or `center` | Humanoid lean, detached head motion |
| Custom | Declared movement and attack anatomy | Project runtime anchor | Generic biped or one-hand defaults |

## Compact Four-Frame Cycles

One coherent `2x2` Imagegen sheet per state.

- Movement: exact idle, phase A, exact idle, phase B.
- Attack: exact idle, anticipation, active contact, exact idle.
- Phases A and B must be mechanically different. Do not mirror one static pose.
- Copy accepted idle pixels into each neutral slot before final registration.
- Keep the body at one camera scale. Perspective can enlarge only the part that approaches the viewer.

Generate complete active sprites separately only after a whole-sheet attempt repeatedly changes identity. Record the reason. Never paste a local limb or body-part patch that creates a visible seam.

## Video Prompt Contract

First-frame-to-video: provider prompt must include all of these before inference:

- exact creature anatomy and locomotion family;
- the only allowed movement or attack driver from `creature_motion`;
- full-frontal camera, fixed center, fixed ground line or hover center, and fixed pixel scale;
- same flat image plane by default; threat comes from pose, not zoom or foreshortening;
- one complete readable action early in the video, with exact idle recovery;
- the existing empty border stays visible and every appendage remains inside source bounds;
- exact identity, face topology, limb count, body volume, weapon, palette, marks, and lighting remain unchanged.

Reject missing `movement_source` for locomotion and missing `attack_source` for attacks. Do not let a generic provider prompt guess the creature's movement family.

## Attack Design

Select the weapon before generation: teeth, jaws, horns, head, claws, wings, forelimbs, tendrils, body mass, or held weapons when appropriate.

Do not default every creature to a right-hand strike. Anticipation and contact must use creature-specific anatomy.

## Background And Segmentation

Black by default for creature grids. Gray or white when the creature loses contrast against black. White-eyed or shadow creatures often need neutral gray.

Run Lucida before adaptive segmentation. Review variable source boxes before registration. A fixed `2x2` layout defines frame order, not one fixed crop size.

## Registration

Read the runtime cell and pivot from the game. Do not infer them from the generated sheet.

- `bbox-bottom` only for a stable lowest contact.
- `body-bottom` when feet, claws, or appendages change their lowest extent.
- `center` for hovering or winged bodies with a stable core.
- `footprint` when the ground-contact area is the gameplay anchor.

Inspect `qa/registration-overlay.png` and each onion sheet. Correct body drift. Do not remove intentional attack or step motion.

## QA Protocol

Review before approval:

- Matte board and adaptive segmentation.
- Contact sheet in chronological order.
- Onion skin with baseline and body center.
- Runtime playback from `manifest.json.frame_layout`.
- Identity report and the accepted idle at runtime size.

Identity proxies can include raised arms, wings, or weapons inside a head or torso band.

Keep the standard failure report. If visual evidence proves stable identity, run a pose-aware comparison and record its thresholds. Do not widen thresholds to hide visible scale drift.

Record every rejection and accepted run in a creature decision ledger. Read that entry before another regeneration.

Video-derived rows: review the whole video first, then all decoded frames, several candidate sequences, and the final selected frames at full source size. Run Lucida only after those semantic checks pass.
