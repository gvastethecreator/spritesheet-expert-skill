# Professional Sprite Animation Standard

Use this reference when improving prompts, presets, curation, QA, or generated assets in `spritesheet-expert`.

## Runtime Atlas Contract

- Atlas output must be runtime-addressable: fixed frame rectangles, stable row order, and `manifest.json.frame_layout` as the source of truth.
- Every sprite frame needs a consistent origin/pivot. Side-view characters usually anchor at feet or center-of-mass projection; top-down characters anchor near ground contact; VFX anchor at the emitter/contact point; tiles anchor to the grid.
- Leave padding/extrusion around sprites so linear filtering, mipmaps, and compression do not bleed neighboring frames into runtime rendering.
- Preserve frame count, FPS, loop flag, and animation tags/row semantics from the preset or request. Do not silently convert animation frames into variant stills.
- Export by state rows when possible. It keeps curation and QA local to the failing action and avoids regenerating unrelated rows.

## Animation Principles For Game Sprites

- Key poses first: define readable extremes before inbetweens. Most game actions need anticipation/setup, action/contact/extreme, recovery/settle.
- Silhouette and staging: the action must read in thumbnail size. Face, hands, feet, weapon/contact point, and line of action should not hide each other.
- Timing and spacing: loops need consistent rhythm; attacks need clear startup, active/readable contact, and recovery; hit reactions need impact, drag/overshoot, then settle.
- Arcs: heads, hands, feet, weapons, hair, cloth, and props usually travel along arcs instead of straight linear slides.
- Squash/stretch is local and volume-preserving. It must not become a camera zoom or global scale drift.
- Follow-through/overlap: hair, cloth, belly, sleeves, tails, or props can lag slightly behind the main body, but identity details must stay stable.
- Appeal: a frame can be simple, but it needs a confident pose, stable proportions, and clean negative space.

## Body Mechanics And Anatomy

- Preserve the same character volume across states. Compare head width, upper-body width, limb thickness, foot size, outline weight, and costume scale against idle.
- Weight shift must have a cause. Grounded poses need planted feet, readable support side, bent knees/hips when lowering, and a center of mass over or between supports.
- Crouch: do not uniformly shrink the character. Feet stay on baseline, knees/hips bend, torso/head lower, silhouette may widen, and stable parts keep the same scale.
- Jump: do not shrink at the peak. The same-sized body moves vertically through anticipation, takeoff, airborne, descent, and landing.
- Attacks: strongest frame must show the threat direction. Hands/feet/weapons should extend along a readable line of action; torso/hips counter-rotate; recovery does not teleport back to idle.
- Reactions: hitstun/knockdown should show force direction, balance loss, drag/overshoot, and recovery/fall staging.
- Keep joints plausible for the design. Cartoon exaggeration is allowed, but knees, elbows, wrists, ankles, shoulders, and hips should still explain the pose.

## Fighting Game Rows

- Idle: stable combat stance, guarded hands, subtle breathing/weight shift, no scale drift.
- Walk forward/back: clear foot contacts and passing poses. Back walk is not a mirrored forward walk if guard/weight differs.
- Crouch: one readable descent into guarded low stance; final key pose lower than idle without head/torso inflation or full-body shrink.
- Jump: anticipation on baseline, airborne peak, descent, landing/recovery. Use vertical placement, not zoom.
- Punch/kick/special: startup, active/contact, recovery. The active frame should be the clearest silhouette and should not rely on detached effects to read.
- Block/hitstun/knockdown: prioritize defensive/readability states over beauty poses; show force, balance, and contact direction.

## Rigging, Cutout, And Frame-By-Frame

- Use bones/rig logic as a mental model even for generated frames: root/pelvis, chest, head, upper/lower limbs, hands/feet, weapon/prop, hair/cloth overlap.
- Rigged/cutout animation is useful for preserving identity, but can become stiff. Add pose-specific redraws at joints, hands, face, cloth, and contact frames.
- Frame-by-frame animation is better for attacks, squash, VFX, and expressive reactions, but must be constrained by the idle anchor and feature-scale QA.
- If a generated row drifts, promote a corrected frame/anchor and regenerate only the failing row before replacing the whole sheet.

## Asset Mode Standards

- Sprite: full-body/contact-aware animation with identity, scale, silhouette, pivot, and motion QA.
- Tileset: slot extraction, exact grid fit, compatible edges, readable collision surfaces, projection consistency, no scene/collage output.
- Texture: flat orthographic samples, seamless/tileable intent, consistent texel density, no perspective scene, no labels.
- Asset/prop/icon: consistent set language, scale hierarchy, silhouette, center/pivot, isolated alpha/neutral-source boundary, no catalog page.
- VFX: temporal sequence with buildup, peak, decay; alpha-friendly opacity; no source-background residue; consistent emitter anchor.
- Custom atlas: write explicit row semantics first. Unknown rows must declare whether frames are animation timing or still variants.

## Background Removal Standard

- Generate new sources on a perfectly flat neutral gray, black, or white background. Do not exclude neutral colors from the subject palette.
- Preserve trustworthy alpha first. Use edge-connected matte removal only for a clean flat border; this avoids globally deleting white clothing, black outlines, gray materials, highlights, or interior holes.
- Use the pinned Lucida model for new Imagegen character and creature grids. Prefer black when there is no identity image. Use adaptive frame bounds after matting. Keep hard alpha threshold `64` for pixel art and soft alpha for illustrated sprites that need translucent edges.
- Use `rembg` with `birefnet-general` for ambiguous, soft, dirty, photographic, painterly, or breathing video backgrounds. `birefnet-general-lite` is a speed option, not the quality default.
- Use BEN2 explicitly for hard/final comparisons where BiRefNet clips hair, fur, spikes, small limbs, or painterly edges. Backend choice is not proof; the best reviewed matte wins.
- Chroma removal is a legacy-import path only. It must be declared, border-connected, soft-edged, and despilled. Do not generate new green, blue, cyan, or magenta source backgrounds.
- Do not apply post-chroma cleanup after model-backed removal on neutral sources. Subject-color over-removal is a production failure.
- QA must check both math and pixels on checker, black, gray, white, and alpha-mask surfaces: transparent interior holes, semi-transparent clothing, source-background residue, edge halos, jagged cut edges, and disconnected fragments.

## QA Checklist

- Runtime: `frame_layout` exists; rectangles, rows, frame counts, FPS/loop intent, and origins are usable.
- Extraction: no cropped bodies, edge pixels, chroma leaks, alpha holes, disconnected debris, or slot overlap.
- Identity: face, hair, palette, outfit, outline, proportions, and asymmetric details match accepted anchors.
- Pose scale: compare height, width, head proxy, upper-body proxy, baseline/bottom, and expected pose curve.
- Visual review: open contact sheet/GIF/`qa/pose-scale-review.png`; judge pose readability, line of action, body mechanics, and professional consistency. Metrics are necessary but not sufficient.
- Runtime playback: load frames through the same `frame_layout`/origin data the game will use, play state transitions in an update/render loop, and inspect bbox/baseline/origin overlays while the actor moves.
- Motion: locomotion alternates contacts/passing; attacks show startup/contact/recovery; jumps/crouches/falls/lands obey baseline/arc; loops do not pop.
- Asset modes: tiles tile, textures repeat, icons read at target size, VFX composes cleanly, still assets share a coherent set style.

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
