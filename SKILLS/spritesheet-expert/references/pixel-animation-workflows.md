# Pixel Animation Workflows

Row contracts, not style prompts. Use when `references/art-direction.json` lists
`animation_workflows`, or when reviewing pixel-art sprite/VFX rows. Must exist before generation, curation, QA pass.

Source: local pixel-art workflow corpus, archived GIFs/images from
user. Pipeline uses them as production principles — don't copy artist
or name style after one source.

## Pipeline Contract

`prepare_sprite_run.py` infers workflows per row from:

- `asset_kind`;
- state id and action text;
- preset camera/context;
- active pixel-art profiles;
- explicit `animation_workflows` on request or row, when provided.

Writes active workflows to `references/art-direction.json` and phase
requirements to `prompts/<state>.txt`. Locomotion rows write
`prompts/motion-references/<state>.txt` and
`references/motion-reference-contracts/<state>.json`. Preparer reuses an
approved hash-pinned master from `assets/motion-reference-templates/`,
deriving 4/6-frame and mirrored variants without redrawing anatomy. Image Gen
only on template cache miss; promote accepted results. Every materialized
reference pass `check_motion_references.py` before character-row
generation. Layout guides: slot geometry only — not motion/anatomy proof.

Wrong inferred workflow: fix request before generation: more explicit
row/action text, or set `animation_workflows` directly.

After extraction and preview, run `check_animation_contracts.py`. JSON report
is automated contract check, not visual-review substitute. Hard contract
errors fail the row before polish, even if source art looks good.

## Universal Rules

- Plan key poses first. Don't ask model for "smooth animation" without
 naming keys that survive.
- Protect contact, pass, hit/contact, follow-through, recovery, and loop seam
 poses when cutting frames.
- Playback speed = drawing. Full-speed GIF/runtime playback required for loop,
 jitter, flicker, sluggishness.
- Pose-to-pose for characters and gameplay. Straight-ahead only for chaotic
 effects where form continuity is intentionally loose.
- Mental layers: legs, arms, head, torso, equipment, hair/cloth, VFX. Base
 motion before polish.
- Full-speed readability beats static pixel accuracy. Flickering detail is
 noise if accurate on static design.

## Workflow Catalog

### `idle-breath`

Standing idle loops and neutral living motion.

1. Torso/weight anchor.
2. Slow rise or held high point.
3. Faster gravity/down accent.
4. Return to first pose without visible pop.

feet/bounding box stable unless stepping is requested; secondary motion
delayed and smaller than torso rhythm.

### `fighting-stance-idle`

Combat idles, guards, stance loops, ready poses.

1. Biomechanical stance: guard, center of mass, support side, and weapon/hand
 logic.
2. Breath/weight rhythm anchored on torso.
3. Extremity amplification: fists, hair, cloth, or weapon move little more
 than torso.
4. Offset timing, not uniform bobbing.

stance reads fighter/weapon role — not generic idle with fists raised.

### `gesture-loop`

Character wave, greeting, salute, emote, or other planted body gesture. Not a
water-wave workflow.

1. Exact accepted identity anchor.
2. Readable anticipation or limb raise.
3. One clear gesture accent.
4. Return to identity anchor before playback wraps.

planted gesture — freeze pelvis, both legs, knees, ankles, both feet, and
contact footprint at first-frame position. No weight shift, hip/root
translation, knee bend, ankle turn, foot rotation, foot slide, or body sway.
Only gesturing shoulder, arm, wrist, and hand carry action; head/torso
motion minimal. Framing, scale, identity locked; no detached symbols replace
pose; final-to-first mustn't pop arm, hand, or prop.

`check_animation_contracts.py` treats loop closure and planted-body stability
as separate requirements. Loop can close cleanly and still fail when the
lower body travels in middle frames.

### `sideview-locomotion`

Side-view walk/run/platformer/run-and-gun motion.

1. Contact.
2. Down.
3. Pass.
4. Swing/up.
5. Mirrored contact/down/pass/swing for second half when frame count allows.

Frame economy:

- 8 frames: fluid full cycle.
- 6 frames: strong default.
- 4 frames: preserve contact/pass essence.
- 3 frames: stride, pass, stride, with pass reused mentally.

opposite arm/leg momentum, triangle-like head/body bob, no same-leg
repetition, no foot sliding, loop seam stable at playback speed.

### `topdown-locomotion`

Top-down 4-dir/8-dir character motion.

1. Choose 4 directions, 5 flippable orientations, or 8 unique orientations.
2. Build front/up/side first; diagonals last.
3. Use rotation playback to reveal projection, thickness, and limb-length
 errors.
4. Prefer 6-frame variable bounce: down, down, faster up/pass.
5. For 4-frame walk rows, lock row to contact A, pass/down, contact B,
 pass/up. Contact and contact B read as opposite support legs in that
 direction, not as shifted silhouette.
6. Add equipment, hair, cape, and asymmetric details after base motion.

handedness and asymmetry stay correct; direction changes don't alter body
volume or projection. Hair, capes, robes, or large costumes can't hide
leg-phase proof. Frame 1 and halfway contact frame visibly use
opposite anatomical support legs, joined by crossover or depth swap.
Screen-space left/right balance can't prove leg identity. If chronological
playback repeats same anatomical contact leg, regenerate or repair that
row before polish.

