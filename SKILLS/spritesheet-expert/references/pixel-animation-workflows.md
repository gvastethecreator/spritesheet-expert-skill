# Pixel Animation Workflows

Use this reference when `references/art-direction.json` lists
`animation_workflows`, or when reviewing pixel-art sprite/VFX rows. These are
row contracts, not style prompts. They decide what phases an animation must
show before generation, curation, and QA can pass.

Primary source material: local pixel-art workflow corpus, including archived
GIFs/images supplied by the user. The pipeline uses those materials as
production principles, not as a request to copy a specific artist or name a
style after one source.

## Pipeline Contract

`prepare_sprite_run.py` infers animation workflows per row from:

- `asset_kind`;
- state id and action text;
- preset camera/context;
- active pixel-art profiles;
- explicit `animation_workflows` on the request or row, when provided.

The script writes active workflows to `references/art-direction.json` and adds
their phase requirements to `prompts/<state>.txt`. Locomotion rows additionally
write `prompts/motion-references/<state>.txt` and
`references/motion-reference-contracts/<state>.json`. The preparer first reuses
an approved hash-pinned master from `assets/motion-reference-templates/`,
deriving 4/6-frame and mirrored variants without redrawing anatomy. Only a
template cache miss calls Image Gen; promote accepted results so later runs do
not regenerate them. Every materialized reference must pass
`check_motion_references.py` before character-row generation. Deterministic
layout guides provide slot geometry only; they are not motion or anatomy proof.

If the inferred workflow is wrong, fix the request before generation by making
the row/action text more explicit or by setting `animation_workflows` directly.

After extraction and preview, run `check_animation_contracts.py`. The JSON
report is not a substitute for visual review; it is the automated part of the
phase contract. A row with hard contract errors is failed before polish, even
when the source art looks attractive.

## Universal Rules

- Plan key poses first. Do not ask the model for "smooth animation" without
  naming the keys that must survive.
- Protect contact, pass, hit/contact, follow-through, recovery, and loop seam
  poses when reducing frame count.
- Playback speed matters as much as drawing. Full-speed GIF/runtime playback is
  required for loop, jitter, flicker, and sluggishness review.
- Use pose-to-pose for characters and gameplay actions. Use straight-ahead only
  for chaotic effects where form continuity is intentionally loose.
- Work in layers mentally: legs, arms, head, torso, equipment, hair/cloth, VFX.
  Solve base motion before polish.
- Full-speed readability beats static pixel accuracy. If a detail flickers, it
  is noise even if it is accurate on the static design.

## Workflow Catalog

### `idle-breath`

For standing idle loops and neutral living motion.

Required phases:

1. Torso/weight anchor.
2. Slow rise or held high point.
3. Faster gravity/down accent.
4. Return to first pose without visible pop.

QA: feet/bounding box remain stable unless stepping is requested; secondary
motion is delayed and smaller than the torso rhythm.

### `fighting-stance-idle`

For combat idles, guards, stance loops, and ready poses.

Required phases:

1. Biomechanical stance: guard, center of mass, support side, and weapon/hand
   logic.
2. Breath/weight rhythm anchored on torso.
3. Extremity amplification: fists, hair, cloth, or weapon move a little more
   than the torso.
4. Offset timing, not uniform bobbing.

QA: stance communicates fighter/weapon role and does not look like a generic
idle with fists raised.

### `gesture-loop`

For a character wave, greeting, salute, emote, or other planted body gesture.
It is not a water-wave workflow.

Required phases:

1. Exact accepted identity anchor.
2. Readable anticipation or limb raise.
3. One clear gesture accent.
4. Return to the identity anchor before playback wraps.

QA: for a planted gesture, freeze pelvis, both legs, knees, ankles, both feet,
and the contact footprint in the first-frame position. Do not allow weight
shift, hip/root translation, knee bend, ankle turn, foot rotation, foot
sliding, or body sway. Only the gesturing shoulder, arm, wrist, and hand should
carry the action; head and torso motion stay minimal. Framing, scale, and
identity stay locked; no detached symbols replace the pose; the final-to-first
transition does not pop an arm, hand, or prop.

`check_animation_contracts.py` treats loop closure and planted-body stability
as separate requirements. A loop can close cleanly and still fail when its
lower body travels during the middle frames.

### `sideview-locomotion`

For side-view walk/run/platformer/run-and-gun motion.

Required phases:

1. Contact.
2. Down.
3. Pass.
4. Swing/up.
5. Mirrored contact/down/pass/swing for the second half when frame count allows.

Frame economy:

- 8 frames: fluid full cycle.
- 6 frames: strong default.
- 4 frames: preserve contact/pass essence.
- 3 frames: stride, pass, stride, with the pass reused mentally.

QA: opposite arm/leg momentum, triangle-like head/body bob, no same-leg
repetition, no foot sliding, and loop seam stable at playback speed.

### `topdown-locomotion`

For top-down 4-dir/8-dir character motion.

Required steps:

1. Choose 4 directions, 5 flippable orientations, or 8 unique orientations.
2. Build front/up/side first; diagonals last.
3. Use rotation playback to reveal projection, thickness, and limb-length
   errors.
4. Prefer 6-frame variable bounce when possible: down, down, faster up/pass.
5. For 4-frame walk rows, lock the row to contact A, pass/down, contact B,
   pass/up. Contact A and contact B must read as opposite support legs in that
   direction, not just as a shifted silhouette.
6. Add equipment, hair, cape, and asymmetric details after the base motion.

