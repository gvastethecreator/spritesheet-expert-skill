# Spritesheet Expert Workflows

## New Sheet Workflow

1. Pick preset or collect custom rows.
2. Create request JSON:

```bash
python scripts/preset_to_request.py platformer-character --out /abs/run/request.json
```

Tileset:

```bash
python scripts/preset_to_request.py tileset-topdown --out /abs/run/request.json
```

Texture:

```bash
python scripts/preset_to_request.py texture-pack --out /abs/run/request.json
```

Non-pixel:

```bash
python scripts/preset_to_request.py platformer-character --style-preset illustration --out /abs/run/request.json
```

Disable Pixel-art direction only when it conflicts with requested style:

```bash
python scripts/preset_to_request.py platformer-character --style-preset illustration --art-direction none --out /abs/run/request.json
```

Custom style:

```bash
python scripts/preset_to_request.py custom-atlas --style-preset custom --style "dark ink-wash game sprite, high contrast, rough brush edge" --out /abs/run/request.json --states-file /abs/run/states.json
```

Pixel-art profile, custom fighting row:

```bash
python scripts/preset_to_request.py custom-atlas --art-profile pixel-combat --out /abs/run/request.json --states-file /abs/run/states.json
```

For `custom-atlas` or `custom-asset-atlas`, pass explicit states:

```bash
python scripts/preset_to_request.py custom-atlas --out /abs/run/request.json --states-json '{"idle":{"frames":4,"fps":4,"loop":true,"action":"subtle idle"}}'
```

On Windows/PowerShell, prefer `--states-file /abs/states.json` to avoid JSON quoting loss.

3. Prepare run:

```bash
python scripts/prepare_sprite_run.py --out-dir /abs/run --character-id hero --base-image /abs/base.png --request /abs/run/request.json --force
```

`prepare_sprite_run.py` also accepts `--style-preset` and `--style`; request JSON wins over CLI args.

After preparation, inspect:

```text
references/art-direction.json
```

Must show the right row profiles before image generation. Fix the request or rerun with `--art-profile` if a combat, tile, VFX, top-down, side-view, isometric, tiny, UI/item, or shmup row is misclassified.

Also show the right `animation_workflows` per animated row. Fix state/action wording or add explicit `animation_workflows` if a row lacks its phase contract, e.g. `gesture-loop`, `sideview-locomotion`, `topdown-locomotion`, `combat-quick-strike`, `combat-power-strike`, `topdown-weapon-attack`, `responsive-jump`, `water-loop`, or `wind-ambient-loop`.

Static/set rows use a separate `production_workflows` field; never treat them as temporal animation. Preparation infers and injects these blocking contracts:

- `character-pose-set`: one camera/scale/identity and no blank declared slots;
- `topdown-direction-set`: elevated orthographic projection plus exact direction/contact order;
- `isometric-direction-set`: 2:1 dimetric projection plus diagonal order;
- `tileset-adjacency`: catalog `repeat_mode`, self-repeat proof, and role-aware adjacency review;
- `seamless-material-set`: full-bleed materials with numeric opposite-edge and 3x3 repeat proof.

If a provider retry still misses mathematical self-repeat edges, run `repair_repeat_edges.py` as an explicit post-process. For an existing frame it backs up provider art, leaves the semantic center unchanged, and harmonizes only the edge band. For a targeted Imagegen/Grok slot retry, pass `--phase-source-dir`: preserves an immutable provider copy, finds a periodic crop, then applies a narrow edge band. Both routes write hash evidence and still require labeled per-item 3x3 review. Not a replacement for provider generation.

When `asset_labels` are present, generated prompt contains an exact numbered slot inventory. Duplicate or blank slot does not satisfy the count.

Locomotion phase guides generate for 4-, 6-, and 8-frame cycles when state name/action/workflow indicates walk, run, move, advance, retreat, or dash. Do not accept a generated locomotion row that skipped these guides unless it is intentional non-legged/hovering motion with a separate visual rationale.

