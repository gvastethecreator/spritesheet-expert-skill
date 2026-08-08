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

`$imagegen` is the primary still-image art engine. `spritesheet-expert` owns contracts, prompts, layout guides, extraction, registration, atlas composition, previews, curation, and QA. `$imagegen` owns default bitmap creation; `$grok-imagine` may own bitmap or video creation only when its route is selected explicitly.

For ordinary user-facing sprite, character, tileset, texture, prop, icon, VFX, or atlas art generation, load and follow `$imagegen`. Generate on a flat neutral gray, black, or white background; do not request green, blue, cyan, or magenta chroma. Preserve valid neutral colors in the subject and remove only the connected source background or use a model-backed cutout.

Local scripted/PIL/procedural drawing is allowed only for deterministic smoke tests, regression fixtures, and geometry debugging. It must never be presented as representative production art, even when `$imagegen` is unavailable. If `$imagegen` cannot be used, stop the generated-art path, write a blocked status, or continue only with explicit user-provided/imported art.

Pipeline validation for generated art must include provider-produced source media before calling the result visually representative. The local scripts can prepare prompts, guides, decode accepted video, extract frames, compose atlases, and produce previews, but they do not replace `$imagegen` or `$grok-imagine` for final visual content.

Before final QA or packaging, run `scripts/check_generation_provenance.py --run-dir /abs/run`. It must pass for generated production art. Use `--allow-imported-source` only for explicit user-provided or existing sheets. Use `--allow-fixture` only for local smoke/regression fixtures.

When `$imagegen` outputs are meant for the project, copy or move the selected generated image from the default generated-images location into the run folder before extraction. Do not leave project-referenced row art only under `$CODEX_HOME`.

Requires Python with Pillow and jsonschema. From the installed skill directory run `python -m pip install -r scripts/requirements-core.txt`, then `python scripts/check_python_env.py`. Repository maintainers use the root `pyproject.toml` for the complete test gate. Install `scripts/requirements-lucida.txt` for the preferred Lucida sprite lane, `scripts/requirements-background.txt` for rembg/BiRefNet, and `scripts/requirements-video.txt` only for video ingestion. These extras remain optional so core request preparation stays lightweight.

## Provider-Neutral Video Animation

Use the video lane for any animation source. The source can come from Grok, another provider, a local tool, or the user.

Ingest existing videos with `scripts/ingest_video_animation.py`. Use an approved first frame when one exists.

Ingestion analyzes every decoded frame. It writes several candidate cycles and builds `qa/<state>-video-frame-selector/index.html` automatically.

The minimal editor is required. It includes full video playback, all frame thumbnails, candidate presets, frame slots, and a cycle preview.

Re-ingest reviewed indices without provider inference. Then remove the background per selected frame, crop its alpha bounds, add transparent padding, and register the result.

Fail extraction if a significant silhouette touches a source boundary. Fail QA if opaque pixels enter the final safe margin.

Read `references/video-animation-workflow.md` for every video source.

## Optional Grok Imagine Provider

Load and follow `$grok-imagine` when the user selects Grok still generation or the first-frame-to-video animation route. Keep provider execution outside this skill: start with the wrapper `--dry-run`, review its exact source/prompt/counts/output, and add `--ack-run` only with explicit current-task consent. Never call Grok inference from tests.

For video animation, create and approve one exact first frame. Then run `scripts/prepare_grok_video_animation.py`. It creates a locked-camera prompt and a dry-run job.

`scripts/ingest_grok_video_animation.py` accepts one video from a successful invocation. It checks the prompt, first frame, media count, and hashes.

After ingestion, use the provider-neutral selector and extraction path. Grok does not own frame selection, background removal, cropping, registration, or QA.

Read `references/grok-video-animation.md` before this route. On Zero Data Retention teams, video generation may require a caller-owned `output.upload_url`; do not retry around that provider boundary or claim completion without copied media and a completed invocation manifest.

## Failure Prevention Contract

