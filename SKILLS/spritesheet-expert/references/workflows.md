# Spritesheet Expert Workflows

## Existing transparent item sheet

Use [Local item-sheet workflow](local-model-item-workflow.md) to import an irregular sheet, propose visual groups with local models, review source masks, classify sprites and export a size-ordered rectangular atlas. Studio and CLI share the same staged runner. Model errors and unassigned pixels remain visible; export a draft until review is complete.

## New Sheet Workflow

Use a new run directory and keep the planning request and states file outside it. `prepare_sprite_run.py --force` removes known outputs, including frames, QA and provider records; it is not a routine retry. Use a successor run unless replacing that exact existing output set is authorized.

1. Pick preset or collect custom rows.
2. Create request JSON:

```bash
python scripts/preset_to_request.py platformer-character --out /abs/request.json
```

Tileset:

```bash
python scripts/preset_to_request.py tileset-topdown --out /abs/request.json
```

Texture:

```bash
python scripts/preset_to_request.py texture-pack --out /abs/request.json
```

Non-pixel:

```bash
python scripts/preset_to_request.py platformer-character --style-preset illustration --out /abs/request.json
```

Disable Pixel-art direction only when it conflicts with requested style:

```bash
python scripts/preset_to_request.py platformer-character --style-preset illustration --art-direction none --out /abs/request.json
```

Custom style:

```bash
python scripts/preset_to_request.py custom-atlas --style-preset custom --style "dark ink-wash game sprite, high contrast, rough brush edge" --out /abs/request.json --states-file /abs/states.json
```

Pixel-art profile, custom fighting row:

```bash
python scripts/preset_to_request.py custom-atlas --art-profile pixel-combat --out /abs/request.json --states-file /abs/states.json
```

For `custom-atlas` or `custom-asset-atlas`, pass explicit states:

```bash
python scripts/preset_to_request.py custom-atlas --out /abs/request.json --states-json '{"idle":{"frames":4,"fps":4,"loop":true,"action":"subtle idle"}}'
```

On Windows/PowerShell, prefer `--states-file /abs/states.json` to avoid JSON quoting loss.

3. Prepare run:

```bash
python scripts/prepare_sprite_run.py --out-dir /abs/run --character-id hero --base-image /abs/base.png --request /abs/request.json
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

If repeat review finds a seam, use `repair_repeat_edges.py` as an explicit post-process. Edge-only mode preserves the decoded center of its original-frame backup; `--force` reproduces that baseline. Each record reports the effective blend/strip widths. For a targeted Imagegen/Grok retry, `--phase-source-dir` preserves a source copy, selects a crop through RGB boundary heuristics, then blends a narrow edge band. Trim ratio is a per-side budget; zero keeps the whole source. Both modes need labeled 3x3 review and fresh downstream QA. Neither proves provider generation or semantic continuity.

When `asset_labels` are present, generated prompt contains an exact numbered slot inventory. Duplicate or blank slot does not satisfy the count.

Locomotion phase guides generate for 4-, 6-, and 8-frame cycles when state name/action/workflow indicates walk, run, move, advance, retreat, or dash. Do not accept a generated locomotion row that skipped these guides unless it is intentional non-legged/hovering motion with a separate visual rationale.

4. Generate one row per state or asset group with `$imagegen` by default. Grok Imagine is an explicit optional still/video route; read `grok-video-animation.md`, start with a dry run or preview, and require a completed provider run record before ingestion.
   - Prompt: `prompts/<state>.txt`
   - Inputs: accepted base/anchor image plus `references/layout-guides/<state>.png`
   - Output path: `raw/<state>.png`
   - Accept provider output only via the executable source-intake contract. Intake checks expected job/state/kind, hashes the selected file, writes provenance; no prose-only inbox/outbox handoff.
   - Do not generate a whole atlas in one image for animated production unless the user asks for a sheet-level prototype/import. Generate per-state raw sheets; assemble the runtime atlas after QA.
   - Animated body rows: `prepare_sprite_run.py` writes `states.<state>.raw_layout`. Compact grids (`2x2`, `3x2`, `4x2`, `3x3`, `4x3`) are the configured default; inspect identity, separation and cropping on the actual result. Final atlas can still be a runtime row; raw generation and delivery shape are separate contracts.
   - New isolated component art requests native alpha first. Use `background_removal.method: alpha` when it passes review and `grid_segmentation: adaptive` for uneven bounds. If alpha is absent or invalid, select the neutral Lucida fallback. Read `lucida-adaptive-workflow.md` before changing revision, alpha mode, threshold, or segmentation.
   - Use `raw_layout_policy: "legacy-strip"` only for explicit low-risk compatibility/import; record the selected raw layout and review its actual output.
   - Walk/run/advance/retreat: preserve the accepted frame budget. Motion references guide pose planning; actual chronological playback must show contact, pass and opposite support phases.
   - If no verifiable accepted local source exists, record that blocker; reuse valid earlier sources and receipts rather than regenerating them merely because a turn changed; do not substitute a scripted drawing.
   - Let `scripts/ingest_source.py` write the accepted raw file and its provenance. Retain the actual provider receipt; do not manufacture a verified record after a manual copy.
   - Writes are atomic per file, not a transaction across the run. On failure, inspect `mutated` before retrying; `true` means an output was already written.
   - If no user/base image, generate only the neutral `idle` or closest standing identity row first. Review it, copy to `raw/idle.png`, then promote frame 0 before action rows:

```bash
python scripts/promote_identity_anchor.py --run-dir /abs/run --state idle --frame 0
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