4. Generate one row per state or asset group with `$imagegen` by default. `$grok-imagine` is an explicit optional still/video route; read `grok-video-animation.md`, start with dry-run, and require a completed invocation manifest before ingestion.
   - Prompt: `prompts/<state>.txt`
   - Inputs: accepted base/anchor image plus `references/layout-guides/<state>.png`
   - Output path: `raw/<state>.png`
   - Accept provider output only via the executable source-intake contract. Intake checks expected job/state/kind, hashes the selected file, writes provenance; no prose-only inbox/outbox handoff.
   - Do not generate a whole atlas in one image for animated production unless the user asks for a sheet-level prototype/import. Generate per-state raw sheets; assemble the runtime atlas after QA.
   - Animated body rows: `prepare_sprite_run.py` writes `states.<state>.raw_layout`. Compact grids (`2x2`, `3x2`, `4x2`, `3x3`, `4x3`) are default — long raw `1xN` character strips drift and crop more often. Final atlas can still be a runtime row; raw generation and delivery shape are separate contracts.
   - New sprite component runs also write `background_removal.method: lucida` and `grid_segmentation: adaptive`. With no identity image, use the black fallback background. Read `lucida-adaptive-workflow.md` before changing pinned revision, alpha mode, threshold, or segmentation method.
   - Use `raw_layout_policy: "legacy-strip"` only for explicit low-risk compatibility/import; report that the row uses the weaker long-strip path.
   - Walk/run/advance/retreat: prefer 8 frames when quality matters. Use 4 or 6 only when the frame budget is intentional and the motion-phase guide still proves contact/pass/opposite-contact logic.
   - If the selected provider has no local accepted file in the current turn, report that the generated-art path cannot be completed honestly yet; do not substitute a scripted drawing.
   - After copying accepted still outputs into `raw/`, write `source-provenance.json` with exact provider/source type and accepted source paths.
   - If no user/base image, generate only the neutral `idle` or closest standing identity row first. Review it, copy to `raw/idle.png`, then promote frame 0 before action rows:

```bash
python scripts/promote_identity_anchor.py --run-dir /abs/run --state idle --frame 0 --allow-slot-fallback
```

   - For every later row, attach or show `references/identity-anchor.png` to `$imagegen` as the canonical character identity reference. Row prompt and layout guide define motion/pose; identity anchor defines face, outfit, palette, proportions, outline weight, and scale.

5. Gate provenance, extract, compose, preview:

```bash
python scripts/check_generation_provenance.py --run-dir /abs/run
```

```bash
python scripts/extract_sprite_row_frames.py --run-dir /abs/run
python scripts/compose_sprite_atlas.py --run-dir /abs/run
python scripts/preview_animation.py --run-dir /abs/run
python scripts/check_frame_alignment.py --run-dir /abs/run
python scripts/check_identity_consistency.py --run-dir /abs/run
python scripts/check_animation_contracts.py --run-dir /abs/run
python scripts/render_runtime_preview.py --run-dir /abs/run --state idle --kind runtime-playback
python scripts/build_preview_workbench.py --run-dir /abs/run --force
python scripts/validate_run.py --run-dir /abs/run --stage post-extract
```

Render runtime playback once per animated state, then build or rebuild the workbench after final QA artifacts exist. Otherwise the self-contained workbench can omit late reports or playback evidence.

After packaging and recording hash-bound visual review, run the final gate:

```bash
python scripts/validate_run.py --run-dir /abs/run --stage pre-package
```

For dirty generated backgrounds or imported rows:

```bash
python scripts/extract_sprite_row_frames.py --run-dir /abs/run --background-removal auto
```

`rembg` no longer runs post-chroma cleanup by default because it can erase legitimate subject pixels. Use `--post-rembg-chroma-cleanup` only after visual review proves remaining key color is border/background residue.

Preferred new Imagegen sprite lane: install Lucida; request is source of truth:

```bash
python -m pip install -r scripts/requirements-lucida.txt
python scripts/extract_sprite_row_frames.py --run-dir /abs/run
```

Review `qa/<state>-adaptive-segmentation.png` before composition. Every colored box must contain one complete pose and its related detached parts. Do not approve `grid-slots-fallback` for a production sprite row.

If the game runtime cell uses a different bottom or pivot, run `register_sprite_frames.py` with that explicit target after extraction. Compose and validate the registered output directory. See `lucida-adaptive-workflow.md` for the full command sequence and the `512x512`, bottom `440` example.

Final/high-risk mattes where rembg/BiRefNet still eats hair, fur, spikes, small limbs, or painterly outlines: switch explicitly to BEN2:

```bash
python scripts/extract_sprite_row_frames.py --run-dir /abs/run --background-removal ben2 --background-model PramaLLC/BEN2 --background-device auto
```

Backend name is not proof. Review `qa/background-matte-review.png` on checker, black, gray, white, and alpha-mask panels before atlas composition.