QA: handedness and asymmetry stay correct; direction changes do not alter body
volume or projection. Hair, capes, robes, or large costumes cannot hide the
leg-phase proof. Frame 1 and the halfway contact frame must visibly use opposite
anatomical support legs, joined by a crossover or depth swap. Screen-space
left/right balance cannot prove leg identity. If chronological playback repeats
the same anatomical contact leg, regenerate or repair that row before polish.

### `combat-quick-strike`

For jabs, fast punches, front kicks, and low-risk combo starters.

Required phases:

1. Guard/start or immediate launch with little/no windup.
2. Brief smear in the main motion direction.
3. Hit/contact frame, strongest silhouette, sometimes held.
4. Follow-through.
5. Recover.
6. Overshoot/snap back when frames allow.

QA: the move feels responsive; visual range matches gameplay range; no smear
counter to motion.

### `combat-power-strike`

For cross punches, round kicks, heavy attacks, finishers, swords, hammers, and
committed melee.

Required phases:

1. Load/pull/anticipation.
2. Fast smear.
3. Hit/contact.
4. Follow-through, possibly held for weight.
5. Recovery, scaled by commitment.
6. Overshoot/settle.

QA: added anticipation communicates power rather than input lag; heavy smears
remain few and fast.

### `topdown-weapon-attack`

For top-down melee and weapon attacks.

Required phases:

1. Anticipation.
2. Forward smear.
3. Optional rebound for hammer/ground contact.
4. Follow-through.
5. Recover.

Six frames is a practical default. Timing encodes weight: quick sword-like
weapons, medium spear-like commitment, slow hammer-like commitment. Smears only
belong to the forward strike.

QA: weapon stays in the same hand across directions; hitbox range feels fair
across angles.

### `responsive-jump`

For platformer, action, and run-and-gun jumps.

Required phases:

1. Immediate up/launch pose, usually with no long anticipation.
2. Airborne/up pose.
3. Down/descending pose.
4. Landing compression or recycled crouch when the fall warrants it.

QA: body scale remains locked to idle; vertical placement sells the arc; no dust
or motion marks compensate for weak posing.

### `hit-reaction-knockdown`

For hurt, hitstun, knockdown, death, collapse, and fall reactions.

Required phases:

1. Impact direction.
2. Recoil/drag.
3. Overshoot or loss of balance.
4. Ground/contact or partial recovery.
5. Settle/final pose.

QA: not a surprised idle; force direction and loss of support are readable.

### `run-gun-layered-motion`

For side-view move-and-shoot rows.

Required steps:

1. Solve leg locomotion first.
2. Treat torso/weapon as a separate aim/shoot layer.
3. Let gun sway ride shoulder/body bounce.
4. Suppress secondary hair/cloth flips when they fight the main run rhythm.

QA: legs keep flowing while upper-body action reads; jump has up/down poses and
no input-lag anticipation.

### `vfx-buildup-peak-decay`

For impacts, explosions, sparks, smoke, fire, electricity, and generic effects.

Required phases:

1. Buildup or source contact.
2. Peak.
3. Decay/cooling.
4. Fade or loop return.

QA: emitter/contact anchor is stable; neutral-background removal preserves
intentional alpha and translucent colors; motion does not steal focus from the
gameplay subject.

### `water-loop`

For water, waves, waterfalls, rivers, splashes, ripples, and reflections.

Required steps:

1. Build the wave/flow guide before animation.
2. Verify loop math: total displacement over N frames closes on the tile/band.
3. For waterfalls, synchronize mouth, vertical flow, and splash.
4. For reflections, start with good static reflected art and then add subtle
   directional ripple.

QA: no end-to-start pop; waterfall bands sag/darken and break at the bottom;
river flow is placed where the river actually needs motion.

### `wind-ambient-loop`

For wind, fabric, hair, plants, leaves, dust, swirls, and ambient environment
motion.

Required steps:

1. Choose material: particle swirl, dust cloud, hair/fabric wave, plant waving,
   falling leaves, or rustling.
2. Mark flow points.
3. Propagate one wave through layers with timing offsets.
4. Keep small sprites flat/simple if shading would flicker.

QA: wind adds life without moving the focal point; leaves/grass do not all move
in sync.

### `pickup-feedback`

For collectibles, UI icons, pickups, coins, health, gems, and powerups.

Required phases:

1. Idle affordance: bob, bounce, shine, rotate, hover, or pulse.
2. Readability check: silhouette plus local color first.
3. Feedback grammar matches item meaning.
4. Loop stays short and stable.

QA: pickup does not read as hazard, projectile, or environmental VFX.

### `tiny-motion`

For 8x8, 8x16, NES-like, and other tiny sprites.

Required rules:

1. One pixel is a large motion; use 1px shifts or cluster swaps.
2. Prefer 2-4 strong frames over weak smooth transitions.
3. Remove detail that flickers at playback size.
4. Use outline/local contrast when backgrounds can swallow the sprite.

QA: no frame exists only to be smooth; each frame changes the runtime read.

## QA Matrix

Before done, map every animated row to its active workflow:

- locomotion: contact/pass logic, frame 1 vs halfway contact using opposite
  anatomical support legs, visible crossover/depth swap, loop seam;
- character gesture: identity anchor, readable limb/body accent, stable feet,
  and clean final-to-first return;
- combat: stance, startup/load if needed, smear direction, hit/contact,
  follow-through, recovery, overshoot;
- top-down: direction strategy, projection consistency, handedness;
- jump/reaction: scale lock, force/arc/readability;
- VFX/water/wind: loop math, emitter/flow anchors, focus discipline;
- tiny/pickup: no over-detail, no excessive frames, immediate readability.

If the row cannot show the workflow phases in its allotted frames, either lower
the promise in the request or regenerate with a different frame budget. Do not
accept a pretty row that fails its phase contract.
