---
name: spritesheet-expert
description: "Build and review spritesheets: irregular item segmentation, rectangular atlases, exact grids, animation rows, video frames, tilesets and textures. Includes portable Studio workspaces, optional local models, provenance and lane-specific QA."
---

# Spritesheet Expert

## Choose One Workflow

Use the source and requested result to choose a lane, not the file extension.
[workflow-lanes.json](references/workflow-lanes.json) is the shared CLI/Studio registry.

| Lane | Use for | Read | Final gate |
| --- | --- | --- | --- |
| `static-items` | Irregular items, characters with accessories, buildings with smoke | [Local item workflow](references/local-model-item-workflow.md) | `validate_item_delivery.py` |
| `true-grid` | Exact slots or a non-temporal variant set | [Row workflows](references/workflows.md) | `validate_run.py --stage pre-package` |
| `animation` | Temporal rows or selected video frames | [Animation workflows](references/pixel-animation-workflows.md); [video guide](references/video-animation-workflow.md) for video sources | `validate_run.py --stage pre-package` |
| `tileset` | Adjacent tiles or repeat textures | [Atlas reference](references/atlas-reference.md); [isometric guide](references/isometric-tilesets.md) for isometric assets | `validate_run.py --stage pre-package` |

Run `scripts/check_workflow.py --run-dir <run> --describe` to inspect the resolved
lane and exact final command. Without `--describe`, it executes that command.
Declare `frame_semantics` in the request; `--lane` checks that selection, never overrides it. Do not create a
`sprite-request.json` merely to satisfy the wrong validator for an item atlas.

Before an end-to-end batch, read [production-workflow.md](references/production-workflow.md).
Freeze accepted source hashes, style, camera, apparent scale and output contract.
Project quotas belong to the accepted project profile, never to every workflow.

## Optional Explicit Pixel-Art Conversion

When the user specifically asks to convert existing imagery to pixel art, use or suggest the project-owned [pixel-art conversion route](references/pixel-art-conversion.md). Run `scripts/convert_pixel_art.py` with an explicit request. It preserves common frame placement and sampled partial alpha, and reduces RGB with one shared palette. It creates a new imported source revision for the existing lane.

Retro styling, extraction, packing or animation requests alone do not activate conversion. Keep those workflows unchanged. This optional import transform is not procedural generation or a local production-art patch. Review the converted source before reusing it; previous source approval does not transfer.

## Static Items And Portable Workspaces

Use `scripts/serve_item_studio.py` or the same
`scripts/run_item_atlas_workflow.py` runner from CLI.
Keep each visual group together; models may propose joins, splits and labels.
Deterministic code owns every visible pixel: assigned once, pending, or explicitly
discarded. Preserve original RGBA, scale and orientation. Never silently delete
small fragments or trust a model's confidence as proof.

Packing uses consecutive, largest-first rectangular shelves, configurable padding,
and bounded pages. It never rotates or scales sprites to fit. Tags belong to stable
IDs, outside PNG pixels. Review pixels, semantics and placement separately; changed
inputs invalidate the affected approval. Inspect light and dark crops before approval.

Every finished item run also writes a self-contained curation playground to
`qa/item-playground/index.html`; rebuild it with `scripts/build_item_playground.py`.
Filter items by QA flag and decision, inspect crops on neutral backgrounds, export the
`item-review-v1` JSON, and apply it with `apply_item_review.py`. The playground never
mutates the run.

Use `manage_studio_workspace.py` to import, adopt, group, archive and export runs.
Workspaces store data with relative paths; runtime environments and weights stay
outside them. Row/grid/animation/tileset snapshots retain their own validators.
A saved snapshot is not a validated engine delivery.

Read [model-runtime/README.md](model-runtime/README.md) before model setup.
Install locked dependencies separately from checkpoints. Use offline inference
after preparation; rebuild the environment after moving the skill and reuse weights.

## Mandatory Imagegen Rule And Grok Exception