`rembg` no longer runs post-chroma cleanup by default because it can erase legitimate subject pixels. Use `--post-rembg-chroma-cleanup` only for declared `legacy-chroma` sources after visual review proves the residue belongs to the background.

For a source that needs the Lucida fallback, prepare the locked optional runtime
and checkpoint as described in `../model-runtime/README.md`. Use its Python:

```bash
python scripts/extract_sprite_row_frames.py --run-dir /abs/run
```

Review `qa/<state>-adaptive-segmentation.png` before composition. Every colored box must contain one complete pose and its related detached parts. Do not approve `grid-slots-fallback` for a production sprite row.

If the game runtime cell uses a different bottom or pivot, run `register_sprite_frames.py` with that explicit target after extraction. Compose and validate the registered output directory. See `lucida-adaptive-workflow.md` for the full command sequence and the `512x512`, bottom `440` example.

Final/high-risk mattes where rembg/BiRefNet still eats hair, fur, spikes, small limbs, or painterly outlines: switch explicitly to BEN2:

```bash
python scripts/extract_sprite_row_frames.py --run-dir /abs/run --background-removal ben2 --background-model PramaLLC/BEN2 --background-device auto
```

Backend name is not proof. Review `qa/background-matte-review.png` on checker, black, gray, white, and alpha-mask panels before atlas composition.

Keep verified native alpha. When it is absent or invalid, the fallback uses flat
neutral gray, black, or white. Lucida and BEN2 require prepared local checkpoints;
compare their mattes on the actual source. Chroma is for declared legacy imports only.

For animated sprites with walk/run/move rows, also run:

```bash
python scripts/check_motion_variation.py --run-dir /abs/run
```

`check_frame_alignment.py`: real-frame/onion-skin gate. Reads `frames/frames-manifest.json` after extraction; writes `qa/frame-alignment-report.json` plus `qa/<state>-onion.png`. Jump: takeoff and landing must return to same shared baseline; airborne frames may leave it only as a visible arc. Fall/knockdown: final frame must settle on the baseline. Grounded rows: feet/body bottom should not drift unless the state intentionally changes ground contact. If JSON passes but onion skin shows root drift, clipped frames, or bad takeoff/landing closure, the row still fails visual QA.

`check_identity_consistency.py`: compares recorded head, upper-body, body-mass and area ratios with configured reference limits. It requires a record per requested frame and finite numeric proxies. Missing evidence remains incomplete; `--allow-missing-proxies` keeps partial diagnostics. These records do not prove current pixel identity: review the regenerated frames and playback. A hash-bound visual review may accept exact proxy false positives; it cannot waive malformed or missing records.

`check_animation_contracts.py`: workflow gate for animated rows with declared or inferred workflows. It checks counts, alpha/visible-pixel variation and bounding-box motion against configured thresholds. Invalid inputs, missing states/frames and rows with no analyzable foreground remain incomplete even with `--warn-only`. VFX may have transparent fade endpoints. Lower-body screen-side balance is diagnostic: confirm anatomical support, timing and pose semantics through chronological playback. Passing these metrics does not prove those visual properties.

For user-facing animated sprite runs, render hash-bound runtime playback evidence for every state and open `qa/preview-workbench/index.html`. Use pause, step, scrub, speed, zoom, state selection, complete filmstrip, and checker/black/gray/white backgrounds. Check: animation reads during playback, not only in a contact sheet.

## Video Animation Workflow

Follow [the video workflow](video-animation-workflow.md) for imports, frame selection, extraction and evidence. For a selected Grok provider, use [its adapter workflow](grok-video-animation.md) for preparation, consent and invocation checks. Return to the common atlas/QA path after ingestion.