### `combat-quick-strike`

Jabs, fast punches, front kicks, low-risk combo starters.

1. Guard/start or immediate launch with little/no windup.
2. Brief smear in main motion direction.
3. Hit/contact frame, strongest silhouette, sometimes held.
4. Follow-through.
5. Recover.
6. Overshoot/snap back when frames allow.

move feels responsive; visual range matches gameplay range; no smear
counter to motion.

### `combat-power-strike`

Cross punches, round kicks, heavy attacks, finishers, swords, hammers,
committed melee.

1. Load/pull/anticipation.
2. Fast smear.
3. Hit/contact.
4. Follow-through, possibly held for weight.
5. Recovery, scaled by commitment.
6. Overshoot/settle.

added anticipation reads as power, not input lag; heavy smears few and
fast.

### `topdown-weapon-attack`

Top-down melee and weapon attacks.

1. Anticipation.
2. Forward smear.
3. Optional rebound for hammer/ground contact.
4. Follow-through.
5. Recover.

Six frames is practical default. Timing encodes weight: quick sword-like
weapons, medium spear-like commitment, slow hammer-like commitment. Smears
only belong to forward strike.

weapon stays in same hand across directions; hitbox range feels fair
across angles.

### `responsive-jump`

Platformer, action, and run-and-gun jumps.

1. Immediate up/launch pose, with no long anticipation.
2. Airborne/up pose.
3. Down/descending pose.
4. Landing compression or recycled crouch when fall warrants it.

body scale locked to idle; vertical placement sells arc; no dust or
motion marks compensate for weak posing.

### `hit-reaction-knockdown`

Hurt, hitstun, knockdown, death, collapse, fall reactions.

1. Impact direction.
2. Recoil/drag.
3. Overshoot or loss of balance.
4. Ground/contact or partial recovery.
5. Settle/final pose.

not surprised idle; force direction and loss of support are readable.

### `run-gun-layered-motion`

Side-view move-and-shoot rows.

1. Solve leg locomotion first.
2. Treat torso/weapon as separate aim/shoot layer.
3. Let gun sway ride shoulder/body bounce.
4. Suppress secondary hair/cloth flips when they fight main run rhythm.

legs keep flowing while upper-body action reads; jump has up/down poses
and no input-lag anticipation.

### `vfx-buildup-peak-decay`

Impacts, explosions, sparks, smoke, fire, electricity, generic effects.

1. Buildup or source contact.
2. Peak.
3. Decay/cooling.
4. Fade or loop return.

emitter/contact anchor stable; neutral-background removal preserves
intentional alpha and translucent colors; motion doesn't steal focus from the
gameplay subject.

### `water-loop`

Water, waves, waterfalls, rivers, splashes, ripples, reflections.

1. Build wave/flow guide before animation.
2. Verify loop math: total displacement over N frames closes on tile/band.
3. For waterfalls, synchronize mouth, vertical flow, and splash.
4. For reflections, start with good static reflected art and then add subtle
 directional ripple.

no end-to-start pop; waterfall bands sag/darken and break at bottom;
river flow is placed where river need motion.

### `wind-ambient-loop`

Wind, fabric, hair, plants, leaves, dust, swirls, ambient environment motion.

1. Choose material: particle swirl, dust cloud, hair/fabric wave, plant waving,
 falling leaves, or rustling.
2. Mark flow points.
3. Propagate one wave through layers with timing offsets.
4. Keep small sprites flat/simple if shading would flicker.

wind adds life without moving focal point; leaves/grass don't all
move in sync.

### `pickup-feedback`

Collectibles, UI icons, pickups, coins, health, gems, powerups.

1. Idle affordance: bob, bounce, shine, rotate, hover, or pulse.
2. Readability check: silhouette plus local color first.
3. Feedback grammar matches item meaning.
4. Loop stays short and stable.

pickup doesn't read as hazard, projectile, or environmental VFX.

### `tiny-motion`

8x8, 8x16, NES-like, and other tiny sprites.

1. One pixel is large motion; use 1px shifts or cluster swaps.
2. Prefer 2-4 strong frames over weak smooth transitions.
3. Remove detail that flickers at playback size.
4. Use outline/local contrast when backgrounds can swallow sprite.

no frame exists only to be smooth; each frame changes runtime read.

## QA Matrix

Before done, map every animated row to its active workflow:

- locomotion: contact/pass logic, frame 1 vs halfway contact using opposite
 anatomical support legs, visible crossover/depth swap, loop seam;
- character gesture: identity anchor, readable limb/body accent, stable feet,
 and clean final-to-first return;
- combat: stance, startup/load, smear direction, hit/contact,
 follow-through, recovery, overshoot;
- top-down: direction strategy, projection consistency, handedness;
- jump/reaction: scale lock, force/arc/readability;
- VFX/water/wind: loop math, emitter/flow anchors, focus discipline;
- tiny/pickup: no over-detail, no excessive frames, immediate readability.

If row can't show workflow phases in allotted frames, lower promise or
regenerate with a different frame budget. Don't accept a pretty row that
fails its phase contract.
