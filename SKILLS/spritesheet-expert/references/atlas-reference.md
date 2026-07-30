# Spritesheet Expert Reference

## Background Removal

New generation uses one perfectly flat neutral background: gray `#808080`, black `#000000`, or white `#FFFFFF`. `prepare_sprite_run.py` chooses the neutral color with the greatest contrast from the accepted reference, with gray as the no-reference fallback. The prompt forbids gradients, texture, vignettes, floor planes, cast shadows, and background lighting variation. It does not ban black, gray, or white from the subject palette.

Default method is `auto`:

1. preserve trustworthy source alpha;
2. for `source_family: neutral`, remove a simple flat border with an edge-connected matte;
3. otherwise use `rembg` with `birefnet-general`;
4. use BEN2 only when selected explicitly for a hard/final comparison.

The matte flood-fill touches only edge-connected palette regions, so neutral clothing, outlines, highlights, inner holes, and props are not erased globally. Ambiguous, dirty, anti-aliased, photographic, or breathing video backgrounds should reach BiRefNet. Model-backed removal is still evidence to review, not an excuse to accept a busy source: if it clips hair, fur, spikes, limbs, outlines, clothing, props, tile edges, or interiors, regenerate a cleaner neutral source or compare a different model.

Chroma is legacy-import compatibility only. A legacy request must declare `background_removal.source_family: legacy-chroma` or select `background_removal.method: chroma` explicitly in the import/unpack path. New preparation rejects chroma generation and never auto-selects the chroma branch for neutral sources. Legacy chroma still uses a border-connected soft matte/despill; keep `check_chroma_key_safety.py`, `rekey_chroma_background.py`, and `check_visible_magenta.py` only for those old sources.

Do not run chroma cleanup after `rembg` on neutral sources. `post_rembg_chroma_cleanup` is valid only for declared `legacy-chroma` media; applying it to neutral art can erase legitimate subject pixels.

Recommended local model stack:

- `rembg` + `birefnet-general`: quality default.
- `rembg` + `birefnet-general-lite`: explicit speed option for iteration.
- `rembg` + `birefnet-dis` or `birefnet-hrsod`: hard silhouettes, high-resolution objects, or irregular source sheets where general-lite leaves background.
- `rembg` + `isnet-anime`: anime/cel character rows when BiRefNet clips linework.
- `ben2` + `PramaLLC/BEN2`: optional higher-quality local matting/refinement path for hair, fur, spikes, painterly edges, 4K-ish inputs, dirty generated backgrounds, and imported irregular sheets. It is heavier than rembg and needs PyTorch.
- `bria-rmbg` / BRIA RMBG 2.0: strong quality candidate, but the publicly available weights are non-commercial and production/commercial use needs a BRIA agreement/API. Do not make it a silent default.

Install only when needed:

```bash
pip install "rembg[cpu]"
pip install git+https://github.com/PramaLLC/BEN2.git
```

Then enable it explicitly when final quality matters or when source sheets are irregular/non-flat:

```bash
python scripts/preset_to_request.py custom-atlas --background-removal rembg --background-model birefnet-general --out /abs/run/request.json --states-file /abs/run/states.json
python scripts/prepare_sprite_run.py --out-dir /abs/run --character-id hero --request /abs/run/request.json --force
python scripts/extract_sprite_row_frames.py --run-dir /abs/run

python scripts/preset_to_request.py custom-atlas --background-removal ben2 --background-model PramaLLC/BEN2 --out /abs/run/request.json --states-file /abs/run/states.json
python scripts/prepare_sprite_run.py --out-dir /abs/run --character-id hero --request /abs/run/request.json --force
python scripts/extract_sprite_row_frames.py --run-dir /abs/run --background-device auto
```

`extract_sprite_row_frames.py` defaults to `auto`: existing alpha first, edge-connected matte for simple flat neutral borders, and `rembg` for ambiguous backgrounds. The chroma branch runs only for `source_family: legacy-chroma`. Tune the matte fallback with `--matte-threshold` and `--matte-max-colors` when a neutral source has small numeric variation. If `rembg` is requested or selected by `auto` but not installed, fail clearly instead of silently using bad alpha. Review `frames/frames-manifest.json.background_removal.source_family`, `model`, and `matte_mask`.

`ben2` is never selected silently by `auto`; choose it explicitly for final/high-risk cutouts after a BiRefNet pass fails visual QA. It writes `background_method: ben2` into manifests and uses `background_removal.device` (`auto`, `cpu`, `cuda`, `cuda:0`, etc.) so slow CPU cutouts are not mistaken for a broken pipeline.

