---
name: spritesheet-expert
description: "Build and validate spritesheets, anatomy-driven animation rows, tilesets, textures, and atlases from imported art, Imagegen, Grok, or existing videos. Use for compact grids, full-video frame analysis, ranked candidate editors, Lucida cutouts, safe adaptive crops, frame registration, playback previews, provenance, curation, and QA."
---

# Spritesheet Expert

## Overview

Build sprites and game asset sheets with the component-row pipeline:

```text
preset/custom contract -> sprite-request.json -> layout guides + row/grid prompts
-> Pixel-art direction profiles + animation workflows -> imagegen, approved Grok, or imported video media
-> ranked video candidates or neutral-background grids -> per-frame Lucida removal + safe adaptive extraction
-> identity consistency + animation contract + onion-skin alignment QA
-> curated frames -> atlas PNG + manifest.json.frame_layout -> interactive review workbench
```

Use `$imagegen` as the default still-image generator. Use `$grok-imagine` only as the explicit optional image/video provider described below. Local scripts own deterministic request prep, neutral-background removal, video-frame ingestion, extraction, registration, atlas composition, previews, curation, unpacking, provenance gates, alignment gates, and exports; they never perform paid inference.

## Mandatory Imagegen Rule And Grok Exception

- Use `$imagegen` for default still-image creation. Use `$grok-imagine` only when the user explicitly selects its still or video route.
- For isolated still art, ask Imagegen for a clean native transparent background first. Preserve provider alpha when it is valid.
- Validate native alpha before extraction: the source must have an alpha channel, transparent exterior pixels, clean semitransparent edges, and no opaque backdrop, matte fringe, or cross-slot bleed.
- If Imagegen does not return valid native alpha, generate on flat neutral gray, black, or white and use the documented background-removal path. Do not request chroma colors for new production art.
- Local PIL or procedural drawing is limited to deterministic fixtures and geometry debugging. Never present it as production art.
- Generated-art validation requires provider-produced source media. Local scripts own contracts, extraction, registration, atlases, previews, and QA, not paid inference.
- Generated production art prefers provider-native alpha. Gray, black, or white neutral backgrounds are the fallback when native alpha is absent or fails review; green, blue, cyan, or magenta are legacy-import chroma only. Alpha validation or model-backed removal plus a contact sheet proves the representative production-art boundary.
- Before final QA, run `scripts/check_generation_provenance.py --run-dir /abs/run`. Use `--allow-imported-source` only for explicit imported art and `--allow-fixture` only for tests.
- Move selected provider output into the project run folder before extraction; do not leave project sources only in a client cache.
- Core setup requires Pillow and jsonschema through `scripts/requirements-core.txt`. Install Lucida, background-removal, or video extras only for the selected lane.

## Provider-Neutral Video Animation

Use the video lane for any animation source. The source can come from Grok, another provider, a local tool, or the user.

Ingest existing videos with `scripts/ingest_video_animation.py`. Use an approved first frame when one exists.

Ingestion analyzes every decoded frame. It writes several candidate cycles and builds `qa/<state>-video-frame-selector/index.html` automatically.

The minimal editor is required. It includes full video playback, all frame thumbnails, candidate presets, frame slots, and a cycle preview.

For creature videos, the editor also shows the declared creature type, anatomy-driven motion source, semantic slot names, and five mandatory review checks. Changing a candidate or frame clears those checks. Do not copy the re-ingestion command until type, pose semantics, identity, camera/scale, and source margins are confirmed for that exact selection.

Re-ingest reviewed indices without provider inference. Then remove the background per selected frame, crop its alpha bounds, add transparent padding, and register the result.

Fail extraction if a significant silhouette touches a source boundary. Fail QA if opaque pixels enter the final safe margin.

Read `references/video-animation-workflow.md` for every video source.

### Fast Video Production Gate

Read `references/video-animation-workflow.md` before preparing or accepting any video-derived state. It owns the detailed prompt, selection, quota, repair, and batch-completion contract.

- Validate the exact first frame, visible anatomy, motion driver, camera, scale, identity locks, and source margins before inference.
- Request one provider video per state and stop after the first successful media call. Review the complete timeline before considering another generation.
- Reject camera movement, scale drift, perspective rotation, identity morphing, anatomy changes, wrong motion, or source-edge contact.
- Review all decoded frames in the selector, then re-ingest exact chronological indices before Lucida or adaptive extraction.
- A quota-sealed batch never regenerates after media succeeds. Exhaust the timeline first; use one identity-locked `$imagegen` pose repair only when the documented repair contract allows it.
- After an Imagegen repair, run `scripts/sync_imagegen_repair_provenance.py` and repeat provenance, matte, registration, contact, onion, runtime, and packaging checks.
- Before declaring a multi-identity batch complete, run `scripts/check_animation_batch_completion.py`. Recursive file count is not quota evidence.
- Explicit `animation_workflows` own QA routing. Action prose is only a legacy fallback.

