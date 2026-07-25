# Sprite reference template standards

## Question

What evidence and phase contracts should reusable Image Gen reference templates
use so generated sprite sheets preserve correct motion instead of copying an
attractive but mechanically incoherent contact sheet?

## Answer

Reference templates must be workflow-specific. A generic mannequin sheet is
not sufficient. Every template needs protected key poses, view/projection,
ground or emitter anchor, loop/once semantics, and a visual approval record
bound to the exact PNG hash.

For an ordinary humanoid walk, use an eight-pose cycle:

1. contact A;
2. down/recoil A;
3. passing A;
4. up A;
5. contact B with limbs reversed;
6. down/recoil B;
7. passing B;
8. up B returning to contact A.

At least one foot remains in contact with the ground throughout a walk. The
torso stays comparatively upright, the feet remain low, and arms swing
cross-laterally. This distinguishes walk from run, where a flight phase exists,
the torso leans forward, and arm extension peaks differently.

## Sources and findings

- [Adobe walk-cycle guide](https://www.adobe.com/creativecloud/animation/discover/animation-walk-cycle.html): defines contact and passing poses, calls up/down essential to whole-body motion, recommends eight frames as a standard, and emphasizes consistent contact points, weight, crossover, arms, torso, and head.
- [Adobe run-cycle guide](https://www.adobe.com/uk/creativecloud/animation/discover/animation-run-cycle.html): distinguishes walk from run by continuous ground contact versus flight, upright versus forward-leaning torso, and gives the eight run keys contact/down/break/up plus the reversed half.
- [Library of Congress Muybridge plate 443 record](https://www.loc.gov/pictures/item/2003663778/): primary sequential photographic evidence with rear and right-profile human walking views and no known publication restrictions. Use as observation evidence, not as style input.
- [CMU Graphics Lab Motion Capture Database](https://mocap.cs.cmu.edu/): primary captured-motion corpus containing walking, running, and other actions. Use motion samples to check root trajectory and action mechanics when a workflow lacks a sufficiently explicit authored guide.
- [Adobe animation principles](https://www.adobe.com/creativecloud/animation/discover/principles-of-animation.html): supports volume-preserving squash/stretch, anticipation, readable staging, and pose-to-pose planning. These become cross-workflow gates rather than optional prompt flavor.
- [Godot 2D sprite animation documentation](https://docs.godotengine.org/en/stable/tutorials/2d/2d_sprite_animation.html): confirms ordered frame playback, FPS review, and explicit row/column selection from sprite sheets; therefore static contact-sheet inspection alone is insufficient.
- [Unity texture-sheet animation API](https://docs.unity3d.com/ScriptReference/ParticleSystem.TextureSheetAnimationModule.html): confirms evenly distributed flipbook frames, explicit grid dimensions, cycle count, FPS, and frame-over-time controls for temporal VFX references.
- [Blender Actions manual](https://docs.blender.org/manual/en/latest/animation/actions.html): cyclic actions need an explicit useful range and matching loop endpoints. Template QA must check the last-to-first seam, not duplicate frame 1 inside the delivered runtime frame range.

## Decisions for this repository

1. Image Gen reference templates use minimalist flat 2D illustrations. Avoid 3D
   mannequins, gradients, glossy surfaces, floor shadows, or character style.
2. Walk and run are separate templates and separate validators. A high-knee or
   flight pose is a walk failure, even if the sheet looks polished.
3. Every body template color-locks anatomical left/right limbs. Frame contracts
   name both the planted/swing leg and the counter-swing arm.
4. Templates are generated once, stored in the repository, hash-pinned, and
   reused. `candidate` is not usable; only visually reviewed `approved` assets
   may enter a run.
5. Every animation workflow gets its own reference family:
   idle, fighting idle, walk, run, top-down locomotion, quick strike, power
   strike, top-down attack, jump, hit/knockdown, run-and-gun, VFX, water, wind,
   pickup, and tiny motion.
6. Body/action templates gate anatomy, contact, weight, phase order, and loop or
   recovery. VFX/environment templates gate emitter/flow anchor, buildup/peak/
   decay or loop math, frame occupancy, and last-to-first continuity.
7. Approval requires both contact-sheet review and playback review at declared
   FPS. Numeric/image checks cannot self-approve motion quality.

## Remaining uncertainty

Creature and non-humanoid locomotion cannot safely inherit the humanoid walk
template. Each morphology needs its own observed-motion source and phase
contract before a reusable template is approved.