New generation must use a flat neutral gray, black, or white background. Lucida is the preferred new sprite model. `birefnet-general` remains the quality default for the `auto` compatibility lane. `birefnet-general-lite` is an explicit speed option. Chroma mode is for declared legacy imports only.

For animated sprites with walk/run/move rows, also run:

```bash
python scripts/check_motion_variation.py --run-dir /abs/run
```

`check_frame_alignment.py`: real-frame/onion-skin gate. Reads `frames/frames-manifest.json` after extraction; writes `qa/frame-alignment-report.json` plus `qa/<state>-onion.png`. Jump: takeoff and landing must return to same shared baseline; airborne frames may leave it only as a visible arc. Fall/knockdown: final frame must settle on the baseline. Grounded rows: feet/body bottom should not drift unless the state intentionally changes ground contact. If JSON passes but onion skin shows root drift, clipped frames, or bad takeoff/landing closure, the row still fails visual QA.

`check_identity_consistency.py`: head/body consistency gate. Reads extracted frame records; blocks rows where head width, upper-body width, or opaque area drift far from the idle reference. Use especially after regenerating action, jump, crouch, hitstun, knockdown, and locomotion rows: changing head size is a failed row, not polish.

`check_animation_contracts.py`: broad workflow gate. Pass for every animated row that has or infers an `animation_workflow`. Catches hard phase failures: duplicated locomotion contacts, static attacks, missing jump travel, static hit reactions, flat VFX, dead ambient loops. Lower-body screen-side balance is only a freeze/variation diagnostic: confirm opposite anatomical support legs through chronological playback and crossover/depth-swap continuity. Report lists those required visual checks.

For user-facing animated sprite runs, render hash-bound runtime playback evidence for every state and open `qa/preview-workbench/index.html`. Use pause, step, scrub, speed, zoom, state selection, complete filmstrip, and checker/black/gray/white backgrounds. Check: animation reads during playback, not only in a contact sheet.

## Video Animation Workflow

Common video lane for Grok and existing video files. Read `video-animation-workflow.md` before this workflow.

Import an existing video:

```bash
python scripts/ingest_video_animation.py --run-dir /abs/run --state walk --video /abs/source/walk.mp4 --first-frame /abs/source/idle.png
```

Analyzes every decoded frame; creates several candidate cycles and the required selector.

Open `qa/<state>-video-frame-selector/index.html`. Select a candidate or replace individual frames.

Re-ingest reviewed indices with `--sample-indices` and `--force`. Does not run provider inference.

### Grok Provider

After accepting one exact neutral-background first frame, prepare the provider job:

```bash
python scripts/prepare_grok_video_animation.py --repo-root /abs/project --run-dir /abs/run --state walk --first-frame provider/grok-imagine/walk/first-frame.png
```

Run the generated `$grok-imagine` arguments with `--dry-run`. Add `--ack-run` only with explicit current-task consent. After the wrapper reports a completed run with exactly one copied video, ingest its manifest:

```bash
python -m pip install -r scripts/requirements-video.txt
python scripts/ingest_grok_video_animation.py --run-dir /abs/run --state walk --invocation /abs/project/.scratch/agent-cli-delegation/grok-imagine/spritesheet-video/<run>/invocation.json
```

Grok command creates the same selector. Then return to step 5.

Video extraction removes background per selected frame. Uses safe alpha crops and blocks source-edge contact.

See `grok-video-animation.md` for Grok consent and provenance checks.

For runs with `art_direction.mode: pixel-art`, add the relevant critique pass:

- tiles/textures: zoomed-out 3x3 repetition and edge compatibility;
- character motion: active workflow phases, full-speed loop seam, key-pose energy, anchor jitter, and noisy flicker;
- locomotion: contact/down/pass/swing or top-down direction/bounce workflow, with no same-leg repetition;
- combat: stance/load if needed, smear direction, hit/contact, follow-through, recovery, overshoot, and visual-hitbox match;
- VFX/water/wind: buildup/peak/decay, stable emitter/contact or flow point, and loop math;
- tiny sprites: no unnecessary frames/detail beyond readable silhouette and one-pixel motion.

6. Launch curation unless user asked for unattended batch:

```bash
python scripts/serve_curation.py --run-dir /abs/run
```

If user edits in curation, re-run compose. Compose reads `curation.json` automatically.

## Existing Sheet Or Asset Workflow

When only a finished atlas or candidate PNG folder exists. Imports real art; does not satisfy generated-art provenance unless the imported source is explicitly imagegen-backed.