## Optional Grok Imagine Provider

Load and follow `$grok-imagine` when the user selects Grok still generation or the first-frame-to-video animation route. Keep provider execution outside this skill: start with the wrapper `--dry-run`, review its exact source/prompt/counts/output, and add `--ack-run` only with explicit current-task consent. Never call Grok inference from tests.

For video animation, create and approve one exact first frame. Then run `scripts/prepare_grok_video_animation.py`. It creates a structured locked-camera prompt and a dry-run job. Front-FPS creature states fail preparation unless `creature_motion.camera`, `movement_source` or `attack_source`, and anatomy are explicit.

`scripts/ingest_grok_video_animation.py` accepts one video from a successful invocation. It checks the prompt, first frame, media count, and hashes.

After ingestion, use the provider-neutral selector and extraction path. Grok does not own frame selection, background removal, cropping, registration, or QA.

Read `references/grok-video-animation.md` before this route. On Zero Data Retention teams, video generation may require a caller-owned `output.upload_url`; do not retry around that provider boundary or claim completion without copied media and a completed invocation manifest.

## Failure Prevention Contract

- Never infer provider provenance from filenames or appearance. Pin accepted source bytes and declare Imagegen, Grok image, Grok video, imported, fixture, or mixed provenance explicitly.
- Never promote deterministic fixtures, procedural drawings, layout guides, or repaired placeholders as representative production art. They may test geometry and failure paths only.
- New isolated still generation first requests provider-native transparency. Accept it only after alpha-channel, transparent-exterior, edge-fringe, and slot-boundary checks pass.
- If native alpha is absent or invalid, use flat gray, black, or white. Green, blue, cyan, and magenta are legacy-import chroma only. When subject colors overlap a matte, use reviewed model-backed removal and compare checker/black/gray/white views.
- A failed semantic frame returns to Imagegen or the explicitly selected Grok provider. Registration may remove extraction jitter; it must not hide actual root, pelvis, foot, or contact drift.
- A contact sheet proves inventory and order. Animation claims require chronological playback plus contact/onion evidence; runtime placement, repeat, projection, and edge claims require their specific proof artifacts.
- Rebuild proof after any source, request, curation, registration, atlas, manifest, or QA change. Final approval must reference current hashes and an inspected visual-review record.

## Local Handoff Runner Contract

When a local app drives this skill, keep provider execution in a separate handoff layer and keep the skill scripts as the only extraction, curation, atlas, preview, and QA path.

- Jobs point to the exact request, state prompt, layout guide, optional identity anchor, expected output, and required motion reference.
- Reusable motion templates must be approved and hash-matching. A pending template is not a bundled master.
- Accept returned art only through the executable source-intake contract in `references/workflows.md`; it verifies job, state, kind, bytes, and provenance.
- Final returned files use `<jobId>-<state>.png|webp|jpg`. Keep contact sheets, debug images, reports, and temporary candidates out of the final-import location.
- A blocked job writes `<jobId>-blocked.json` with `status`, `reasonKind`, `userMessage`, and `suggestion`. Never fabricate a placeholder to keep the pipeline moving.
- Provider adapters emit bounded status and artifacts. They do not mutate browser-only state or bypass the run-folder contracts.

## Reference Gates

Read `references/atlas-reference.md` when choosing background removal, style presets, core scripts, asset modes, production standards, or frame budgets.

Read `references/pixel-art-direction.md` when the target is pixel art, retro/tiny sprites, tile art, texture packs, VFX, combat rows, top-down, side-view, or isometric game assets. Default to `art_direction.mode: pixel-art` for pixel-art presets unless the user asks for a conflicting non-pixel style.

Read `references/pixel-animation-workflows.md` when generating or reviewing animated rows, combat rows, top-down direction sets, VFX, water, wind, pickups, or tiny sprites. Use it to verify each row's required phases, not only its visual style.

Read `references/professional-sprite-animation.md` before generating, repairing, curating, or reviewing animated character rows.

Read `references/creature-animation.md` before generating or repairing non-human creatures, frontal retro-FPS enemies, compact 2x2 movement/attack grids, or anatomy-specific registration.

Read `references/isometric-tilesets.md` when generating, importing, slicing, naming, or reviewing isometric terrain, props, decor, buildings, or tilesets.

Read `references/grok-video-animation.md` when using Grok image generation, image-to-video, video decoding, or video-derived provenance.

Read `references/video-animation-workflow.md` when importing, selecting, reselecting, cutting, or validating frames from any video source.