## Review And Curation

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
python scripts/unpack_atlas_run.py --atlas /abs/sheet.png --out-dir /abs/sheet-curator --diagnostic
python scripts/check_generation_provenance.py --run-dir /abs/sheet-curator --allow-imported-source
python scripts/serve_curation.py --run-dir /abs/sheet-curator
```

Prefer exact inputs when available:

- `--manifest manifest.json`: existing `frame_layout`.
- `--grid 8x9`: slice uniform cells only when the source sheet is truly grid-exact and dimensions divide cleanly. Every declared cell and row is retained, including transparent ones, so frame positions and counts stay explicit.
- `--boxes-file authored-boxes.json --atlas sheet.png`: reviewed manual source rectangles after visual curation fixes bad cuts.
- `--projection-grid 8x4 --atlas sheet.png`: split each expected row by alpha projection and DP repair when the sheet has uneven gutters or touching poses. Repair/diagnostic bridge; review `qa/segmentation-overlay.png` and promote accepted boxes before final packaging.
- no grid/manifest: alpha auto-detect. Diagnostic for imagegen/imported whole sheets with non-standard dimensions, uneven gutters, or visible row/column drift. Do not treat auto-detected rectangles as production cuts until the segmentation overlay is reviewed and converted to a trusted manifest/grid/authored boxes.
- `--pngs-dir folder`: curate loose PNG candidates or still assets; imports as `asset_kind: asset` with slot extraction.

Imports validate source images, rectangles, labels, and the request before replacing known outputs. Rectangles must use integer pixel coordinates, fit the source, and fit the target cell. `--cell WxH` supplies or overrides a manifest's cell size. Renaming states retains their timing metadata. The copied source and its hash use the same captured bytes as decoding; they prove imported bytes, not provider generation or cut quality. `--force` requires an owned run and its writer lock; inputs inside outputs to be replaced require another output directory. A selected root `manifest.json` is preserved.

Before composing an imported sprite sheet, matte/segment it, then register frames to a stable runtime pivot:

```bash
python scripts/unpack_atlas_run.py --atlas /abs/sheet.png --states walk-down,walk-left,walk-right,walk-up --background-removal auto --out-dir /abs/sheet-auto --diagnostic
python scripts/register_sprite_frames.py --run-dir /abs/sheet-auto --out-dir /abs/sheet-registered --cell 256x256 --anchor body-bottom
python scripts/compose_sprite_atlas.py --run-dir /abs/sheet-registered
```

For hard imported sheets where auto/rembg leaves scenery or cuts the subject, rerun unpacking with explicit BEN2 and compare the segmentation overlay:

```bash
python scripts/unpack_atlas_run.py --atlas /abs/sheet.png --states walk-down,walk-left,walk-right,walk-up --background-removal ben2 --background-model PramaLLC/BEN2 --background-device auto --out-dir /abs/sheet-ben2 --diagnostic
```

Review `qa/preprocessed-atlas-alpha.png`, `qa/segmentation-overlay.png`, and `qa/segmentation-report.json` before registration. If overlay boxes are wrong, or the report says auto-detect is the layout source, do not proceed as production alignment; fix background removal, pass a trusted manifest/grid, author exact boxes, or regenerate/import cleaner separated frames.

Projection repair for a known 4-row, 8-frame-per-row sheet with uneven gutters:

```bash
python scripts/unpack_atlas_run.py --atlas /abs/sheet.png --projection-grid 8x4 --states idle,walk,attack,hurt --background-removal auto --out-dir /abs/sheet-projection --diagnostic
```

If the projection overlay is visually correct, convert accepted rectangles to authored boxes JSON and rerun:

```bash
python scripts/unpack_atlas_run.py --atlas /abs/sheet.png --boxes-file /abs/authored-boxes.json --out-dir /abs/sheet-authored
```

## Isometric Tileset Workflow

Follow [the isometric guide](isometric-tilesets.md) for the grid/catalog contract, generation, exact imports, provenance checks, calibrated placement and map/depth review. Use `asset_kind: asset` for isolated props/decor and retain slot QA.

## Prop Catalog Strategy

For 2D/top-down/side-view prop packs, classify every catalog item before generation with `strategy_class`:

- `compact_prop`: can use square `2x2`, `3x3`, or `4x4` packs.
- `wide_or_long_object`, `tall_or_large_object`, `collision_bearing_object`, `tileset_or_strip_piece`: do not approve inside square compact packs; generate one-by-one, as a platform/edge strip, custom wide cells, or a tileset-like atlas.

`check_asset_slots.py` blocks missing/invalid `strategy_class` for asset/prop catalog items and records `edge_touch` for each slot.

Use [the QA outputs guide](qa-and-outputs.md) for current slot, repeat, adjacency and visual evidence requirements. Isometric placement and metadata follow the linked isometric guide.

## Registration And Export

Use `--anchor body-bottom` for top-down and side-view humanoid sprites: X from torso/body mass, Y locks the bottom baseline, so the actor is stable and legs can still animate inside the slot. Use `--anchor footprint` only when pinning the active contact point is the runtime intent.

Registration treats target-cell clipping as failure by default. Use `--allow-clipping` only for deliberate VFX/partial-frame assets after visual review.

After still curation:

```bash
python scripts/export_curated_pngs.py --run-dir /abs/sheet-curator
```