Every extraction writes `qa/background-matte-review.png`. Review raw source, checker, black, gray, white, and alpha-mask panels before judging atlas quality. The six surfaces should preserve outline pixels, interior holes, props, hair/fur/spikes, and tiny limbs without background residue.

For imported whole sheets, `unpack_atlas_run.py` defaults to background-removal
`auto` when using alpha auto-detect. It writes `qa/preprocessed-atlas-alpha.png`,
`qa/segmentation-overlay.png`, and `qa/segmentation-report.json` so cuts can be
reviewed before registration/composition. Auto-detect boxes are diagnostic: they
are not a production layout source for irregular imagegen sheets unless a human
reviews and converts them into a trusted manifest, explicit grid, or authored
boxes. Use `--background-removal none` only for trusted alpha, manifest, or
exact-grid sheets.

## Generation Provenance

Generated production art must be backed by `$imagegen` or an explicitly selected
`$grok-imagine` invocation. Procedural/PIL drawing is only a fixture path.

Record accepted source art before extraction:

```json
{
  "version": 2,
  "kind": "sprite-source-provenance",
  "source_type": "imagegen",
  "art_engine": "imagegen",
  "fixture": false,
  "verification_status": "verified",
  "accepted_sources": [
    {
      "path": "raw/idle.png",
      "sha256": "<64 lowercase hex characters>",
      "size_bytes": 12345,
      "states": ["idle"]
    },
    {
      "path": "raw/run.png",
      "sha256": "<64 lowercase hex characters>",
      "size_bytes": 23456,
      "states": ["run"]
    }
  ],
  "state_coverage": ["idle", "run"],
  "notes": "selected imagegen row strips copied into this run"
}
```

Then gate the run:

```bash
python scripts/check_generation_provenance.py --run-dir /abs/run
```

For explicit existing/user-provided sheets, use:

```bash
python scripts/check_generation_provenance.py --run-dir /abs/run --allow-imported-source
```

For smoke fixtures only:

```bash
python scripts/check_generation_provenance.py --run-dir /abs/run --allow-fixture
```

Do not invent hashes or reuse this example literally. The executable source-intake command computes provenance from accepted files; legacy v1 provenance loads only as `legacy-unverified` and cannot satisfy production QA.

## Style Presets

Default style is `pixel-art`. Pixel art is optional: choose a different style when the user asks for realistic, illustrated, painterly, anime, vector-like, custom sprites, or custom asset art.

Built-ins:

- `pixel-art`: default; low-res, chunky outline, limited palette.
- `illustration`: clean 2D game illustration/cel shading.
- `painterly`: stylized brushy game sprite.
- `realistic`: semi-realistic isolated game sprite.
- `anime`: anime-inspired 2D game sprite.
- `vector`: flat vector-like game sprite.
- `custom`: use `--style` text as the contract.

Keep atlas constraints stable: one row per state or asset group, flat neutral source background where transparency is needed, no text, no scene background, no guide marks, no slot overlap.

Sprites use `asset_kind: sprite` and component extraction. Tiles, textures, icons, props, VFX, and full-cell assets use `asset_kind` plus `extraction_mode: slots` so full-cell art does not depend on connected-component detection.

Raw generation shape is not the same as final delivery shape. Animated body
rows default to compact raw grids recorded in `states.<state>.raw_layout`
because long `1xN` imagegen strips drift, touch, and crop more often. The final
runtime atlas remains `manifest.json.frame_layout` rows after deterministic
composition. Use legacy raw strips only for explicit compatibility or low-risk
fixture work.

## Pixel-Art Direction Profiles And Workflows

Pixel-art presets default to `art_direction.mode: pixel-art`. The profile and
workflow system is a production rubric distilled from the local pixel-art
workflow corpus supplied by the user; it is not a request to copy a specific
artist or name a style after one source.

Use `references/pixel-art-direction.md` for profile definitions, QA, and repair order.
Use `references/pixel-animation-workflows.md` for row phase contracts such as
locomotion, combat, jump, top-down attacks, VFX, water, wind, pickups, and tiny
motion.
Use `references/isometric-tilesets.md` for 2:1 isometric terrain, decor, props,
buildings, pivots, edge/corner roles, and runtime map/depth proof.

Request shape:

```json
{
  "art_direction": {
    "mode": "pixel-art",
    "profiles": ["auto"],
    "workflow_reference": "references/pixel-animation-workflows.md"
  }
}
```

`auto` infers profiles per row. Explicit profiles are useful when a custom row needs stronger direction:

```bash
python scripts/preset_to_request.py custom-atlas --art-profile pixel-combat --out /abs/run/request.json --states-file /abs/run/states.json
python scripts/prepare_sprite_run.py --out-dir /abs/run --character-id hero --request /abs/run/request.json --force
```

Preparation writes `references/art-direction.json`, which records active
profiles, animation workflows, and source article groups per row. Review it
before generation. Disable only for conflicting non-pixel styles:

```bash
python scripts/prepare_sprite_run.py --out-dir /abs/run --character-id hero --request /abs/run/request.json --art-direction none --force
```

When auto inference is wrong for a custom row, add explicit workflows in the
request:

```json
{
  "animation_workflows": ["combat-power-strike"]
}
```

## Core Scripts

- `scripts/preset_to_request.py`: convert `references/presets.json` preset into request JSON.
- `scripts/prepare_sprite_run.py`: write `sprite-request.json`, compact-grid/strip raw layout metadata, geometry-only `references/layout-guides/*.png`, `references/art-direction.json`, locomotion Image Gen prompts/contracts, `prompts/*.txt`, `raw/`, `frames/`.
- `scripts/prepare_motion_template_library.py`: regenerate the five canonical view prompts from the template catalog; it does not draw or approve bitmap art.
- `scripts/check_motion_references.py`: fail closed before locomotion row generation unless every required neutral mannequin is a valid 512px-or-larger image with adjacent `art_engine=imagegen` provenance.
- `scripts/promote_identity_anchor.py`: turn the first accepted generated idle/neutral frame into `references/identity-anchor.png`.
- `scripts/extract_sprite_row_frames.py`: remove chroma/rembg/BEN2 background, extract compact raw grids, connected components, projection-repaired strips, normalize sprite pose scale/baseline, write transparent cell frames.
- `scripts/register_sprite_frames.py`: align extracted/imported frames to a stable runtime pivot before atlas composition; use after unpacking whole-sheet candidates whose sprites drift inside cells.
- `scripts/compose_sprite_atlas.py`: bake atlas and runtime `manifest.json.frame_layout`.
- `scripts/preview_animation.py`: write contact sheets and GIF previews under `qa/`.
- `scripts/build_preview_workbench.py`: write the self-contained, hash-bound interactive review surface under `qa/preview-workbench/`.
- `scripts/prepare_grok_video_animation.py`: bind one exact first frame to a dry-run-first `$grok-imagine video-from-image` job.
- `scripts/ingest_grok_video_animation.py`: validate completed Grok media, decode/sample video deterministically, preserve frame 1, write the normal raw grid and provider provenance.
- `scripts/check_frame_alignment.py`: real-frame onion-skin QA for baseline/root alignment, jump takeoff/landing closure, fall/knockdown settlement, bboxes, and alpha centers.
- `scripts/check_identity_consistency.py`: head/upper-body/area proxy QA so identity scale drift cannot pass as animation.
- `scripts/serve_curation.py`: local curation webview; selection + move/scale/rotate/shear saved in `curation.json`.
- `scripts/unpack_atlas_run.py`: rebuild curator-ready run from existing atlas, manifest, grid, projection-grid repair, authored boxes, or loose PNG folder; for visual auto-detect/projection it can matte the sheet first and writes segmentation QA.
- `scripts/export_curated_pngs.py`: export curated still PNGs from imported/candidate sets.
- `scripts/compose_selected_cycle.py`: record human-picked frame order for partial locomotion wins.
- `scripts/compose_sprite_gif.py`: export clean transparent GIFs.
- `scripts/check_generation_provenance.py`: require verified imagegen, Grok, mixed, or explicit imported-source provenance before production QA; allow procedural art only as fixtures.
- `scripts/check_visible_magenta.py`: screenshot guard for visible chroma leakage.
- `scripts/check_chroma_key_safety.py`: palette-distance guard for unsafe key colors before/after generation.
- `scripts/rekey_chroma_background.py`: replace or normalize a border-connected generated key background before extraction.
- `scripts/check_animation_contracts.py`: generic animation workflow QA for locomotion, combat, jumps, reactions, VFX, water, wind, pickups, idles, and tiny sprites.
- `scripts/check_motion_variation.py`: heuristic locomotion QA for frozen legs/body-part positions.
- `scripts/check_asset_slots.py`: still/tileset/texture slot QA for labels, catalog metadata, pivots, clipping, per-item `repeat_mode`, numeric self-repeat edge coverage/error, labeled per-item 3x3 previews, and role-aware adjacency assembly. Overlay mode remains an explicit isolation-review obligation.
- `scripts/check_isometric_tiles.py`: isometric tileset QA for 2:1 footprint, runtime cell, pivots, edge/corner roles, map composition, depth-sort previews, calibrated runtime metadata, and candidate catalog fixes.
- `scripts/smoke_pipeline.py`: tiny local smoke check.
- `scripts/smoke_presets_from_reference.py`: run every preset through deterministic pipeline using a reference sheet.
- `references/professional-sprite-animation.md`: production standard for atlas contracts, animation principles, body mechanics, fighting rows, asset modes, background removal, and visual QA.

