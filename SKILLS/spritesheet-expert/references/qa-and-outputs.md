# Spritesheet Expert QA And Outputs

## QA

Block done unless:

- `validate_run.py --stage pre-package` exits `0` and `qa/run-validation-report.json.status` is `pass`. This aggregate report is the final machine decision; individual commands remain useful diagnostics but cannot replace it.
- `frames/frames-manifest.json.ok` true.
- `qa/generation-provenance-report.json.status` is `pass` for production art. Provenance uses exact source types, safe run-relative paths, byte sizes, SHA-256 and complete state coverage; substring hints are never accepted. Procedural/PIL/synthetic art passes only with explicit fixture mode and cannot be called representative. Imported/user-provided sheets require verified provenance and `--allow-imported-source`.
- `references/art-direction.json` exists for pixel-art runs, and active row profiles plus `animation_workflows` match the asset kind/state before generation or final review.
- `frames/frames-manifest.json.sprite_registration.reference_height`, `reference_width`, `reference_scale`, and stable proxy values exist for sprite runs, and jump/crouch/fall/land frame records show reasonable `height_vs_reference`, `width_vs_reference`, `head_width_vs_reference`, `upper_width_vs_reference`, `expected_height_vs_reference`, and `bottom_y` for their pose profile.
- Crouch/duck/squat transition rows are compared frame-to-frame: early frames can be taller, final frames must be visibly compressed, final width should usually stay at least around 0.78x of idle width, head/upper-body proxies should remain near idle scale, and the sequence must not shrink uniformly as it settles into the crouch.
- `frames/frames-manifest.json.rows[*].background_method` records `alpha`, `matte`, `lucida`, `rembg`, `ben2`, or legacy `chroma`, and `background_removal` matches the intended request. Native-transparent generation records `background_method: alpha`; neutral fallback generation declares `source_family: neutral`; only imported legacy rows may declare `legacy-chroma`. `rows[*].method` records whether extraction used `grid-adaptive-components`, `grid-components`, `components`, `projection-strip`, or slot extraction.
- Adaptive rows include one `source_bbox` per frame and a current `qa/<state>-adaptive-segmentation.png`. Review frame order, complete limbs, detached effects, variable bounds, and cross-frame assignment. `grid-slots-fallback` cannot pass production review.
- `frames/frames-manifest.json.background_matte_review` points to `qa/background-matte-review.png`. Review raw, checker, black, gray, white, and alpha-mask panels for missing alpha, opaque backdrops, over-removal, fringe, halos, and cross-slot bleed. Valid provider alpha needs the same review. For a fallback matte, a model name is not proof; the selected Lucida, BiRefNet, or BEN2 matte must win visual review for this source.
- Legacy chroma output uses a soft-edge/despill matte, not a hard key threshold. Run `check_chroma_key_safety.py`, `rekey_chroma_background.py`, and chroma leakage review only for those declared legacy sources.
- `sprite-sheet-alpha.report.json.ok` true.
- `manifest.json.frame_layout` exists and runtime can use rectangles.
- Imported or irregular whole-sheet candidates have `qa/segmentation-report.json` and `qa/segmentation-overlay.png` from `unpack_atlas_run.py`. Review the overlay before registration; bad boxes mean the matte/segmentation step failed, not that alignment needs tweaking. Auto-detect and projection-repair layout warnings block production packaging until a trusted manifest/grid/authored-box layout replaces them.
- Imported or whole-sheet sprite candidates have `qa/registration-report.json.ok` true after `register_sprite_frames.py`, unless an existing trusted manifest already provides exact rectangles and origins. Review `qa/registration-overlay.png` for stable body pivot/baseline before judging animation.
- Animated rows with active or inferred `animation_workflows` have `qa/animation-contract-report.json.ok` true. Treat the report as a workflow gate: hard errors block done, warnings require review notes or repair, and `visual_review_checklist` items still require playback/contact/prototype inspection.
- Animated sprite runs have `qa/frame-alignment-report.json.ok` true from `check_frame_alignment.py`, and relevant `qa/<state>-onion.png` overlays are reviewed. This gate compares real extracted frames, not prompts: baseline, bbox, alpha-center/root, takeoff/landing closure, and final ground settlement must make sense.
- Jump rows require takeoff and landing bottoms on the same shared baseline within tolerance, a visible airborne arc, and no accidental root-x drift unless the state is intentionally a forward/back jump. Crouch/block/idle/locomotion rows keep grounded contact stable. Fall/knockdown rows must settle to the baseline by the final frame.
- Animated character runs and multi-frame static character pose/direction sets have `qa/identity-consistency-report.json.ok` true from `check_identity_consistency.py`. Head size, upper-body scale, central body-mass width, and opaque-area proxy drift are blocking identity failures unless the row is a deliberate fall/knockdown/crouch pose with visual evidence that the apparent change is pose/orientation, not zoom or redesign. A static `variants` label never waives same-character identity.
- Contact sheets and deterministic GIF/PNG runtime evidence are reviewed for identity, frame count, direction, loop seam, timing, and pose scale/baseline overlays.
- `qa/preview-workbench/index.html` and `qa/preview-workbench/workbench.evidence.json` exist for animated review. The report hashes the atlas, manifest, linked QA evidence, and self-contained HTML. Use pause, step, scrub, speed, zoom, state selection, every filmstrip frame, and checker/black/gray/white backgrounds; keyboard controls and layouts down to 360px must remain usable without page overflow. Initial zoom must fit the measured stage (including high-resolution provider frames), and canvas scaling must honor the manifest's `sampling_policy`: crisp nearest-neighbor for pixel art, smooth linear sampling for illustrated art.
- Runtime animation playback is reviewed for state changes, frame timing, origin/baseline stability, bbox scale, and input-driven movement. The workbench is the human inspection surface; hash-bound deterministic GIF/PNG evidence remains the machine gate.
- For pose-sensitive rows, visually review `qa/pose-scale-review.png` when present. Metrics are necessary but not sufficient; if the pose reads wrong, the row fails even when `frames-manifest.json.ok` is true.
- Visual review includes pose readability, silhouette, line of action, center of mass, grounded contact, plausible joints, and whether the state communicates its gameplay purpose.
- Fighting/combat rows show clear startup/active/recovery or impact/reaction staging; do not accept pretty poses that are ambiguous as gameplay frames.
- Pixel combat rows identify stance, startup/load if needed, smear with main motion, hit/contact, follow-through, recovery, and overshoot, with visual range matching intended hitbox.
- Pixel quick-strike rows avoid unnecessary windup; power-strike rows justify load/anticipation through weight, range, or commitment. Smears stay brief and follow the main motion.
- Pixel top-down weapon rows show anticipation, forward smear, optional rebound, follow-through, and recover; weapon handedness and hitbox reach stay consistent across directions.
- Pixel motion rows preserve keyframes over smooth filler: locomotion has contact/pass logic, loops reconnect without pops, and playback has energy rather than sluggish in-betweens.
- Pixel side-view locomotion rows show contact/down/pass/swing or an intentional low-frame equivalent. Pixel top-down locomotion rows show direction strategy, variable bounce, and projection consistency.
- Pixel texture/tile rows pass zoomed-out repetition review such as 3x3 tiling, edge compatibility, negative-space balance, and scale-appropriate cluster density.
- Pixel top-down/isometric rows preserve one projection system; isometric rows follow 2:1 construction and surface-specific tileability where relevant.
- Pixel tiny rows keep missing-information economy: no unnecessary detail, no excessive frames, and one-pixel motion scale where applicable.
- Pixel VFX rows show buildup/peak/decay, stable emitter/contact point, alpha-safe fade, and loop math without end-to-start pop. Water rows show wave/flow loop closure; wind rows show flow points/propagation instead of random motion.
- When no base image was provided, `references/identity-anchor.png` exists and later generated rows visibly follow that anchor instead of drifting into a new character.
- User-facing generated art was backed by the declared `$imagegen` or `$grok-imagine` source media; synthetic fixtures are labeled as fixtures only.
- Every video row has a hash-bound `video-source.json`. Grok rows also retain the completed invocation and exact first-frame evidence.
- Multi-identity animation batches have a passing `batch-completion-report.json` from `check_animation_batch_completion.py`. Quota videos, final accepted sources, Imagegen repairs, and archived reports are counted separately; recursive file count is never quota evidence.
- Every video row has `qa/<state>-video-frame-selector/index.html` and `selector.evidence.json`. The evidence matches the report, video, selected indices, candidates, and HTML hashes.
- Video extraction applies background removal per selected frame. Each segmentation span records alpha bounds, crop padding, context padding, discarded noise, and source-edge contacts.
- A video row fails when a significant source component touches a video boundary. It also fails when opaque pixels enter the final safe margin.
- Failed provider jobs use blocked sidecars or clear status/log errors instead of fake row images.
- `qa/motion-variation-report.json.ok` true for walk/run/move sprite rows, unless explicitly waived for non-legged/hovering motion after visual review.
- Walk/run/move rows also need a visual leg-phase gate. Frame 1 and the halfway contact frame must show opposite anatomical support/contact legs; pass/down frames must show the crossover or depth swap that connects them, and each direction row is reviewed independently in chronological playback. Screen-space left/right balance is diagnostic only and cannot name the anatomical leg. Repeated same-leg contact is a hard failure even when `motion-variation-report.json.ok` is true.
- Planted gestures use both a lower-mask change ceiling (`0.25`) and a stricter horizontal footprint-center range (`0.025`). The mask tolerance allows small provider/matte silhouette variation; the center gate still rejects the visible leg/root travel seen in the prior greeting.
- Planted gesture rows need two independent proofs: loop closure and lower-body stability. `check_animation_contracts.py` must report `metrics.gesture_planted_lower_body.ok: true`; visual review must confirm that pelvis, knees, ankles, feet, and contact footprint do not translate during the middle frames. Registration must not be used to hide animated legs or root travel.
- Tilesets reviewed for exact grid/authored-box alignment, labels, catalog metadata, edge compatibility, projection consistency, collision roles, and no accidental scene/collage output.
- Asset/prop packs reviewed for `strategy_class`; square compact packs may contain only `compact_prop`. Wide/long, tall/large, collision-bearing, and tileset/strip pieces require a different sheet shape.
- Isometric tilesets have `qa/isometric-tile-review.json.ok` true from `check_isometric_tiles.py`. Review `qa/isometric-pivot-overlay.png`, `qa/isometric-map-review.png`, and `qa/isometric-depth-review.png`; the 2:1 footprint, runtime cell, pivots, edge/corner roles, and depth sorting must make sense in a map, not only as isolated slots.
- Isometric prototypes/importers consume `qa/isometric-runtime-metadata.json`. If `qa/isometric-calibrated-catalog.json` differs from the source catalog, approve/copy the corrected footprint and pivots, rerun the pipeline, and do not package against stale metadata.
- Textures declare `asset_catalog.items.*.repeat_mode: self`, fill the runtime cell edge-to-edge, pass numeric left/right and top/bottom edge-strip comparison in `qa/asset-slot-review.json.repeat_validation`, and receive a 3x3 repeat review for every delivered sample. Consistent texel density, no labels, no framed swatches, and no perspective scenes remain blocking visual checks.
- Tiles declare `repeat_mode` per catalog item: `self`, `adjacency`, or `overlay`. Self tiles pass the same numeric edge gate as textures and get one labeled 3x3 preview per delivered item. Adjacency tiles require distinct `tile_role` values plus `qa/tile-adjacency-review.png`; overlay tiles require isolation review. A contact sheet or unlabeled montage alone is not adjacency proof.
- Full-bleed slot extraction uses a centered cover crop before resize so odd provider dimensions cannot introduce a one-pixel transparent seam.
- `qa/tile-repeat-review.png` includes every `repeat_mode: self` item with its catalog label; it does not silently sample only the first slots.
- Provider-derived edge repair must leave `qa/repeat-edge-repair-report.json`, immutable provider-source copies, original-frame backups, and fresh per-item repeat previews. A targeted provider retry may use periodic phase crop before a narrow edge-band harmonization; the report must record both widths and hashes. Repaired metrics without those artifacts are not approval evidence.
- Still assets reviewed for set consistency, silhouette, scale, isolation, and slot boundaries.
- No visible chroma, guide marks, labels, scene backgrounds, shadows outside cells, slot overlap, or cropped body parts.