- Never infer provider provenance from filenames or appearance. Pin accepted source bytes and declare Imagegen, Grok image, Grok video, imported, fixture, or mixed provenance explicitly.
- Never promote deterministic fixtures, procedural drawings, layout guides, or repaired placeholders as representative production art. They may test geometry and failure paths only.
- New isolated generation uses flat gray, black, or white. Green, blue, cyan, and magenta are legacy-import chroma only. When subject colors overlap a matte, use reviewed model-backed removal and compare checker/black/gray/white views.
- A failed semantic frame returns to Imagegen or the explicitly selected Grok provider. Registration may remove extraction jitter; it must not hide actual root, pelvis, foot, or contact drift.
- A contact sheet proves inventory and order. Animation claims require chronological playback plus contact/onion evidence; runtime placement, repeat, projection, and edge claims require their specific proof artifacts.
- Rebuild proof after any source, request, curation, registration, atlas, manifest, or QA change. Final approval must reference current hashes and an inspected visual-review record.

## Local Handoff Runner Contract

When this skill is driven by a local app such as Sprite Bench, keep the skill as the atlas engine and use a separate handoff layer for providers:

```text
codex-handoff/
  inbox/   # structured generation/regeneration jobs
  outbox/  # real returned images or blocked sidecars
  status/  # runner status per job
  logs/    # stdout/stderr tails from codex exec or adapters
```

The app or runner may write a job JSON that points to `sprite-request.json`, `prompts/<state>.txt`, `references/layout-guides/<state>.png`, optional `references/identity-anchor.png`, and the expected output row. Locomotion jobs must also point to the accepted `references/motion-references/<state>.png`. Codex, a manual operator, or a future provider should return a real image file to `outbox/` using the job id prefix. The runner then copies the accepted result into `raw/<state>.png` before extraction.

Locomotion tries an approved reusable Image Gen template first. The catalog at `assets/motion-reference-templates/` reserves five 8-frame master slots for side, front, back, three-quarter-front, and three-quarter-back views; an entry marked `needs-imagegen` is a pending slot, not a bundled master. Left-facing variants mirror an approved right-facing master, and 4/6-frame variants select protected phases from it. If no approved/hash-matching template exists, generate the neutral color-coded mannequin once from `prompts/motion-references/<state>.txt`, review it, and promote it into the library instead of regenerating it per character. Every run copy has adjacent provenance with `art_engine: "imagegen"`, matching `state`, and `selected_source`. Run `scripts/check_motion_references.py --run-dir /abs/run`; only after it passes may the runner submit the final character-row job. Never send the deterministic layout guide as a substitute motion/anatomy reference.

Returned final row files should be named like `<jobId>-<state>.png|webp|jpg`. Do not place contact sheets, comparison sheets, preview grids, temp candidates, QA JSON, debug images, staging files, or work-in-progress files in the outbox root as final import candidates.

If generation is blocked by safety, policy, missing imagegen capability, provider failure, no returned image, or user cancellation, write a small `<jobId>-blocked.json` sidecar with `status=blocked`, `reasonKind`, `userMessage`, and `suggestion`. Allowed `reasonKind` values are `policy_or_safety`, `imagegen_unavailable`, `runner_failed`, `no_image_returned`, and `unknown`. Do not create a placeholder image, deterministic drawing, SVG, or text preview to keep the pipeline moving.

