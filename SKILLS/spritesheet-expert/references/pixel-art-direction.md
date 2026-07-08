# Pixel-Art Atlas Direction

Use this reference when the atlas target is pixel art, tile art, tiny sprites,
retro game assets, or any run that opts into `art_direction.mode: pixel-art`.

Primary source material: local pixel-art workflow corpus supplied by the user.
The pipeline uses the corpus as production principles, not as a request to copy
a specific artist or name a style after one source. Prompts should preserve the
user's subject, style, and game constraints.

## Pipeline Contract

`prepare_sprite_run.py` writes:

```text
sprite-request.json.art_direction
references/art-direction.json
prompts/<state>.txt
```

`art_direction.profiles` may be explicit profile ids or `auto`. `auto` infers
profiles from asset kind, preset camera, state id, action text, cell size, and
combat/VFX/tile keywords.

Animation phase contracts live in `references/pixel-animation-workflows.md`.
`prepare_sprite_run.py` writes active workflow ids to
`references/art-direction.json` and injects their phase requirements into row
prompts.

Use `--art-direction none` only when the user asks for non-pixel art direction
or the profile would fight a custom style.

Examples:

```bash
python scripts/preset_to_request.py platformer-character --out /abs/run/request.json
python scripts/preset_to_request.py custom-atlas --art-profile pixel-combat --out /abs/run/request.json --states-file /abs/run/states.json
python scripts/prepare_sprite_run.py --out-dir /abs/run --character-id hero --request /abs/run/request.json --force
```

## Universal Bar

- Palette: small sub-palette per scene/row, hue-shifted ramps, value contrast
  before hue variety, no saturated high-brightness color spam.
- Clusters: intentional groups of pixels, repeated motifs, no orphan pixels,
  no noisy literal detail where suggestion would read better.
- Light: one primary direction, usually top or upper corner; use directional
  highlight/midtone/shadow, never pillow shading.
- Scale: smaller is often stronger. If detail, color, or frame count does not
  improve runtime readability, remove it.
- Playback: judge motion at full speed. A static zoomed-in contact sheet can
  hide jitter, pops, and noisy flicker.

## Profiles

### `pixel-core`

Always-on pixel-art fundamentals. Applies palette, cluster, lighting, and
runtime-scale economy. Use for almost every pixel-art profile.

Failure signs: pillow shading, fuzzy anti-aliased detail, unrelated palettes,
or high-detail cells that read worse at target size.

### `pixel-character`

Character construction and identity. Applies dummy/anatomy-first workflow,
silhouette priority, animation-friendly simplification, and asymmetric-detail
discipline.

Failure signs: static-pose design that falls apart in motion, costume noise,
hands/feet/weapon lost in silhouette, or mirrored gear that changes hand/side.

### `pixel-motion`

Animation economy. Applies keyframe-first thinking, section-by-section motion,
loop seam checks, and energy over smoothness.

Failure signs: too many weak in-betweens, missing contact/pass/action poses,
uniform sine-wave bounce, or frame reduction that deletes key poses.

### `pixel-sideview`

Platformer, run-n-gun, side-view character and side-view tile logic. Applies
center-of-gravity anchors, tile-unit gameplay readability, walk/run mechanics,
responsive jump expectations, collision-clean tile silhouettes, and variants.

Failure signs: jittering anchor, jump anticipation in twitch movement, flat
platforms with no support, foreground collision lost in background texture, or
walk/run cycles without contact/down/pass/swing logic.

### `pixel-topdown`

Top-down characters, props, and tiles. Applies one 3/4 projection, tile-unit
sprite sizing, Y-overlap discipline, flippability tradeoffs, direction planning,
and terrain 3x3 repetition checks.

Failure signs: mixed side/top projection, X-overlap depth confusion, asymmetric
characters mirrored as if symmetrical, or terrain edges that only work in a
contact sheet.

### `pixel-isometric`

Isometric/dimetric assets. Applies 2:1 line discipline, cuboid/wireframe
construction, surface-specific seamless checks, and projection anchors for
round organic forms.