## Presets

Read `references/presets.json` first. Current presets:

- `codex-pet`
- `platformer-character`
- `topdown-character`
- `isometric-character`
- `combat-character`
- `fighting-game-character`
- `rpg-monster`
- `ui-avatar`
- `tileset-topdown`
- `tileset-platformer`
- `texture-pack`
- `asset-pack`
- `custom-asset-atlas`
- `custom-atlas`

Preset defaults are contracts. Override only when user explicitly asks, then report compatibility changes.

## Asset Modes

- `sprite`: character/creature/avatar animation rows. Use anchors, motion QA, GIFs, and component extraction.
- `tileset`: top-down, side-view, or isometric tile rows. Use slot extraction, exact grid or authored boxes, reviewed labels, catalog pivots, edge/corner compatibility, collision roles, and repeat/map QA. Isometric tilesets additionally require `references/isometric-tilesets.md` and `check_isometric_tiles.py`.
- `texture`: seamless material samples. Use slot extraction, zero safe margin, tileability checks, and contact-sheet QA.
- `asset`: props, pickups, icons, VFX, decals, and mixed still sheets. Use slot extraction, set consistency, and curation/export.
- `custom-atlas` / `custom-asset-atlas`: pass explicit rows with `--states-file` on Windows.

## Professional Production Standard

Use `references/professional-sprite-animation.md` as the quality bar when generating, repairing, curating, or reviewing atlas work.

For animated characters, every row must be judged on:

- key-pose clarity: setup/anticipation, action/contact/extreme, recovery/settle when the state needs it;
- silhouette and line of action: pose readable at runtime size without labels, motion marks, or detached effects;
- anatomy/body mechanics: grounded weight, center of mass, plausible joints, arcs, overlap/follow-through, and no accidental stiffness;
- identity and volume: face, head, upper body, hands, feet, outline weight, costume scale, and asymmetric details remain locked to the accepted anchor;
- pivot/origin behavior: feet/baseline for grounded side-view sprites, airborne arc for jumps/falls, grid for tiles, emitter/contact point for VFX.

For fighting-game or combat rows, require readable gameplay phases:

- idle/block: guard, balance, breathing/weight shift, stable combat stance;
- walk/run: alternating contacts, passing poses, shoulder/hip counter-motion, loop seam;
- crouch/jump/fall/land: height and placement changes without whole-character rescale;
- punch/kick/special: startup, active/contact, recovery, with the active frame as the strongest silhouette;
- hitstun/knockdown/death: force direction, balance loss, overshoot/drag, and recovery/fall staging.

For non-sprite asset modes:

- tilesets need exact grid fit, edge compatibility, readable collision surfaces, consistent projection, and no scene/collage output;
- textures need seamless/tileable intent, flat material samples, consistent texel density, and no perspective hero objects;
- props/icons need centered isolation, readable silhouette, scale hierarchy, and coherent set language;
- VFX needs buildup/peak/decay frames, stable emitter anchor, alpha-friendly opacity, and no source-background residue.

## Frame Budget

Default: keep preset frame counts. Do not reduce animation just because smaller is possible.

Use low-frame animation only when:

- user asks for 2-3 frames, limited animation, cheap/retro motion, tiny sprites, faster production, or a strict runtime budget;
- user says the exact frame count per state;
- user is unsure and the target is simple enough, then ask once: "default smooth frames or compact 2-4 frame animation?"

For preset sprites, use:

```bash
python scripts/preset_to_request.py platformer-character --frame-budget micro --out /abs/run/request.json
```

Budget heuristics:

- `micro`: simple idles/reactions can be 2 frames, attacks often 3, locomotion usually 4, complex deaths/specials usually 4.
- `compact`: keep more readability; simple rows around 3, actions around 4, locomotion around 6.
- exact control: write a `--states-file` with explicit frame counts and actions.

Do not apply frame budgets to tilesets, textures, or still asset variant rows; their frame count means variants, not animation timing.