Provider adapters must not mutate browser-only state. They should emit bounded events, update status/log files, and write artifacts back into the run folder or handoff outbox. The existing skill scripts remain the only supported path for extraction, curation, atlas composition, previews, and QA.

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
   - New sprite component runs default to `background_removal.method: lucida` and `grid_segmentation: adaptive`. With no identity image, preparation uses a black fallback background. Pixel art uses hard alpha threshold `64`; illustrated art keeps soft alpha unless the request changes it.
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
   - New generation uses flat neutral gray, black, or white. Lucida is the preferred sprite cutout because it preserves illustration, line art, and glow. `auto` remains the compatibility path for other assets. It preserves existing alpha, uses edge-connected matte removal for a clean flat source, and falls back to `rembg` with `birefnet-general` for ambiguous backgrounds. Chroma is legacy-import compatibility only. BEN2 is an explicit comparison path. Review raw, checker, black, gray, white, and alpha panels in `qa/background-matte-review.png`; over-removal of clothing, outlines, props, interiors, or antialiasing is a hard failure.
   - For video sources, remove the background from each selected frame. Do not send the complete grid through one model inference. Use dynamic alpha bounds and transparent crop padding.
   - Treat source-edge contact and final safe-margin intrusion as hard failures. Registration cannot recover missing source pixels.
   - Render deterministic runtime playback for every animated state, finish the QA reports, then build or rebuild `qa/preview-workbench/index.html` with `scripts/build_preview_workbench.py --force`. Use its pause/step/scrub/speed/zoom/state controls, full frame strip, and checker/black/gray/white edge microscope for human review. Keeping this order prevents a stale self-contained workbench from omitting late evidence.
   - Use Pixel-art profile and workflow QA as a critique pass: 3x3 tile repetition, full-speed motion, locomotion contact/pass logic, attack phase readability, VFX loop math, tiny-sprite economy, projection uniformity, and palette/cluster discipline where relevant.
   - If a second provider attempt still fails exact `repeat_mode: self` edges, `repair_repeat_edges.py` may harmonize only the provider-derived edge band. Keep its original backups/hash report and rerun the all-item 3x3 preview; this is post-processing, never procedural replacement art.
   - For isometric tilesets, do not approve isolated slots only. Run `check_asset_slots.py` and `check_isometric_tiles.py`, then review pivot, 2:1 footprint, map-repeat, edge/corner, and depth-sort proof images. Runtime/prototype placement must consume `qa/isometric-runtime-metadata.json` or a reviewed catalog copied from `qa/isometric-calibrated-catalog.json`; never place isometric cells from rectangular top-lefts or stale declared pivots.

Done when source provenance, required video selector evidence, transparent frames, atlas PNG, manifest, previews, the workbench, and QA reports match the asset kind.

## Identity And Motion Rules

