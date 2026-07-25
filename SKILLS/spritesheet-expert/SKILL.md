---
name: spritesheet-expert
description: "Spritesheet pipeline. Use for sprites, tilesets, textures, asset sheets, extraction, curation, and QA."
---

# Spritesheet Expert

## Overview

Build sprites and game asset sheets with the component-row pipeline:

```text
preset/custom contract -> sprite-request.json -> layout guides + row/grid prompts
-> Pixel-art direction profiles + animation workflows -> imagegen raw grids/row strips
-> compact raw grids/row strips -> alpha/chroma/matte/rembg/BEN2 background removal + component/projection/grid extraction
-> identity consistency + animation contract + onion-skin alignment QA
-> curated frames -> atlas PNG + manifest.json.frame_layout
```

Use `$imagegen` for visual generation. Use local scripts only for deterministic request prep, layout guides, model-backed/background-key/matte removal, extraction, registration, atlas composition, previews, curation, unpacking, provenance gates, alignment gates, and exports.

## Mandatory Imagegen Rule

`$imagegen` is the internal visual-generation sub-skill and the primary art engine for this skill. `spritesheet-expert` owns contracts, prompts, layout guides, extraction, registration, atlas composition, previews, curation, and QA; `$imagegen` owns bitmap creation.

For any user-facing sprite, character, tileset, texture, prop, icon, VFX, or atlas art generation, `$imagegen` is mandatory. Load and follow the `$imagegen` skill rules for generation/editing, save-path handling, chroma-key transparency, and output honesty.

Local scripted/PIL/procedural drawing is allowed only for deterministic smoke tests, regression fixtures, and geometry debugging. It must never be presented as representative production art, even when `$imagegen` is unavailable. If `$imagegen` cannot be used, stop the generated-art path, write a blocked status, or continue only with explicit user-provided/imported art.

Pipeline validation for generated art must include `$imagegen`-produced source image or row strips before calling the result visually representative. The local scripts can prepare prompts, guides, extraction, atlas composition, previews, and QA, but they do not replace `$imagegen` for final visual content.

Before final QA or packaging, run `scripts/check_generation_provenance.py --run-dir /abs/run`. It must pass for generated production art. Use `--allow-imported-source` only for explicit user-provided or existing sheets. Use `--allow-fixture` only for local smoke/regression fixtures.

When `$imagegen` outputs are meant for the project, copy or move the selected generated image from the default generated-images location into the run folder before extraction. Do not leave project-referenced row art only under `$CODEX_HOME`.

Requires Python with Pillow available. `rembg` is optional for local model-backed background removal.

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

Locomotion uses an approved reusable Image Gen template first. The canonical library lives at `assets/motion-reference-templates/`: five 8-frame masters cover side, front, back, three-quarter-front, and three-quarter-back views; left-facing variants are mirrored and 4/6-frame variants select protected phases from the 8-frame master. If no approved/hash-matching template exists, generate the neutral color-coded mannequin once from `prompts/motion-references/<state>.txt`, review it, and promote it into the library instead of regenerating it per character. Every run copy has adjacent provenance with `art_engine: "imagegen"`, matching `state`, and `selected_source`. Run `scripts/check_motion_references.py --run-dir /abs/run`; only after it passes may the runner submit the final character-row job. Never send the deterministic layout guide as a substitute motion/anatomy reference.

Returned final row files should be named like `<jobId>-<state>.png|webp|jpg`. Do not place contact sheets, comparison sheets, preview grids, temp candidates, QA JSON, debug images, staging files, or work-in-progress files in the outbox root as final import candidates.

If generation is blocked by safety, policy, missing imagegen capability, provider failure, no returned image, or user cancellation, write a small `<jobId>-blocked.json` sidecar with `status=blocked`, `reasonKind`, `userMessage`, and `suggestion`. Allowed `reasonKind` values are `policy_or_safety`, `imagegen_unavailable`, `runner_failed`, `no_image_returned`, and `unknown`. Do not create a placeholder image, deterministic drawing, SVG, or text preview to keep the pipeline moving.