Repair smallest failing scope: row first, extraction second, full regeneration last.

## Outputs

Normal run folder:

```text
sprite-request.json
references/layout-guides/<state>.png
references/identity-anchor.png
references/identity-anchor.json
references/art-direction.json
prompts/<state>.txt
raw/<state>.png
frames/<state>/frame-N.png
frames/frames-manifest.json  # includes background_method, sprite_registration, and per-frame bbox/height metrics
curation.json
sprite-sheet-alpha.png
sprite-sheet-alpha.report.json
manifest.json
qa/<state>-contact.png
qa/<state>.gif
qa/pose-scale-review.png
qa/background-matte-review.png
qa/<state>-adaptive-segmentation.png
qa/preview-workbench/index.html
qa/preview-workbench/workbench.evidence.json
qa/frame-alignment-report.json
qa/identity-consistency-report.json
qa/<state>-onion.png
qa/preprocessed-atlas-alpha.png
qa/segmentation-report.json
qa/segmentation-overlay.png
qa/registration-report.json
qa/registration-overlay.png
qa/generation-provenance-report.json
qa/visual-review.json
qa/run-validation-report.json
qa/animation-contract-report.json
qa/motion-variation-report.json
qa/asset-slot-review.json
qa/asset-slot-overlay.png
qa/tile-repeat-review.png
qa/isometric-tile-review.json
qa/isometric-pivot-overlay.png
qa/isometric-map-review.png
qa/isometric-depth-review.png
qa/isometric-runtime-metadata.json
qa/isometric-calibrated-catalog.json
provider/grok-imagine/<state>/prompt.txt
provider/grok-imagine/<state>/job.json
provider/grok-imagine/<state>/video-source.json
provider/video/<state>/video-source.json
provider/video/<state>/source.mp4
qa/<state>-video-frame-selector/index.html
qa/<state>-video-frame-selector/selector.evidence.json
batch-completion-report.json  # beside a multi-identity batch manifest
```

Use `manifest.json.frame_layout` as runtime SSoT. Do not recover frame rectangles from alpha at runtime.

Run the aggregate gate at each useful boundary:

```bash
python scripts/validate_run.py --run-dir /abs/run --stage preflight
python scripts/validate_run.py --run-dir /abs/run --stage post-extract
python scripts/validate_run.py --run-dir /abs/run --stage pre-package
```

`pre-package` returns `2` while required visual review is missing, `1` for contract/quality failures, and `3` for operational failures. A partial `--gate` selection is diagnostic and can never produce an aggregate final green.

For a complete animation batch, run the batch gate after every run has passed `pre-package` and its runtime candidate has been packaged:

```bash
python scripts/check_animation_batch_completion.py --repo-root /abs/project --batch-manifest /abs/project/path/to/batch-manifest.json
```

The batch report is the final machine decision for inventory, quota accounting, provenance, selector freshness, repairs, and packaged-candidate freshness. It does not replace individual visual approval.