- Base image creates identity source.
- Creature motion starts from the declared anatomy. Do not apply mirrored biped sway to winged, hovering, multi-legged, amorphous, serpentine, or custom bodies.
- Compact four-frame movement uses exact idle, phase A, exact idle, phase B. Compact attack uses exact idle, anticipation, contact, exact idle.
- Replace repeated generated idles with the accepted idle pixels before final registration and QA. Visual similarity is not pixel identity.
- Choose registration from stable anatomy. Do not align multi-legged bodies from a changing leg tip or hovering bodies from a changing shroud edge.
- If no base image exists, the first accepted idle/neutral frame becomes the identity source. Promote it to `references/identity-anchor.png` before generating action rows.
- Direction-sensitive work should create accepted idle anchors before action rows.
- Later rows should solve motion, not rediscover identity.
- Jump, fall, land, crouch, duck, and squat rows must preserve idle/direction scale. Show height changes through body compression or vertical placement, not zoom-to-fill.
- Crouch/duck/squat transition rows use per-frame height curves plus scale-lock checks. The first frame may remain near standing height, then later frames compress toward a final pose around 65-75% idle height while feet stay on the shared baseline. Preserve head, hands, feet, line weight, outfit scale, and body thickness; the final crouch should not become a uniformly smaller whole character.
- Jump rows use per-frame vertical placement checks at the idle reference scale. Do not compute one global jump-peak scale for the whole row; compare each frame against its own expected height, width, head/upper-body proxy, and bottom position.
- Jump takeoff and landing frames must return to the same shared baseline. Airborne frames may leave the baseline, but the arc must be visible, the root x should not drift unless the state is intentionally forward/back, and onion-skin overlay must show clean takeoff/landing closure.
- Fall/knockdown rows must settle back to the ground baseline by the final frame. Falling/collapsing frames may rotate and get lower/wider, but they must not slide because of registration drift or uniformly shrink to fit.
- Pose corrections require visual comparison, not only numeric checks. Open `qa/pose-scale-review.png`, `qa/<state>-contact.png`, GIFs, or the prototype viewer and compare idle/reference, transition, and final frames for readable body pose, locked character scale, baseline, silhouette, head/hand/foot size, outfit texture, and no "miniature final pose" effect.
- For humanoid/mascot sprites, use stable-part proxy metrics as a guardrail: `head_width_vs_reference` and `upper_width_vs_reference` should stay near idle scale for jump/fall/land/crouch even when full-body bbox height changes. If these proxies shrink, the row likely scaled the whole character down instead of changing pose.
- Run `check_identity_consistency.py` after extraction for animated character runs. It gates head width, upper-body width, and opaque-area proxy drift across all rows. Head-size wobble, upper-body shrink, or inflated/miniaturized frames are identity failures even when motion, alignment, and atlas composition pass.
- Treat identity proxies as guardrails. If raised limbs enter a head or torso proxy band, preserve the standard failure, inspect contact/onion/runtime evidence, and document any pose-aware rerun. Never hide visible drift by widening thresholds.
- Run the same identity gate for every multi-frame static character pose or direction set. `frame_semantics=variants` does not waive same-character scale, face construction, or body-volume consistency, and every declared slot must be occupied once.
- Grounded pose rows keep feet on the shared baseline. Airborne rows keep the same body size and move through the slot using the jump/fall arc.
- Side-view and mascot locomotion rows also keep feet on the shared baseline so body bob, stride, and distinct contact/pass poses survive extraction.
- Generate paired basis row first for directional locomotion, then paired row with basis as rhythm reference.
- 4-, 6-, and 8-frame `walk/run/move/advance/retreat/dash` rows get motion-phase layout guides by default so legs alternate contact/passing poses instead of drifting in one direction. Prefer 8 frames for fighting-game advance/retreat when quality matters.
- Run `check_animation_contracts.py` for every animated row that has or infers an `animation_workflow`. It checks workflow-specific phase evidence for locomotion, combat, top-down attacks, jumps, reactions, VFX, water, wind, pickups, idles, and tiny sprites, then writes the visual checklist that still gates approval.
- For `gesture-loop`, freeze pelvis through both feet in both the still/video provider prompt and the final visual result. Require `metrics.gesture_planted_lower_body.ok: true` as well as loop closure; never use registration to hide leg, foot, contact-footprint, or root travel.
- Run `check_frame_alignment.py` for every animated sprite run. It writes `qa/frame-alignment-report.json` plus `qa/<state>-onion.png` overlays that compare real extracted frames, baseline, bboxes, and alpha centers. Do not approve jump, fall, land, crouch, knockdown, block, idle, or locomotion rows without reviewing the relevant onion skin.
- Run `check_motion_variation.py` for walk/run/move rows. It checks lower-body silhouette change, screen-space balance variation, opposite-contact pose difference, and body-center drift so frozen or duplicated phases get caught before done. Screen-space left/right is diagnostic only; it cannot identify the anatomical support leg.
- Treat the motion report as a heuristic, never final approval. For every walk/run/move row, inspect chronological playback/contact sheets and confirm frame 1 and the halfway contact frame use opposite anatomical support legs with a visible crossover/depth swap. Pass/down frames must connect those contacts without both legs drifting together. Same-leg contact is a hard row failure even when the JSON says `ok`.
- Mirror only when user approves and asymmetric details stay correct.
- Locomotion is experimental until the deterministic GIF and interactive workbench playback pass motion QA.
- If a row partially works, use `compose_selected_cycle.py`; do not pretend full row passed.
- Tiles/textures declare `asset_catalog.items.*.repeat_mode` as `self`, `adjacency`, or `overlay`. Self-repeat outputs fill the cell edge-to-edge and pass numeric opposite-edge QA. Adjacency and overlay outputs require their role-aware hash-bound visual review; a contact sheet alone is not proof.

## QA And Outputs

Read `references/qa-and-outputs.md` before final packaging. Completion criterion: QA reports, previews, atlas, manifest, and exports match the requested asset kind.
