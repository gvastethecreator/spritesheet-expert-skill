# Professional Sprite Animation Standard

Use when improving prompts, presets, curation, QA, or generated assets in
`spritesheet-expert`.

## Runtime Atlas Contract

- Atlas output is runtime-addressable: fixed frame rectangles, stable row
 order, `manifest.json.frame_layout` as source of truth.
- Every sprite frame needs consistent origin/pivot. Side-view characters
 anchor at feet or center-of-mass projection; top-down near ground
 contact; VFX at emitter/contact point; tiles to grid.
- Pad/extrude sprites so linear filtering, mipmaps, and compression don't bleed neighboring frames.
- Preserve frame count, FPS, loop flag, and animation tags/row semantics from
 preset or request. Don't silently convert animation frames into variant
 stills.
- Export by state rows: curation/QA local to failing action; don't regenerate unrelated rows.

## Animation Principles For Game Sprites

- Key poses first: readable extremes before inbetweens. Actions need
 setup, contact/extreme, recovery.
- Silhouette: action reads in thumbnail. Face, hands, feet, weapon/contact, line of action shouldn't hide each other.
- Timing: loops keep rhythm; attacks need startup, readable contact, recovery;
 hits need impact, drag/overshoot, settle.
- Arcs for heads, hands, feet, weapons, hair, cloth, props — not linear slides.
- Squash/stretch: local, volume-preserving. Not camera zoom or global scale
 drift.
- Follow-through: hair, cloth, belly, sleeves, tails, props can lag; identity
 details stay stable.
- Appeal: simple is fine; poses confident, proportions stable, negative space clean.

## Body Mechanics And Anatomy

- Same character volume across states. Compare head width, upper-body width,
 limb thickness, foot size, outline weight, costume scale vs idle.
- Weight shift needs a cause. Grounded poses: planted feet, readable support,
 bent knees/hips when lowering, COM over or between supports.
- Crouch: don't uniformly shrink. Feet on baseline, knees/hips bend, torso/head
 lower, silhouette may widen, stable parts keep scale.
- Jump: don't shrink at peak. Same-sized body through anticipation, takeoff,
 airborne, descent, landing.
- Attacks: strongest frame shows threat direction. Hands/feet/weapons along a
 readable line of action; torso/hips counter-rotate; recovery doesn't teleport
 to idle.
- Reactions: hitstun/knockdown show force direction, balance loss,
 drag/overshoot, recovery/fall staging.
- Joints plausible. Cartoon exaggeration allowed, but knees, elbows, wrists, ankles, shoulders, hips explain the pose.

## Fighting Game Rows

- Idle: stable combat stance, guarded hands, subtle breathing/weight shift, no
 scale drift.
- Walk forward/back: clear foot contacts and passing poses. Back walk isn't a
 mirrored forward walk if guard/weight differs.
- Crouch: one readable descent into guarded low stance; final key pose lower
 than idle without head/torso inflation or full-body shrink.
- Jump: anticipation on baseline, airborne peak, descent, landing/recovery.
 Use vertical placement, not zoom.
- Punch/kick/special: startup, active/contact, recovery. Active frame is clearest silhouette; don't rely on detached effects to read.
- Block/hitstun/knockdown: prioritize defensive/readability over beauty poses; show force, balance, contact direction.

## Rigging, Cutout, And Frame-By-Frame

- Bones/rig as mental model for generated frames: root/pelvis,
 chest, head, upper/lower limbs, hands/feet, weapon/prop, hair/cloth overlap.
- Rigged/cutout preserves identity but can go stiff. Add pose-specific redraws at joints, hands, face, cloth, contact frames.
- Frame-by-frame is better for attacks, squash, VFX, expressive reactions, but stay constrained by idle anchor and feature-scale QA.
- If generated row drifts, promote corrected frame/anchor and regenerate
 only failing row before replacing whole sheet.

## Asset Mode Standards

- Sprite: full-body/contact-aware animation with identity, scale, silhouette, pivot, motion QA.
- Tileset: slot extraction, exact grid fit, compatible edges, readable
 collision surfaces, projection consistency, no scene/collage output.
- Texture: flat orthographic samples, seamless/tileable intent, consistent
 texel density, no perspective scene, no labels.
