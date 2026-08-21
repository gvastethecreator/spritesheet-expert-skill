# Pixel-Art Atlas Direction

Use when atlas target is pixel art, tile art, tiny sprites, retro game
assets, or any run that opts into `art_direction.mode: pixel-art`.

Source: local pixel-art workflow corpus from user. Pipeline treats it as
production principles — don't copy an artist or name a style after one
source. Prompts keep user's subject, style, game constraints.

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
`references/art-direction.json` and injects phase requirements into row
prompts.

Use `--art-direction none` only when user asks for non-pixel art direction
or profile would fight custom style.

Examples:

```bash
python scripts/preset_to_request.py platformer-character --out /abs/run/request.json
python scripts/preset_to_request.py custom-atlas --art-profile pixel-combat --out /abs/run/request.json --states-file /abs/run/states.json
python scripts/prepare_sprite_run.py --out-dir /abs/run --character-id hero --request /abs/run/request.json --force
```

## Universal Bar

- Palette: small sub-palette per scene/row, hue-shifted ramps, value contrast
  before hue variety, no saturated high-brightness spam.
- Clusters: intentional pixel groups, repeated motifs, no orphan pixels, no
 noisy literal detail where suggestion reads better.
- Light: one primary direction, top or upper corner; directional
 highlight/midtone/shadow, never pillow shading.
- Scale: smaller is stronger. If detail, color, or frame count doesn't
 improve runtime readability, remove it.
- Playback: judge motion at full speed. Static zoomed-in contact sheet can
  hide jitter, pops, noisy flicker.

## Profiles

### `pixel-core`

Fundamentals: palette, cluster, lighting, runtime-scale economy.

Fail: pillow shading, fuzzy anti-aliased detail, unrelated palettes, or
high-detail cells that read worse at target size.

### `pixel-character`

Construction: dummy/anatomy-first, silhouette priority,
animation-friendly simplification, asymmetric-detail discipline.

Fail: static-pose design that falls apart in motion, costume noise,
hands/feet/weapon lost in silhouette, mirrored gear that changes hand/side.

### `pixel-motion`

Animation economy: keyframe-first, section-by-section motion, loop-seam
checks, energy over smoothness.

Fail: too many weak in-betweens, missing contact/pass/action poses, uniform
sine-wave bounce, frame reduction that deletes key poses.

### `pixel-sideview`

Platformer/run-n-gun side-view character and tiles: COG anchors, tile-unit
readability, walk/run mechanics, responsive jump, collision-clean silhouettes,
variants.

Fail: jittering anchor, jump anticipation in twitch movement, flat platforms
with no support, foreground collision lost in background texture, walk/run
cycles without contact/down/pass/swing logic.

### `pixel-topdown`

Top-down characters, props, tiles: one 3/4 projection, tile-unit sizing,
Y-overlap discipline, flippability tradeoffs, direction planning, terrain 3x3
repetition checks.

Fail: mixed side/top projection, X-overlap depth confusion, asymmetric
characters mirrored as if symmetrical, terrain edges that only work in a
contact sheet.

### `pixel-isometric`

Isometric/dimetric: 2:1 line discipline, cuboid/wireframe construction,
surface-specific seamless checks, projection anchors for round organic forms.

Fail: eyeballed 30-degree lines, inconsistent plane values, seamless top
texture but broken side faces, organic assets with no 2:1 anchor.

### `pixel-texture`

Textures, terrain, tiles, rocks, plants, bricks, materials: cluster density by
scale, negative space, edge matching, geological/botanical/material logic,
zoomed-out repetition review.

Fail: every leaf/brick drawn, blurry high-frequency texture, obvious
cross/diagonal in 3x3 tile tests, material colors that don't fit biome.

### `pixel-combat`

Melee/fighting/top-down attacks: stance and biomechanics, attack phases,
smear direction, hit-frame emphasis, overshoot, visual-hitbox match, timing as
risk/reward.

Fail: combat stance with no biomechanics, pretty attack pose with unclear
active frame, smear counter to motion, heavy attacks with no commitment, jab
with visible input-lag windup, visual range that doesn't match gameplay
range.

### `pixel-items-ui`

Items, pickups, UI icons, feedback: silhouette-plus-color iconicity,
item-specific idle, consistent feedback grammar, glance readability.

Fail: icon recognized only by detail, distracting idle, pickup that looks like
hazard, feedback not tied to item meaning, UI competing with player
focal point.

### `pixel-vfx`

Water, wind, impacts, explosions, ambient motion: loop math, flow points,
buildup/peak/decay, stable emitter/contact anchors, alpha-friendly fade/cooling.

Fail: random motion, end-to-start pop, VFX stealing focus, detached effects
hiding weak body posing, chroma-colored cores that break extraction.

### `pixel-shmup`

Ships, bullets, pickups, factions, explosions, parallax: projectile
visibility, faction language, roll/thruster feedback, pickup meaning,
background support.

Fail: bullets lost against backgrounds, enemies from different visual games,
mirrored ships under directional light, generic pickups with no
rarity/meaning affordance.

### `pixel-tiny`

8x8, 8x16, NES-like, ultra-small sprites: missing-information beauty, outline
for readability, one-pixel movement economy, low frame-count discipline.

Fail: detail so small it becomes noise, 8-frame cycles where 3-6 frames read
better, no outline on busy backgrounds, movement larger than sprite
scale can support.

### `pixel-environment`

Backgrounds, parallax, city/landscape/interior support: background-as-support,
atmospheric perspective, modular tiles plus landmarks, gameplay/decor
separation.

Fail: background competing with sprites, decorative texture confused with
collision, all-generic repetition, all-custom scenery without runtime reuse.

## QA And Repair

When pixel-art profiles are active:

- Open `references/art-direction.json`; active row profiles match asset
 kind and state.
- Active `animation_workflows` match row purpose. Use
 `references/pixel-animation-workflows.md` for required phases before
 accepting generated art.
- Review row prompts before generation; wrong profile → fix request or pass
 `--art-profile`.
- Tiles/textures: zoomed-out repetition proof (prefer 3x3 for square tiles;
 surface-specific isometric checks).
- Character motion: full-speed GIF/runtime for loop pop, anchor jitter, noisy
 flicker, key-pose weakness.
- Combat: identify startup, active/contact, follow-through, recovery, overshoot
 — or explain why the state omits a phase.
- VFX: buildup/peak/decay and stable emitter/contact anchor.

Repair order:

1. Fix prompt/profile mismatch.
2. Regenerate only failing row.
3. Curate/reorder/select frames if the row has enough good keys.
4. Adjust extraction/registration if art is good but atlas is wrong.
5. Regenerate whole sheet only when identity, projection, palette, or core
 style language fails across multiple rows.