```bash
python scripts/unpack_atlas_run.py --atlas /abs/sheet.png --out-dir /abs/sheet-curator --diagnostic --force
python scripts/check_generation_provenance.py --run-dir /abs/sheet-curator --allow-imported-source
python scripts/serve_curation.py --run-dir /abs/sheet-curator
```

Prefer exact inputs when available:

- `--manifest manifest.json`: existing `frame_layout`.
- `--grid 8x9`: slice uniform cells only when the source sheet is truly grid-exact and dimensions divide cleanly.
- `--boxes-file authored-boxes.json --atlas sheet.png`: reviewed manual source rectangles after visual curation fixes bad cuts.
- `--projection-grid 8x4 --atlas sheet.png`: split each expected row by alpha projection and DP repair when the sheet has uneven gutters or touching poses. Repair/diagnostic bridge; review `qa/segmentation-overlay.png` and promote accepted boxes before final packaging.
- no grid/manifest: alpha auto-detect. Diagnostic for imagegen/imported whole sheets with non-standard dimensions, uneven gutters, or visible row/column drift. Do not treat auto-detected rectangles as production cuts until the segmentation overlay is reviewed and converted to a trusted manifest/grid/authored boxes.
- `--pngs-dir folder`: curate loose PNG candidates or still assets; imports as `asset_kind: asset` with slot extraction.

Before composing an imported sprite sheet, matte/segment it, then register frames to a stable runtime pivot:

```bash
python scripts/unpack_atlas_run.py --atlas /abs/sheet.png --states walk-down,walk-left,walk-right,walk-up --background-removal auto --out-dir /abs/sheet-auto --diagnostic --force
python scripts/register_sprite_frames.py --run-dir /abs/sheet-auto --out-dir /abs/sheet-registered --cell 256x256 --anchor body-bottom --force
python scripts/compose_sprite_atlas.py --run-dir /abs/sheet-registered
```

For hard imported sheets where auto/rembg leaves scenery or cuts the subject, rerun unpacking with explicit BEN2 and compare the segmentation overlay:

```bash
python scripts/unpack_atlas_run.py --atlas /abs/sheet.png --states walk-down,walk-left,walk-right,walk-up --background-removal ben2 --background-model PramaLLC/BEN2 --background-device auto --out-dir /abs/sheet-ben2 --diagnostic --force
```

Review `qa/preprocessed-atlas-alpha.png`, `qa/segmentation-overlay.png`, and `qa/segmentation-report.json` before registration. If overlay boxes are wrong, or the report says auto-detect is the layout source, do not proceed as production alignment; fix background removal, pass a trusted manifest/grid, author exact boxes, or regenerate/import cleaner separated frames.

Projection repair for a known 4-row, 8-frame-per-row sheet with uneven gutters:

```bash
python scripts/unpack_atlas_run.py --atlas /abs/sheet.png --projection-grid 8x4 --states idle,walk,attack,hurt --background-removal auto --out-dir /abs/sheet-projection --diagnostic --force
```

If the projection overlay is visually correct, convert accepted rectangles to authored boxes JSON and rerun:

```bash
python scripts/unpack_atlas_run.py --atlas /abs/sheet.png --boxes-file /abs/authored-boxes.json --out-dir /abs/sheet-authored --force
```

## Isometric Tileset Workflow

Read `references/isometric-tilesets.md` before generating, importing, or reviewing isometric terrain, props, decor, or buildings.

Do not generate a full game scene and cut it into tiles. Generate grouped rows with clean slots:

- base terrain variants;
- edges, corners, raised ledges, ramps, or height transitions;
- hazards, overlays, decals, roads, water, bridges;
- props/decor/building pieces as separate asset rows.

Before image generation, `prepare_sprite_run.py` must preserve `asset_catalog` and reject isometric requests whose `asset_catalog.tile.runtimeCell` does not match `request.cell`. For isometric rows, the layout guide includes a 2:1 diamond and floor/contact pivot so `$imagegen` aligns each slot before extraction.

Prepare labels and catalog metadata before slicing. Catalog must declare 2:1 footprint, runtime cell, per-slot pivot, category, collision, and tile/edge role:

```json
{
  "projection": "2:1 isometric",
  "tile": {"width": 128, "height": 64, "runtimeCell": [224, 224]},
  "items": {
    "grass-flat": {"category": "terrain", "tile_role": "base", "collision": "walkable", "pivot": [112, 168]},
    "north-edge": {"category": "terrain-edge", "edge_role": "north", "collision": "ledge", "pivot": [112, 168]}
  }
}
```