Provider adapters must not mutate browser-only state. They should emit bounded events, update status/log files, and write artifacts back into the run folder or handoff outbox. The existing skill scripts remain the only supported path for extraction, curation, atlas composition, previews, and QA.

## Reference Gates

Read `references/atlas-reference.md` when choosing background removal, style presets, core scripts, asset modes, production standards, or frame budgets.

Read `references/pixel-art-direction.md` when the target is pixel art, retro/tiny sprites, tile art, texture packs, VFX, combat rows, top-down, side-view, or isometric game assets. Default to `art_direction.mode: pixel-art` for pixel-art presets unless the user asks for a conflicting non-pixel style.

Read `references/pixel-animation-workflows.md` when generating or reviewing animated rows, combat rows, top-down direction sets, VFX, water, wind, pickups, or tiny sprites. Use it to verify each row's required phases, not only its visual style.

Read `references/professional-sprite-animation.md` before generating, repairing, curating, or reviewing animated character rows.

Read `references/isometric-tilesets.md` when generating, importing, slicing, naming, or reviewing isometric terrain, props, decor, buildings, or tilesets.

Completion criterion: atlas contract names asset kind, extraction mode, background removal, art direction profile(s), animation workflow(s), generation provenance, frame budget if any, QA path, and output manifest before final packaging.

## Process

1. Choose preset or custom contract.
   - Read `references/atlas-reference.md` for presets, asset modes, background removal, and frame budgets.
   - Use `references/pixel-art-direction.md` to choose `auto` or explicit profiles such as `pixel-sideview`, `pixel-topdown`, `pixel-isometric`, `pixel-combat`, `pixel-texture`, `pixel-vfx`, `pixel-items-ui`, `pixel-shmup`, or `pixel-tiny`.
   - Use `references/pixel-animation-workflows.md` to confirm inferred row workflows such as `sideview-locomotion`, `topdown-locomotion`, `combat-quick-strike`, `combat-power-strike`, `topdown-weapon-attack`, `responsive-jump`, `water-loop`, or `wind-ambient-loop`.

2. Prepare run folder and generation prompts.
   - Use `scripts/preset_to_request.py` and `scripts/prepare_sprite_run.py` for deterministic request/layout/art-direction setup.
   - Check `references/art-direction.json` after preparation. Wrong profiles or workflows mean fix the request before generation.
   - Animated body rows use compact raw grids by default (`raw_layout.kind: compact-grid`) and are assembled into runtime rows only after extraction/QA. Do not force imagegen to draw long raw `1xN` character strips unless the request explicitly opts into `raw_layout_policy: "legacy-strip"` for a low-risk/import compatibility run.
   - Locomotion rows also produce `prompts/motion-references/<state>.txt`, a machine-readable contract, and a target under `references/motion-references/`. `prepare_sprite_run.py` materializes an approved template automatically when available; generation is only the cache miss path. The mannequin's fixed anatomical colors prove left/right limb continuity; they are motion evidence only and must not leak into character identity or style.

3. Generate or import real row art.
   - Use `$imagegen` for generated user-facing art. Never substitute procedural drawings, placeholder drawings, SVGs, or PIL sheets for representative art.
   - Before a locomotion row, run `scripts/check_motion_references.py --run-dir /abs/run`. A missing reference, undersized image, missing sidecar, or provenance other than `art_engine=imagegen` blocks row generation.
   - Write or preserve `source-provenance.json` with `art_engine: "imagegen"` and selected source paths before extraction. For existing user sheets, record imported/user-provided provenance and keep it separate from generated-art claims.

