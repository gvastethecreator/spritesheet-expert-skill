# Lucida Adaptive Workflow

Use this workflow for Imagegen grids and selected video frames. Use it when poses have uneven bounds or soft glow must survive removal.

## Contract

Use one flat neutral background. Prefer black when there is no identity image. Let preparation choose gray or white when an accepted identity image has poor contrast against black.

Use this request contract:

```json
{
  "generation_background": {
    "family": "neutral",
    "name": "black",
    "hex": "#000000",
    "rgb": [0, 0, 0],
    "selection": "fallback"
  },
  "background_removal": {
    "method": "lucida",
    "model": "egeorcun/lucida",
    "revision": "6ee11122534c8de59402a589d2293c198cfbf848",
    "device": "auto",
    "input_size": 1024,
    "alpha_mode": "hard",
    "hard_alpha_threshold": 64,
    "source_family": "neutral"
  },
  "grid_segmentation": "adaptive"
}
```

Keep `alpha_mode: hard` and threshold `64` for pixel art. This converts Lucida's soft mask into stable runtime pixels. Use `alpha_mode: soft` for illustrated sprites that need translucent hair, smoke, or glow.

Keep the model revision pinned. Lucida uses custom Transformers code. Do not run a floating branch or an unreviewed revision.

## Run

Install the optional model lane:

```bash
python -m pip install -r scripts/requirements-lucida.txt
```

Use Python 3.12 or newer for this lane. Keep the core skill available on its lighter runtime when Lucida inference is not needed.

Prepare the run. New sprite component runs select Lucida and adaptive segmentation by default:

```bash
python scripts/prepare_sprite_run.py --out-dir /abs/run --character-id enemy --request /abs/run/request.json --force
```

Generate each compact grid with `$imagegen`. Use the prepared prompt and guide. Copy the accepted image to `raw/<state>.png`. Record source provenance.

For a four-frame creature state, generate one complete `2x2` grid. Do not generate each frame separately by default. If the whole grid repeatedly changes identity, document the failure before you regenerate complete active sprites separately. Do not paste a local body-part patch over an existing frame.

Run the deterministic path:

```bash
python scripts/check_generation_provenance.py --run-dir /abs/run
python scripts/extract_sprite_row_frames.py --run-dir /abs/run
```

For video ingestion, repeated neutral idles are replaced with exact copies of the accepted idle frame before extraction. Similar generated idles are not interchangeable.

Read the game's runtime cell and actor pivot before extraction. Choose the anchor from stable anatomy. Use `body-bottom` for a stable lower body mass and `center` for hovering bodies. Use `bbox-bottom` only when the lowest opaque point is a stable contact in every frame. Do not align a multi-legged body from one changing foot tip. This request fragment matches a `512x512` cell with the creature body bottom at `440`:

```json
{
  "registration": {
    "method": "register_sprite_frames",
    "anchor": "body-bottom",
    "target_x": 0.5,
    "target_bottom": 440
  }
}
```

Replace `440` with the real game target. Do not guess it from the image. Extraction applies the anchor to every final cell. Use that same run for composition and every later gate:

```bash
python scripts/compose_sprite_atlas.py --run-dir /abs/run
python scripts/preview_animation.py --run-dir /abs/run
python scripts/check_frame_alignment.py --run-dir /abs/run
python scripts/check_identity_consistency.py --run-dir /abs/run
python scripts/check_animation_contracts.py --run-dir /abs/run
python scripts/check_motion_variation.py --run-dir /abs/run
python scripts/build_preview_workbench.py --run-dir /abs/run --force
python scripts/validate_run.py --run-dir /abs/run --stage post-extract
```

## How Adaptive Cuts Work

Remove the background before frame detection. Find the main alpha component for each expected pose. Assign detached limbs, weapons, particles, and glow to the nearest pose in two dimensions. Crop each frame to its own source bounds. Then fit every crop into the shared runtime cell and baseline.

For video-derived grids, split the source cells before model inference. Process each selected frame with Lucida. Do not infer one matte for the complete grid.

Add a neutral context border before inference. Remove small disconnected matte noise after inference.

Calculate one significant alpha box for each frame. Add transparent padding around the box.

Fail if a significant component touches the original video boundary. Fail if the final sprite enters the reserved cell margin.

Do not use a fixed grid to hide a bad adaptive result. Do not use `--allow-slot-fallback` for production approval. Repair the source separation or use reviewed fixed cells only when the source is a true exact grid.

## Review

Inspect these files before atlas composition:

- `qa/background-matte-review.png`
- `qa/<state>-adaptive-segmentation.png`
- `frames/frames-manifest.json.rows[*].segmentation.spans[*].source_bbox`
- `frames/frames-manifest.json.sprite_registration.baseline_y`
- `qa/registration-overlay.png` and `qa/registration-report.json` when runtime registration runs

Reject missing limbs, cross-assigned effects, clipped glow, merged poses, detached noise, or inconsistent order. Then inspect onion skin and runtime playback. A clean cut does not prove correct game placement.

For neutral sources, do not treat black, gray, or white subject pixels as chroma leakage. Chroma checks apply only to `legacy-chroma` sources.

If an identity proxy marks raised forearms or wings as a larger head or torso, keep the standard report. Inspect the contact, onion, and runtime playback. Run a pose-aware comparison only when those images prove that the stable body parts did not change. Record the reason and thresholds. Do not use this protocol to excuse visible scale drift.

Lucida is a BiRefNet fine-tune released under MIT. Its upstream documentation also lists mixed training-data licenses. Review those terms before commercial release.