- Asset/prop/icon: consistent set language, scale hierarchy, silhouette,
 center/pivot, isolated alpha/neutral-source boundary, no catalog page.
- VFX: temporal sequence with buildup, peak, decay; alpha-friendly opacity; no
 source-background residue; consistent emitter anchor.
- Custom atlas: write explicit row semantics first. Unknown rows declare
 whether frames are animation timing or variants.

## Background Removal Standard

- New sources: flat neutral gray, black, or white background. Don't exclude neutral colors from subject palette.
- Trustworthy alpha first. Edge-connected matte only for clean flat border — avoids globally deleting white clothing, black outlines, gray materials, highlights, or interior holes.
- Pinned Lucida model for new Imagegen character/creature grids.
 Prefer black when there's no identity image. Adaptive frame bounds after
 matting. Hard alpha threshold `64` for pixel art; soft alpha for
 illustrated sprites that need translucent edges.
- `rembg` + `birefnet-general` for ambiguous, soft, dirty, photographic,
 painterly, or breathing video backgrounds. `birefnet-general-lite` is
 speed option, not quality default.
- BEN2 for hard/final comparisons where BiRefNet clips hair, fur, spikes,
 small limbs, or painterly edges. Backend choice isn't proof; best reviewed
 matte wins.
- Chroma removal is legacy-import only. Must be declared, border-connected,
 soft-edged, and despilled. Don't generate new green, blue, cyan, or magenta
 source backgrounds.
- Don't post-chroma-clean after model-backed removal on neutral sources. Subject-color over-removal is production failure.
- QA checks math and pixels on checker, black, gray, white, alpha-mask
 surfaces: transparent interior holes, semi-transparent clothing,
 source-background residue, edge halos, jagged cut edges, disconnected
 fragments.

## QA Checklist

- Runtime: `frame_layout` exists; rectangles, rows, frame counts, FPS/loop
 intent, and origins are usable.
- Extraction: no cropped bodies, edge pixels, chroma leaks, alpha holes,
 disconnected debris, or slot overlap.
- Identity: face, hair, palette, outfit, outline, proportions, and asymmetric
 details match accepted anchors.
- Pose scale: compare height, width, head proxy, upper-body proxy,
 baseline/bottom, and expected pose curve.
- Visual review: open contact sheet/GIF/`qa/pose-scale-review.png`; judge pose readability, line of action, body mechanics, professional consistency.
 Metrics are necessary but not sufficient.
- Runtime playback: load frames through same `frame_layout`/origin data
 game will use, play state transitions in update/render loop; inspect bbox/baseline/origin overlays while actor moves.
- Motion: locomotion alternates contacts/passing; attacks show
 startup/contact/recovery; jumps/crouches/falls/lands obey baseline/arc;
 loops don't pop.
- Asset modes: tiles tile, textures repeat, icons read at target size, VFX
 composes cleanly, assets share coherent set style.

## Sources

- Unity Sprite Atlas manual: https://docs.unity3d.com/Manual/class-SpriteAtlas.html
- Unity 2D Animation package manual: https://docs.unity3d.com/Packages/com.unity.2d.animation@latest
- Godot 2D sprite animation docs: https://docs.godotengine.org/en/stable/tutorials/2d/2d_sprite_animation.html
- Godot 2D skeletons docs: https://docs.godotengine.org/en/stable/tutorials/animation/2d_skeletons.html
- Aseprite sprite sheet export docs: https://www.aseprite.org/docs/sprite-sheet/
- Adobe overview of the 12 principles of animation: https://www.adobe.com/creativecloud/animation/discover/principles-of-animation.html
- Animation Mentor 12 principles article: https://www.animationmentor.com/blog/12-principles-of-animation/
- Animation Mentor weight and body mechanics article: https://www.animationmentor.com/blog/how-to-create-believable-weight-in-animation/
- Capcom attack frame basics: https://game.capcom.com/cfn/sfv/column/131432?lang=en
- Rivals Workshop anticipation/action/recovery guide: https://www.rivalslib.com/workshop_guide/art/anticipation_action_recovery.html
- rembg local background removal project: https://github.com/danielgatis/rembg
- Lucida model and workflow: https://github.com/egeorcun/lucida
- BRIA RMBG-2.0 model page: https://huggingface.co/briaai/RMBG-2.0
