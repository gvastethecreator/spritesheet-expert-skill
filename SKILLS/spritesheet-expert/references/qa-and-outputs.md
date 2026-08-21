# Spritesheet Expert QA And Outputs

## QA

Block done unless:

- `validate_run.py --stage pre-package` exits `0` and `qa/run-validation-report.json.status` is `pass`. Aggregate report is final machine decision; other commands can't replace it.
- `frames/frames-manifest.json.ok` true.
- `qa/generation-provenance-report.json.status` is `pass` for production art. Provenance: exact source types, safe run-relative paths, byte sizes, SHA-256, full state coverage; no substring hints. Procedural/PIL/synthetic art passes only in explicit fixture mode — not representative. Imported/user sheets need verified provenance and `--allow-imported-source`.
- `references/art-direction.json` exists for pixel-art runs, and active row profiles plus `animation_workflows` match asset kind/state before generation or final review.
- `frames/frames-manifest.json.sprite_registration.reference_height`, `reference_width`, `reference_scale`, and stable proxy values exist for sprite runs. Jump/crouch/fall/land records show plausible `height_vs_reference`, `width_vs_reference`, `head_width_vs_reference`, `upper_width_vs_reference`, `expected_height_vs_reference`, and `bottom_y` for their pose profile.
- Crouch/duck/squat rows compared frame-to-frame: early frames may be taller; final frames read compressed; final width ≥ ~0.78× idle width; head/upper-body proxies stay near idle scale; sequence mustn't shrink uniformly into crouch.
- `frames/frames-manifest.json.rows[*].background_method` records `alpha`, `matte`, `lucida`, `rembg`, `ben2`, or legacy `chroma`, and `background_removal` matches request. Native-transparent → `background_method: alpha`; neutral fallback → `source_family: neutral`; only imported legacy rows may declare `legacy-chroma`. `rows[*].method`: `grid-adaptive-components`, `grid-components`, `components`, `projection-strip`, or slot extraction.
- Adaptive rows include one `source_bbox` per frame and current `qa/<state>-adaptive-segmentation.png`. Review frame order, complete limbs, detached effects, variable bounds, and cross-frame assignment. `grid-slots-fallback` can't pass production review.
- `frames/frames-manifest.json.background_matte_review` points to `qa/background-matte-review.png`. Review raw, checker, black, gray, white, and alpha-mask panels for missing alpha, opaque backdrops, over-removal, fringe, halos, and cross-slot bleed. Provider alpha gets same review. Fallback matte: model name isn't proof; selected Lucida, BiRefNet, or BEN2 matte wins for this source.
- Legacy chroma uses soft-edge/despill matte, not hard key. Run `check_chroma_key_safety.py`, `rekey_chroma_background.py`, and chroma leakage review only for declared legacy sources.
- `sprite-sheet-alpha.report.json.ok` true.
- `manifest.json.frame_layout` exists and runtime can use rectangles.
- Imported or irregular whole-sheet candidates have `qa/segmentation-report.json` and `qa/segmentation-overlay.png` from `unpack_atlas_run.py`. Review overlay before registration; bad boxes = matte/segmentation failed, not alignment. Auto-detect and projection-repair layout warnings block production packaging until trusted manifest/grid/authored-box layout replaces them.
- Imported or whole-sheet sprite candidates have `qa/registration-report.json.ok` true after `register_sprite_frames.py`, unless trusted manifest already provides exact rectangles and origins. Review `qa/registration-overlay.png` for stable body pivot/baseline before judging animation.
- Animated rows with active or inferred `animation_workflows` have `qa/animation-contract-report.json.ok` true. Workflow gate: hard errors block done; warnings need review notes or repair; `visual_review_checklist` items need playback/contact/prototype inspection.
- Animated sprite runs have `qa/frame-alignment-report.json.ok` true from `check_frame_alignment.py`, and relevant `qa/<state>-onion.png` overlays are reviewed. Compares extracted frames, not prompts: baseline, bbox, alpha-center/root, takeoff/landing closure, and final ground settlement make sense.
- Jump rows: takeoff and landing bottoms on same shared baseline within tolerance, visible airborne arc, no accidental root-x drift unless state is intentional forward/back jump. Crouch/block/idle/locomotion rows keep grounded contact stable. Fall/knockdown rows settle to baseline by final frame.
- Animated character runs and multi-frame static pose/direction sets have `qa/identity-consistency-report.json.ok` true from `check_identity_consistency.py`. Head size, upper-body scale, central body-mass width, and opaque-area proxy drift block identity unless row is deliberate fall/knockdown/crouch with visual proof the change is pose/orientation, not zoom or redesign. Static `variants` never waives same-character identity.
- Contact sheets + GIF/PNG evidence: identity, frame count, direction, loop seam, timing, pose scale/baseline overlays.
- `qa/preview-workbench/index.html` and `qa/preview-workbench/workbench.evidence.json` exist for animated review. Report hashes atlas, manifest, linked QA evidence, and self-contained HTML. Pause, step, scrub, speed, zoom, state selection, every filmstrip frame, checker/black/gray/white backgrounds; keyboard/layout to 360px without overflow. Initial zoom fits measured stage (incl. high-res provider frames). Canvas scaling honors manifest `sampling_policy`: nearest-neighbor for pixel art, linear for illustrated art.
- Runtime playback: state changes, frame timing, origin/baseline stability, bbox scale, input-driven movement. Workbench: human inspection; hash-bound GIF/PNG evidence is machine gate.
- Pose-sensitive rows: visually review `qa/pose-scale-review.png` when present. Metrics necessary, not sufficient; if pose reads wrong, row fails when `frames-manifest.json.ok` is true.
- Visual review: pose readability, silhouette, line of action, center of mass, grounded contact, plausible joints, and whether state communicates its gameplay purpose.
- Fighting/combat: clear startup/active/recovery or impact/reaction; pretty poses that are ambiguous as gameplay frames fail.
- Pixel combat: stance, startup/load, smear with main motion, hit/contact, follow-through, recovery, overshoot; visual range matches intended hitbox.
- Pixel quick-strike: avoid unnecessary windup; power-strike: load/anticipation via weight, range, or commitment. Smears stay brief and follow main motion.
- Pixel top-down weapon: anticipation, forward smear, optional rebound, follow-through, recover; weapon handedness and hitbox reach stay consistent across directions.
- Pixel motion: keyframes over smooth filler; locomotion has contact/pass logic, loops reconnect without pops, playback has energy rather than sluggish in-betweens.
- Pixel side-view locomotion: contact/down/pass/swing or intentional low-frame equivalent. Pixel top-down locomotion: direction strategy, variable bounce, projection consistency.
- Pixel texture/tile: zoomed-out repetition review 3x3 tiling, edge compatibility, negative-space balance, scale-appropriate cluster density.
- Pixel top-down/isometric: one projection system; isometric rows follow 2:1 construction and surface-specific tileability where relevant.
- Pixel tiny: missing-information economy; no unnecessary detail, no excessive frames, one-pixel motion scale where applicable.
- Pixel VFX: buildup/peak/decay, stable emitter/contact point, alpha-safe fade, loop math without end-to-start pop. Water: wave/flow loop closure; wind: flow points/propagation instead of random motion.
- If no base image, `references/identity-anchor.png` exists and later generated rows visibly follow that anchor instead of drifting into new character.
- User-facing generated art was backed by declared `$imagegen` or `$grok-imagine` source media; synthetic fixtures are labeled as fixtures only.
- Every video row has hash-bound `video-source.json`. Grok rows retain completed invocation and exact first-frame evidence.
- Multi-identity batches: passing `batch-completion-report.json` from `check_animation_batch_completion.py`. Quota videos, final accepted sources, Imagegen repairs, and archived reports are counted separately; recursive file count is never quota evidence.
- Every video row has `qa/<state>-video-frame-selector/index.html` and `selector.evidence.json`. evidence matches report, video, selected indices, candidates, and HTML hashes.
- Video extraction applies background removal per selected frame. Each segmentation span records alpha bounds, crop padding, context padding, discarded noise, and source-edge contacts.
- video row fails when significant source component touches video boundary. It fails when opaque pixels enter final safe margin.
- Failed provider jobs use blocked sidecars or clear status/log errors instead of fake row images.
- `qa/motion-variation-report.json.ok` true for walk/run/move sprite rows, unless waived for non-legged/hovering motion after visual review.
- Walk/run/move rows: visual leg-phase gate. Frame 1 and halfway contact show opposite anatomical support/contact legs; pass/down frames show crossover or depth swap; review each direction row independently in chronological playback. Screen-space L/R balance is diagnostic only — can't name anatomical leg. Repeated same-leg contact is hard fail when `motion-variation-report.json.ok` is true.
- Planted gestures use both lower-mask change ceiling (`0.25`) and stricter horizontal footprint-center range (`0.025`). Mask tolerance allows small provider/matte silhouette variation; center gate rejects visible leg/root travel seen in prior greeting.
- Planted gesture rows need two independent proofs: loop closure and lower-body stability. `check_animation_contracts.py` reports `metrics.gesture_planted_lower_body.ok: true`; visual review: pelvis, knees, ankles, feet, and contact footprint don't translate in middle frames. Registration mustn't hide animated legs or root travel.
- Tilesets: exact grid/authored-box alignment, labels, catalog metadata, edge compatibility, projection consistency, collision roles, no accidental scene/collage output.
- Asset/prop packs: `strategy_class`; square compact packs may contain only `compact_prop`. Wide/long, tall/large, collision-bearing, and tileset/strip pieces require different sheet shape.
- Isometric tilesets have `qa/isometric-tile-review.json.ok` true from `check_isometric_tiles.py`. Review `qa/isometric-pivot-overlay.png`, `qa/isometric-map-review.png`, and `qa/isometric-depth-review.png`; the 2:1 footprint, runtime cell, pivots, edge/corner roles, and depth sorting make sense in map, not only as isolated slots.
- Isometric prototypes/importers consume `qa/isometric-runtime-metadata.json`. If `qa/isometric-calibrated-catalog.json` differs from source catalog, approve/copy corrected footprint and pivots, rerun pipeline, and don't package against stale metadata.
- Textures declare `asset_catalog.items.*.repeat_mode: self`, fill runtime cell edge-to-edge, pass numeric L/R and T/B edge-strip comparison in `qa/asset-slot-review.json.repeat_validation`, and get a 3x3 repeat review per delivered sample. Blocking visual checks: consistent texel density, no labels, no framed swatches, no perspective scenes.
- Tiles declare `repeat_mode` per catalog item: `self`, `adjacency`, or `overlay`. Self: same numeric edge gate as textures plus one labeled 3x3 preview per delivered item. Adjacency: distinct `tile_role` values plus `qa/tile-adjacency-review.png`. Overlay: isolation review. Contact sheet or unlabeled montage alone isn't adjacency proof.
- Full-bleed slot extraction uses centered cover crop before resize so odd provider dimensions can't introduce one-pixel transparent seam.
- `qa/tile-repeat-review.png` includes every `repeat_mode: self` item with its catalog label; it doesn't silently sample only first slots.
- Provider-derived edge repair leaves `qa/repeat-edge-repair-report.json`, immutable provider-source copies, original-frame backups, and fresh per-item repeat previews. Targeted provider retry may use periodic phase crop before narrow edge-band harmonization; report both widths and hashes. Repaired metrics without those artifacts aren't approval evidence.
- Assets: set consistency, silhouette, scale, isolation, slot boundaries.
- No visible chroma, guide marks, labels, scene backgrounds, shadows outside cells, slot overlap, or cropped body parts.

Repair smallest scope: row first, extraction second, full regeneration last.

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

Use `manifest.json.frame_layout` as runtime SSoT. Don't recover frame rectangles from alpha at runtime.

Run aggregate gate at each useful boundary:

```bash
python scripts/validate_run.py --run-dir /abs/run --stage preflight
python scripts/validate_run.py --run-dir /abs/run --stage post-extract
python scripts/validate_run.py --run-dir /abs/run --stage pre-package
```

`pre-package` exits `2` if required visual review missing, `1` for contract/quality failures, `3` for operational failures. Partial `--gate` is diagnostic — never aggregate final green.

Complete animation batch: run batch gate after every run passed `pre-package` and runtime candidate packaged:

```bash
python scripts/check_animation_batch_completion.py --repo-root /abs/project --batch-manifest /abs/project/path/to/batch-manifest.json
```

Batch report: final machine decision for inventory, quota, provenance, selector freshness, repairs, packaged-candidate freshness. Doesn't replace visual approval.
