# Spritesheet Expert QA And Outputs

## QA

Block done unless:

- `validate_run.py --stage pre-package` exits `0` and `qa/run-validation-report.json.status` is `pass`. This aggregate report is the final machine decision; individual commands remain useful diagnostics but cannot replace it.
- `frames/frames-manifest.json.ok` true.
- `qa/generation-provenance-report.json.status` is `pass` for production art. Provenance uses exact source types, safe run-relative paths, byte sizes, SHA-256 and complete state coverage; substring hints are never accepted. Procedural/PIL/synthetic art passes only with explicit fixture mode and cannot be called representative. Imported/user-provided sheets require verified provenance and `--allow-imported-source`.
- `references/art-direction.json` exists for pixel-art runs, and active row profiles plus `animation_workflows` match the asset kind/state before generation or final review.
- `frames/frames-manifest.json.sprite_registration.reference_height`, `reference_width`, `reference_scale`, and stable proxy values exist for sprite runs, and jump/crouch/fall/land frame records show reasonable `height_vs_reference`, `width_vs_reference`, `head_width_vs_reference`, `upper_width_vs_reference`, `expected_height_vs_reference`, and `bottom_y` for their pose profile.
- Crouch/duck/squat transition rows are compared frame-to-frame: early frames can be taller, final frames must be visibly compressed, final width should usually stay at least around 0.78x of idle width, head/upper-body proxies should remain near idle scale, and the sequence must not shrink uniformly as it settles into the crouch.
- `frames/frames-manifest.json.rows[*].background_method` records `alpha`, `chroma`, `rembg`, or `ben2`, and `background_removal` matches the intended request. `rows[*].method` records whether extraction used `grid-components`, `components`, `projection-strip`, or slot extraction. Chroma rows should use `chroma_mask: border-connected` and be checked for internal alpha holes in clothing/props. `rembg` rows should not use post-chroma cleanup unless `background_removal.post_rembg_chroma_cleanup` is explicitly true and visual QA proves no subject pixels were damaged.
- `frames/frames-manifest.json.background_matte_review` points to `qa/background-matte-review.png`. Review raw, checker, dark, and alpha-mask panels for over-removal before approving generated rows. `background_method: ben2` is acceptable only when selected explicitly for hard/final cutouts and the BEN2 review beats rembg/chroma visually.
- Chroma output uses a soft-edge/despill matte, not a hard key threshold. Review extracted frames against checker, dark, and high-contrast solid backgrounds for halos, jagged cut edges, and leftover key-color fringe.
- `check_chroma_key_safety.py` passes, or any `warn/fail` result is resolved: `fail` requires safer key/rembg/regeneration; `warn` requires alpha preview or curation proof that exact-key islands are not subject pixels.
- `sprite-sheet-alpha.report.json.ok` true.
- `manifest.json.frame_layout` exists and runtime can use rectangles.
- Imported or irregular whole-sheet candidates have `qa/segmentation-report.json` and `qa/segmentation-overlay.png` from `unpack_atlas_run.py`. Review the overlay before registration; bad boxes mean the matte/segmentation step failed, not that alignment needs tweaking. Auto-detect and projection-repair layout warnings block production packaging until a trusted manifest/grid/authored-box layout replaces them.
- Imported or whole-sheet sprite candidates have `qa/registration-report.json.ok` true after `register_sprite_frames.py`, unless an existing trusted manifest already provides exact rectangles and origins. Review `qa/registration-overlay.png` for stable body pivot/baseline before judging animation.
- Animated rows with active or inferred `animation_workflows` have `qa/animation-contract-report.json.ok` true. Treat the report as a workflow gate: hard errors block done, warnings require review notes or repair, and `visual_review_checklist` items still require playback/contact/prototype inspection.
- Animated sprite runs have `qa/frame-alignment-report.json.ok` true from `check_frame_alignment.py`, and relevant `qa/<state>-onion.png` overlays are reviewed. This gate compares real extracted frames, not prompts: baseline, bbox, alpha-center/root, takeoff/landing closure, and final ground settlement must make sense.
- Jump rows require takeoff and landing bottoms on the same shared baseline within tolerance, a visible airborne arc, and no accidental root-x drift unless the state is intentionally a forward/back jump. Crouch/block/idle/locomotion rows keep grounded contact stable. Fall/knockdown rows must settle to the baseline by the final frame.
- Animated character runs have `qa/identity-consistency-report.json.ok` true from `check_identity_consistency.py`. Head size, upper-body scale, central body-mass width, and opaque-area proxy drift are blocking identity failures unless the row is a deliberate fall/knockdown/crouch pose with visual evidence that the apparent change is pose/orientation, not zoom or redesign.
- Contact sheet/GIFs reviewed for identity, frame count, direction, loop seam, motion when animated, and pose scale/baseline overlays for jump/crouch/fall/land rows.
- Runtime animation playback reviewed for animated sprite runs: state changes, frame timing, origin/baseline stability, bbox scale, and input-driven movement must read correctly in a canvas/game loop or equivalent engine preview.
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
- User-facing generated art was backed by `$imagegen` row sources when `$imagegen` was available; synthetic fixtures are labeled as fixtures only.
- Failed provider jobs use blocked sidecars or clear status/log errors instead of fake row images.
- `qa/motion-variation-report.json.ok` true for walk/run/move sprite rows, unless explicitly waived for non-legged/hovering motion after visual review.
- Walk/run/move rows also need a visual leg-phase gate. Frame 1 and frame 3 must show opposite support/contact legs, pass/down frames must not repeat the same-side leg pose, and each direction row is reviewed independently at playback speed. Same-side contact legs are a hard failure, not a polish issue. Metrics are a heuristic only; if the legs read wrong, the row fails even when `motion-variation-report.json.ok` is true.
- Tilesets reviewed for exact grid/authored-box alignment, labels, catalog metadata, edge compatibility, projection consistency, collision roles, and no accidental scene/collage output.
- Asset/prop packs reviewed for `strategy_class`; square compact packs may contain only `compact_prop`. Wide/long, tall/large, collision-bearing, and tileset/strip pieces require a different sheet shape.
- Isometric tilesets have `qa/isometric-tile-review.json.ok` true from `check_isometric_tiles.py`. Review `qa/isometric-pivot-overlay.png`, `qa/isometric-map-review.png`, and `qa/isometric-depth-review.png`; the 2:1 footprint, runtime cell, pivots, edge/corner roles, and depth sorting must make sense in a map, not only as isolated slots.
- Isometric prototypes/importers consume `qa/isometric-runtime-metadata.json`. If `qa/isometric-calibrated-catalog.json` differs from the source catalog, approve/copy the corrected footprint and pivots, rerun the pipeline, and do not package against stale metadata.
- Textures reviewed for seamless/tileable intent, consistent texel density, and no labels or perspective scenes.
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
```

Use `manifest.json.frame_layout` as runtime SSoT. Do not recover frame rectangles from alpha at runtime.

Run the aggregate gate at each useful boundary:

```bash
python scripts/validate_run.py --run-dir /abs/run --stage preflight
python scripts/validate_run.py --run-dir /abs/run --stage post-extract
python scripts/validate_run.py --run-dir /abs/run --stage pre-package
```

`pre-package` returns `2` while required visual review is missing, `1` for contract/quality failures, and `3` for operational failures. A partial `--gate` selection is diagnostic and can never produce an aggregate final green.