- Use `$imagegen` for new still artwork unless the user selects another supported provider. Imported sources keep imported provenance; local analysis does not make them provider-generated.
- Request native transparency for isolated stills. Keep valid provider alpha after checking exterior, semitransparent edges, halos and cross-slot bleed.
- If alpha is absent or fails review, use flat gray, black, or white and reviewed model-backed removal. New production sources must not use chroma colors; green, blue, cyan, or magenta are legacy-import chroma only. Full-bleed textures follow their repeat contract.
- Local procedural/PIL/SVG drawings are fixtures or geometry diagnostics, never representative production art.
- Copy selected media into the run and record exact provenance before extraction. Component-row runs use `scripts/check_generation_provenance.py`; `--allow-imported-source` is only for known imports and `--allow-fixture` only for tests. Item delivery checks its source provenance directly.

## Optional Grok Imagine Provider

When the user selects Grok, load `$grok-imagine` and
[references/grok-video-animation.md](references/grok-video-animation.md).
Keep provider execution in its adapter: dry-run first, current-task consent before
`--ack-run`. Never call paid inference from tests or hide it in skill scripts.
One successful media call completes that approved job; inspect it before requesting
another. Provider errors and missing returned media remain blocked, not placeholders.

## Row, Animation And Tile Work

Prepare the explicit request with `preset_to_request.py` and `prepare_sprite_run.py`.
For a non-temporal character set, set `"frame_semantics": "variants"` in the request
passed to `prepare_sprite_run.py`. When importing an atlas, use
`unpack_atlas_run.py --frame-semantics variants`. Do not inherit the sprite animation default.
Follow the selected lane's guide for intake, extraction, curation, registration,
composition and QA. Fixed cells require a true grid. Otherwise inspect adaptive
source boxes; valid native alpha does not need rematting.

For pixel art, read [pixel-art-direction.md](references/pixel-art-direction.md).
For animated characters, read [professional-sprite-animation.md](references/professional-sprite-animation.md).
For non-human/anatomy-driven motion, also read [creature-animation.md](references/creature-animation.md).
For neutral matte removal, read [lucida-adaptive-workflow.md](references/lucida-adaptive-workflow.md).

- Declare identity anchor, camera, anatomy, motion driver, semantic phases and timing before animation generation.
- Use approved, hash-matching motion references. Pending templates block that template route; generate real provider references or supply an approved one.
- Existing videos go through `ingest_video_animation.py`. Review the full timeline and selector, then re-ingest exact chronological indices without new inference.
- Registration needs the explicit runtime cell and pivot. It may remove extraction jitter, not hide real motion, change anatomy, or recover clipped source pixels.
- A contact sheet proves inventory and order. Animation additionally needs playback, contact/onion and identity proof; tiles need repeat/adjacency, projection, pivot and map proof.
- Use [qa-and-outputs.md](references/qa-and-outputs.md) for component-row packaging. It is not the static-item final gate.
- Leave a self-contained review workbench at `qa/preview-workbench/index.html` (`scripts/build_preview_workbench.py`) with every finished row, animation, or tileset run.

## Failure Prevention Contract

Keep original inputs, immutable successors and current evidence hashes. Rebuild
affected proof after source, request, selection, mask, label, pivot or layout changes.
Never infer approval from a model result, old evidence, cached completion flag or
successful ZIP export.

Reject source clipping, foreign pixels, duplicate ownership and lost silhouette
details. Return semantic/art failures to the approved provider; do not draw a local
production patch. Review the cohort at native size against the accepted style lock.

Distinguish processing complete, visually reviewed, technically verified and
engine-tested. Draft export relaxes review only, never integrity. Run the selected
final gate against disk artifacts. Check the actual engine loader, texture limits,
filtering and pivots before claiming engine readiness.

Studio's Delivery Lab is a hash-verified, read-only inspection surface, not an engine
test. Editable review verifies exact folder-relative artifact paths and hashes before
enabling decisions. Replacements start a new review and preserve their own source.

Shared handoffs remain agent- and model-agnostic. Carry exact input hashes, request,
references, expected outputs, statuses and blockers. Inherit the active client's
tools and permissions; provider settings belong only in adapters.