4. Extract, curate, compose, preview, and QA.
   - Follow `references/workflows.md` for exact commands for new sheets, imported sheets, atlas unpacking, curation, GIFs, and exports.
   - For imported/generated whole sheets, do not trust a nominal grid when dimensions, gutters, or visual placement drift. Prefer a trusted manifest, explicit grid, authored boxes, or projection-grid repair when the expected rows/columns are known. Auto-detect is diagnostic by default: if `qa/segmentation-report.json` says the boxes are wrong, auto-detected, or projection-repaired, fix layout/background/source or promote reviewed boxes before registration/composition.
   - Matte conservatively. `auto` may use edge-connected matte removal for simple opaque imagegen checker/white/key-like backgrounds, chroma for clean flat keys, and rembg/BEN2 for complex non-flat backgrounds. `rembg` output must not get chroma-cleaned again unless explicitly requested with `post_rembg_chroma_cleanup`; over-removal of clothing, outlines, props, interiors, or antialiasing is a hard extraction failure. For hard/final cutouts, explicitly compare chroma/matte/rembg/BEN2 candidates and review `qa/background-matte-review.png` before atlas composition.
   - Use Pixel-art profile and workflow QA as a critique pass: 3x3 tile repetition, full-speed motion, locomotion contact/pass logic, attack phase readability, VFX loop math, tiny-sprite economy, projection uniformity, and palette/cluster discipline where relevant.
   - For isometric tilesets, do not approve isolated slots only. Run `check_asset_slots.py` and `check_isometric_tiles.py`, then review pivot, 2:1 footprint, map-repeat, edge/corner, and depth-sort proof images. Runtime/prototype placement must consume `qa/isometric-runtime-metadata.json` or a reviewed catalog copied from `qa/isometric-calibrated-catalog.json`; never place isometric cells from rectangular top-lefts or stale declared pivots.

Done when source provenance, transparent frames, atlas PNG, manifest, previews, QA reports, and any curation/export artifacts match the requested asset kind.

## Identity And Motion Rules

- Base image creates identity source.
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
- Grounded pose rows keep feet on the shared baseline. Airborne rows keep the same body size and move through the slot using the jump/fall arc.
- Side-view and mascot locomotion rows also keep feet on the shared baseline so body bob, stride, and support-side changes survive extraction.
- Generate paired basis row first for directional locomotion, then paired row with basis as rhythm reference.
- 4-, 6-, and 8-frame `walk/run/move/advance/retreat/dash` rows get motion-phase layout guides by default so legs alternate contact/passing poses instead of drifting in one direction. Prefer 8 frames for fighting-game advance/retreat when quality matters.
- Run `check_animation_contracts.py` for every animated row that has or infers an `animation_workflow`. It checks workflow-specific phase evidence for locomotion, combat, top-down attacks, jumps, reactions, VFX, water, wind, pickups, idles, and tiny sprites, then writes the visual checklist that still gates approval.
- Run `check_frame_alignment.py` for every animated sprite run. It writes `qa/frame-alignment-report.json` plus `qa/<state>-onion.png` overlays that compare real extracted frames, baseline, bboxes, and alpha centers. Do not approve jump, fall, land, crouch, knockdown, block, idle, or locomotion rows without reviewing the relevant onion skin.
- Run `check_motion_variation.py` for walk/run/move rows. It checks lower-body silhouette change, support-side balance, and body-center drift so frozen joints or same-leg poses get caught before done. Weak support alternation is a failure for locomotion unless deliberately downgraded with `--support-warn-only` for hover/float/no-leg designs.
- Treat the motion report as a heuristic, never final approval. For every walk/run/move row, inspect playback/contact sheets and confirm frame 1 and frame 3 show opposite support/contact legs; pass/down frames must not keep both legs drifting to the same side. Same-side contact legs are a hard row failure. If visual leg phase fails, the row fails even when the JSON says `ok`.
- Mirror only when user approves and asymmetric details stay correct.
- Locomotion is experimental until preview GIF passes motion QA.
- If a row partially works, use `compose_selected_cycle.py`; do not pretend full row passed.

## QA And Outputs

Read `references/qa-and-outputs.md` before final packaging. Completion criterion: QA reports, previews, atlas, manifest, and exports match the requested asset kind.