Read `references/lucida-adaptive-workflow.md` for new Imagegen character or creature grids, black-background cutouts, soft-to-hard alpha policy, variable frame bounds, or adaptive segmentation repair.

Completion criterion: atlas contract names asset kind, extraction mode, background removal, art direction profile(s), animation workflow(s), generation provenance, frame budget if any, QA path, and output manifest before final packaging.

## Process

1. Choose preset or custom contract.
   - Read `references/atlas-reference.md` for presets, asset modes, background removal, and frame budgets.
   - Use `references/pixel-art-direction.md` to choose `auto` or explicit profiles such as `pixel-sideview`, `pixel-topdown`, `pixel-isometric`, `pixel-combat`, `pixel-texture`, `pixel-vfx`, `pixel-items-ui`, `pixel-shmup`, or `pixel-tiny`.
   - Use `references/pixel-animation-workflows.md` to confirm inferred row workflows such as `gesture-loop`, `sideview-locomotion`, `topdown-locomotion`, `combat-quick-strike`, `combat-power-strike`, `topdown-weapon-attack`, `responsive-jump`, `water-loop`, or `wind-ambient-loop`.
   - For an animated creature, declare `creature_motion` before generation. Name its anatomy, locomotion, camera, registration anchor, shared-idle policy, movement source, and attack source.

2. Prepare run folder and generation prompts.
   - Use `scripts/preset_to_request.py` and `scripts/prepare_sprite_run.py` for deterministic request/layout/art-direction setup.
   - Check `references/art-direction.json` after preparation. Wrong profiles or workflows mean fix the request before generation.
   - Static/set rows also record `production_workflows`: character pose-set identity, top-down/isometric projection, exact slot inventory, tile adjacency, or seamless material contracts. They are non-temporal and must not be routed as fake animations.
   - Animated body rows use compact raw grids by default (`raw_layout.kind: compact-grid`) and are assembled into runtime rows only after extraction/QA. Do not force imagegen to draw long raw `1xN` character strips unless the request explicitly opts into `raw_layout_policy: "legacy-strip"` for a low-risk/import compatibility run.
   - Generate a complete compact grid for each creature state. For four-frame cycles, use one coherent 2x2 source. Use isolated full-frame regeneration only after a documented whole-grid identity failure. Never use a local patch that leaves an edit seam.
   - New isolated still and asset prompts request a fully transparent background with clean native alpha, no floor, backdrop, exterior shadow, halo, matte fringe, or cross-slot bleed.
   - New sprite component runs accept verified provider alpha as `background_removal.method: alpha`. If provider alpha is absent or invalid, use `lucida` with `grid_segmentation: adaptive`; with no identity image, preparation uses a black fallback background. Pixel art uses hard alpha threshold `64`; illustrated art keeps soft alpha unless the request changes it.
   - Locomotion rows also produce `prompts/motion-references/<state>.txt`, a machine-readable contract, and a target under `references/motion-references/`. `prepare_sprite_run.py` materializes an approved template automatically when available; generation is only the cache miss path. The mannequin's fixed anatomical colors prove left/right limb continuity; they are motion evidence only and must not leak into character identity or style.

3. Generate or import real row art.
   - Use `$imagegen` by default. Use `$grok-imagine` only through the explicit provider contract above. Never substitute procedural drawings, placeholder drawings, SVGs, or PIL sheets for representative art.
   - Before a locomotion row, run `scripts/check_motion_references.py --run-dir /abs/run`. A missing reference, undersized image, missing sidecar, or provenance other than `art_engine=imagegen` blocks row generation.
   - Write or preserve `source-provenance.json` with the exact provider/source type and accepted source paths before extraction. Grok video rows also require `provider/grok-imagine/<state>/video-source.json`. For existing user sheets, record imported/user-provided provenance and keep it separate from generated-art claims.
   - For an existing video, run `ingest_video_animation.py`. Review the required candidate editor before extraction. Re-ingest selected indices without new inference.