Import only with exact grid, trusted manifest, or authored boxes. If dimensions do not divide the declared grid, that is a failed slice, not an alignment issue:

```bash
python scripts/unpack_atlas_run.py --atlas /abs/terrain.png --out-dir /abs/terrain-run --grid 8x4 --asset-kind tileset --extraction-mode slots --asset-labels-file /abs/terrain-labels.json --asset-catalog-file /abs/terrain-catalog.json --background-removal auto --force
python scripts/check_generation_provenance.py --run-dir /abs/terrain-run
python scripts/compose_sprite_atlas.py --run-dir /abs/terrain-run
python scripts/check_asset_slots.py --run-dir /abs/terrain-run
python scripts/check_isometric_tiles.py --run-dir /abs/terrain-run
```

`check_isometric_tiles.py` also writes `qa/isometric-runtime-metadata.json` and `qa/isometric-calibrated-catalog.json`. Use runtime metadata for prototypes immediately. If the calibrated catalog changes footprint or pivots, review overlay/map/depth images, copy approved values back into the source catalog, then rerun unpack, compose, and isometric QA before final packaging.

For isometric props/decor, use `asset_kind: asset` and still run slot QA:

```bash
python scripts/unpack_atlas_run.py --atlas /abs/props.png --out-dir /abs/props-run --grid 6x4 --asset-kind asset --extraction-mode slots --asset-labels-file /abs/props-labels.json --asset-catalog-file /abs/props-catalog.json --background-removal auto --force
python scripts/check_asset_slots.py --run-dir /abs/props-run
```

For 2D/top-down/side-view prop packs, classify every catalog item before generation with `strategy_class`:

- `compact_prop`: can use square `2x2`, `3x3`, or `4x4` packs.
- `wide_or_long_object`, `tall_or_large_object`, `collision_bearing_object`, `tileset_or_strip_piece`: do not approve inside square compact packs; generate one-by-one, as a platform/edge strip, custom wide cells, or a tileset-like atlas.

`check_asset_slots.py` blocks missing/invalid `strategy_class` for asset/prop catalog items and records `edge_touch` for each slot.

Required visual review:

- `qa/segmentation-overlay.png`: grid/cuts match the source.
- `qa/asset-slot-overlay.png`: each label, bbox, and pivot is correct.
- `qa/tile-repeat-review.png` and `qa/tile-repeat-items/<label>.png`: every self-repeat item shown in both overview and labeled 3x3 isolation.
- `qa/asset-slot-review.json.repeat_validation`: numeric edge coverage and opposite-edge error for every `repeat_mode=self` tile/texture. `adjacency` and `overlay` remain explicit hash-bound visual-review work, not silently approved by the montage.
- `qa/tile-adjacency-review.png`: distinct catalog `tile_role` values build a role-aware edge/corner/slope/platform review for adjacency tiles.
- `qa/isometric-pivot-overlay.png`: every tile has a 2:1 footprint on the visual floor.
- `qa/isometric-map-review.png`: base/detail/hazard tiles compose into a coherent map.
- `qa/isometric-depth-review.png`: raised/height tiles sort correctly.
- `qa/isometric-runtime-metadata.json`: prototype/importer uses calibrated footprint and pivots.
- `qa/isometric-calibrated-catalog.json`: reviewed values copied back to the source catalog before final packaging.

Prototype renderers must draw from catalog pivots, not top-left cell placement:

```text
center_x = origin_x + (col - row) * tile_width / 2
center_y = origin_y + (col + row) * tile_height / 2 - z_height
object_anchor_y = center_y + tile_height / 2
draw_x = center_x - pivot_x
draw_y = object_anchor_y - pivot_y
```

Sort by `row + col + z_offset`, then stable source order. Use `qa/isometric-runtime-metadata.json.tile` and `items[*].pivot` when generated frames prove the catalog footprint/pivot is stale. Do not prototype from rectangular top-left placement or image-center anchoring.

Use `--anchor body-bottom` for top-down and side-view humanoid sprites: X from torso/body mass, Y locks the bottom baseline, so the actor is stable and legs can still animate inside the slot. Use `--anchor footprint` only when pinning the active contact point is the runtime intent.

Registration treats target-cell clipping as failure by default. Use `--allow-clipping` only for deliberate VFX/partial-frame assets after visual review.

After still curation:

```bash
python scripts/export_curated_pngs.py --run-dir /abs/sheet-curator
```
