# Creature Animation Contract

Use this reference for non-human creatures, frontal retro-FPS enemies, compact `2x2` cycles, and anatomy-specific registration.

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
| Biped | Complete alternating steps and opposite arm swing | `body-bottom` or `footprint` | Knee-only motion, repeated lead foot, torso flattening |
| Quadruped | Declared support groups and weight transfer | `footprint` or `body-bottom` | Side sway, mirrored two-leg pose |
| Multi-legged | Declared diagonal or alternating leg groups | `body-bottom` | One moving leg, one moving side, alignment from a leg tip |
| Winged | Coordinated bilateral wing phases | `center` | One-wing alternation, static wings, body shrink |
| Hovering | Shroud, tendrils, vapor, or lower-body pulse | `center` | Terrestrial steps, whole-body side sway |
| Amorphous | Localized folds, waves, or contractions | `body-bottom` or `center` | Fake biped steps, mirrored tail motion, mass loss |
| Serpentine | Propagated body wave | `body-bottom` or `center` | Humanoid lean, detached head motion |
| Custom | Declared movement and attack anatomy | Project runtime anchor | Generic biped or one-hand defaults |

## Compact Four-Frame Cycles

Use one coherent `2x2` Imagegen sheet for each state.

- Movement: exact idle, phase A, exact idle, phase B.
- Attack: exact idle, anticipation, active contact, exact idle.
- Make phases A and B mechanically different. Do not mirror one static pose.
- Copy the accepted idle pixels into each neutral slot before final registration.
- Keep the body at one camera scale. Perspective can enlarge only the part that approaches the viewer.

Generate complete active sprites separately only after a whole-sheet attempt repeatedly changes identity.

Record the reason. Never paste a local limb or body-part patch that creates a visible seam.

## Attack Design

Select the weapon before generation. Use teeth, jaws, horns, head, claws, wings, forelimbs, tendrils, body mass, or held weapons when appropriate.

Do not default every creature to a right-hand strike. A simple animation remains distinct when anticipation and contact use creature-specific anatomy.

## Background And Segmentation

Use black by default for creature grids. Use gray or white when the creature loses contrast against black.

White-eyed or shadow creatures often need neutral gray.

Run Lucida before adaptive segmentation. Review variable source boxes before registration. A fixed `2x2` layout defines frame order, not one fixed crop size.

## Registration

Read the runtime cell and pivot from the game. Do not infer them from the generated sheet.

- Use `bbox-bottom` only for a stable lowest contact.
- Use `body-bottom` when feet, claws, or appendages change their lowest extent.
- Use `center` for hovering or winged bodies with a stable core.
- Use `footprint` when the ground-contact area is the gameplay anchor.

Inspect `qa/registration-overlay.png` and each onion sheet. Correct body drift. Do not remove intentional attack or step motion.

## QA Protocol

Review these artifacts before approval:

- Matte board and adaptive segmentation.
- Contact sheet in chronological order.
- Onion skin with baseline and body center.
- Runtime playback from `manifest.json.frame_layout`.
- Identity report and the accepted idle at runtime size.

Identity proxies can include raised arms, wings, or weapons inside a head or torso band.

Keep the standard failure report. If visual evidence proves stable identity, run a pose-aware comparison and record its thresholds.

Do not widen thresholds to hide visible scale drift.

Record every rejection and accepted run in a creature decision ledger. Read that entry before another regeneration.