4. Extract, curate, compose, preview, and QA.
   - Follow `references/workflows.md` for exact commands for new sheets, imported sheets, atlas unpacking, curation, GIFs, and exports.
   - For imported/generated whole sheets, do not trust a nominal grid when dimensions, gutters, or visual placement drift. New compact sprite grids use Lucida before adaptive two-dimensional component assignment. Review `qa/<state>-adaptive-segmentation.png` and the recorded variable source boxes. Use fixed cells only for a true exact grid. Auto-detect and slot fallback remain diagnostic until reviewed.
   - Compare the extracted baseline with the game's real runtime cell and actor pivot. When they differ, run `register_sprite_frames.py` with the explicit target and use the registered run for composition, previews, and QA. Never infer the target from the sprite image alone.
   - Preserve valid provider-native alpha without rematting. Record `background_method: alpha` and review raw, checker, black, gray, white, and alpha panels in `qa/background-matte-review.png`.
   - If native alpha is absent or invalid, use flat neutral gray, black, or white. Lucida is the preferred sprite cutout because it preserves illustration, line art, and glow. `auto` remains the compatibility path for other assets. It preserves existing alpha, uses edge-connected matte removal for a clean flat source, and falls back to `rembg` with `birefnet-general` for ambiguous backgrounds. Chroma is legacy-import compatibility only. BEN2 is an explicit comparison path. Over-removal of clothing, outlines, props, interiors, or antialiasing is a hard failure.
   - When Lucida removes a large dark cavity that is fully enclosed by the accepted subject, set a reviewed per-run `background_removal.enclosed_hole_max_ratio`. Keep the default `0.02` for other runs. Never fill a border-connected limb, wing, ring, or silhouette gap.
   - For a clean, high-contrast neutral sheet, start Lucida with `--background-input-size 384`. Review the matte. Increase to `512`, then `1024`, only when fine fur, transparency, thin appendages, or glow is lost. Run one Lucida extractor at a time. Do not lower the request default or approve a faster matte by batch metrics alone.
   - For video sources, remove the background from each selected frame. Do not send the complete grid through one model inference. Use dynamic alpha bounds and transparent crop padding.
   - Treat source-edge contact and final safe-margin intrusion as hard failures. Registration cannot recover missing source pixels.
   - Render deterministic runtime playback for every animated state, finish the QA reports, then build or rebuild `qa/preview-workbench/index.html` with `scripts/build_preview_workbench.py --force`. Use its pause/step/scrub/speed/zoom/state controls, full frame strip, and checker/black/gray/white edge microscope for human review. Keeping this order prevents a stale self-contained workbench from omitting late evidence.
   - Use Pixel-art profile and workflow QA as a critique pass: 3x3 tile repetition, full-speed motion, locomotion contact/pass logic, attack phase readability, VFX loop math, tiny-sprite economy, projection uniformity, and palette/cluster discipline where relevant.
   - If a second provider attempt still fails exact `repeat_mode: self` edges, `repair_repeat_edges.py` may harmonize only the provider-derived edge band. Keep its original backups/hash report and rerun the all-item 3x3 preview; this is post-processing, never procedural replacement art.
   - For isometric tilesets, do not approve isolated slots only. Run `check_asset_slots.py` and `check_isometric_tiles.py`, then review pivot, 2:1 footprint, map-repeat, edge/corner, and depth-sort proof images. Runtime/prototype placement must consume `qa/isometric-runtime-metadata.json` or a reviewed catalog copied from `qa/isometric-calibrated-catalog.json`; never place isometric cells from rectangular top-lefts or stale declared pivots.

Done when source provenance, required video selector evidence, transparent frames, atlas PNG, manifest, previews, the workbench, and QA reports match the asset kind. A multi-identity animation batch is done only after `check_animation_batch_completion.py` also passes for the complete manifest.

## Identity And Motion Rules

- Establish one accepted identity anchor before later rows. Later generation solves motion, not identity.
- Derive creature motion from declared anatomy and one explicit motion driver. Lock non-driver anatomy, camera, image-plane scale, root, and margins.
- Preserve exact-idle pixels where the workflow requires them. Use chronological, readable anticipation, contact, passing, recovery, and loop phases.
- Keep grounded baselines stable and preserve character scale through crouch, jump, fall, land, knockdown, and direction changes.
- Run `check_identity_consistency.py`, `check_animation_contracts.py`, `check_frame_alignment.py`, and the workflow-specific motion gates for every applicable row.
- Treat numeric reports as guardrails. Review contact sheets, onion skins, deterministic playback, and the interactive workbench before approval.
- Use `record_identity_proxy_review.py` only for exact, visually confirmed proxy false positives. Any changed source, frame, crop, request, or atlas invalidates that review.
- Treat explicit `animation_workflows` as authoritative in `check_motion_variation.py`; word matching is only for legacy rows without a workflow id.
- Mirror only with approval and after checking asymmetric details. Registration may remove extraction jitter; it must not hide real anatomy or root drift.
- Tiles and textures must honor their declared repeat or adjacency contract and its matching visual evidence.

Read `references/professional-sprite-animation.md`, `references/creature-animation.md`, `references/pixel-animation-workflows.md`, `references/video-animation-workflow.md`, and `references/qa-and-outputs.md` for the complete branch-specific rules and proof gates.

## QA And Outputs

Read `references/qa-and-outputs.md` before final packaging. Completion criterion: QA reports, previews, atlas, manifest, and exports match the requested asset kind.