Failure signs: eyeballed 30-degree lines, inconsistent plane values, seamless
top texture but broken side faces, or organic assets with no 2:1 anchor.

### `pixel-texture`

Textures, terrain, tiles, rocks, plants, bricks, materials. Applies cluster
density by scale, negative space, edge matching, geological/botanical/material
logic, and zoomed-out repetition review.

Failure signs: every leaf/brick drawn, blurry high-frequency texture, obvious
cross/diagonal in 3x3 tile tests, or material colors that do not fit the biome.

### `pixel-combat`

Melee, fighting, top-down attacks. Applies stance and biomechanics, attack
phases, smear direction, hit-frame emphasis, overshoot, visual-hitbox match,
and timing as risk/reward.

Failure signs: combat stance with no biomechanics, pretty attack pose with
unclear active frame, smear counter to motion, heavy attacks with no commitment,
jab with visible input-lag windup, or visual range that does not match gameplay
range.

### `pixel-items-ui`

Items, pickups, UI icons, feedback affordance. Applies silhouette-plus-color
iconicity, item-specific idle systems, consistent feedback grammar, and glance
readability.

Failure signs: icon recognized only by detail, distracting idle, pickup that
looks like a hazard, feedback not tied to item meaning, or UI competing with
the player focal point.

### `pixel-vfx`

Water, wind, impacts, explosions, ambient motion. Applies loop math, flow
points, buildup/peak/decay, stable emitter/contact anchors, and alpha-friendly
fade/cooling.

Failure signs: random motion, end-to-start pop, VFX stealing focus, detached
effects hiding weak body posing, or chroma-colored cores that break extraction.

### `pixel-shmup`

Ships, bullets, pickups, factions, explosions, parallax readability. Applies
projectile visibility, faction language, roll/thruster feedback, pickup
meaning, and background support.

Failure signs: bullets lost against backgrounds, enemies from different visual
games, mirrored ships under directional light, or generic pickups with no
rarity/meaning affordance.

### `pixel-tiny`

8x8, 8x16, NES-like, ultra-small sprites. Applies missing-information beauty,
outline use for readability, one-pixel movement economy, and low frame-count
discipline.

Failure signs: detail so small it becomes noise, 8-frame cycles where 3-6
frames read better, no outline on busy backgrounds, or movement larger than the
sprite scale can support.

### `pixel-environment`

Backgrounds, parallax, city/landscape/interior support assets. Applies
background-as-support, atmospheric perspective, modular tiles plus landmarks,
and gameplay/decor separation.

Failure signs: background competing with sprites, decorative texture confused
with collision, all-generic repetition, or all-custom scenery without runtime
reuse.

## QA And Repair

Add these checks to normal atlas QA when Pixel-art profiles are active:

- Open `references/art-direction.json`; confirm the active row profiles match
  the asset kind and state.
- Confirm active `animation_workflows` match the row's purpose. Use
  `references/pixel-animation-workflows.md` for the required phases before
  accepting generated art.
- Review prompts for the row before generation; if the wrong profile appears,
  fix the request or pass explicit `--art-profile`.
- For tiles/textures, add a zoomed-out repetition proof, preferably 3x3 for
  square tiles and surface-specific checks for isometric tiles.
- For character motion, review full-speed GIF/runtime playback for loop pop,
  anchor jitter, noisy flicker, and key-pose weakness.
- For combat rows, identify startup, active/contact, follow-through, recovery,
  and overshoot in the row or explain why the state intentionally omits a phase.
- For VFX, verify buildup/peak/decay and stable emitter/contact anchor.

Repair order:

1. Fix prompt/profile mismatch.
2. Regenerate only the failing row.
3. Curate/reorder/select frames if the row has enough good keys.
4. Adjust extraction/registration if the art is good but the atlas is wrong.
5. Regenerate the whole sheet only when identity, projection, palette, or core
   style language fails across multiple rows.
