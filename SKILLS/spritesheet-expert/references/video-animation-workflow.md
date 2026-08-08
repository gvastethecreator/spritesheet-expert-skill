# Video Animation Workflow

Use this workflow for every animation video. The video can come from Grok, another provider, a local tool, or a user.

## Contract

The video is source media. It is not an approved spritesheet.

Keep these stages separate:

```text
source video -> full-frame analysis -> candidate cycles -> human selection
-> per-frame background removal -> safe alpha crop -> registration -> atlas -> QA
```

The source state can use any supported frame count. The adaptive selector has a specialized four-frame cycle and a general sequence mode.

The selector is required for every video-derived state. An automatic rank is a suggestion. It is not human approval.

## Import An Existing Video

Declare the state and raw layout in `sprite-request.json`. The layout capacity must hold the selected frame count.

Run this command:

```bash
python scripts/ingest_video_animation.py \
  --run-dir /abs/run \
  --state walk \
  --video /abs/source/walk.mp4 \
  --first-frame /abs/source/approved-idle.png
```

`--first-frame` is optional. If it is absent, decoder frame 0 becomes the anchor.

Use `--license` to record the terms for the imported source. The default value is `caller-provided-source-terms`.

The command copies the video into `provider/video/<state>/`. It writes hash-bound provenance and a provider-neutral source report.

## Ingest A Grok Video

Use `prepare_grok_video_animation.py` and `ingest_grok_video_animation.py`. Read `grok-video-animation.md` for provider consent and invocation checks.

Grok ingestion enters the same selector and extraction path. No later stage depends on Grok.

## Select Candidate Cycles

Ingestion decodes the complete source video at its native frame rate. It does not reduce the video to a low frame rate.

The analyzer measures these properties:

- silhouette change;
- color and pose change;
- sharpness;
- foreground size;
- center drift;
- source-boundary contact;
- chronological separation.

The analyzer writes as many as eight ranked cycles. Open this file:

```text
qa/<state>-video-frame-selector/index.html
```

The editor contains the complete video, one thumbnail for each decoded frame, candidate presets, frame slots, and a loop preview. Frames whose foreground reaches the decoded source boundary are marked `BORDE`. Safe candidate cycles rank above clipped poses even when the clipped pose has more motion.

Select any chronological frame set. Then copy the re-ingestion command or download the selection JSON.

Re-ingestion uses `--sample-indices` and `--force`. It does not call the provider.

```bash
python scripts/ingest_video_animation.py \
  --run-dir /abs/run \
  --state walk \
  --video /abs/run/provider/video/walk/source.mp4 \
  --sample-indices 0,17,35,54 \
  --force
```

The provenance gate requires `selector.evidence.json`. It also checks the report hash, video hash, selected indices, candidate count, and editor HTML hash.

## Remove The Background

Run `extract_sprite_row_frames.py` after frame selection.

Video-derived grids use independent-frame removal. Lucida processes each selected frame separately.

The extractor adds a neutral context border before model inference. Then it removes small disconnected matte noise.

The extractor calculates one alpha box for each frame. It adds transparent crop padding around that box.

The run fails if a significant source component touches an original video boundary. Padding cannot repair pixels that the video already cut.

The final cell reserves `cell.safe_margin`. The run fails if any opaque pixel enters that margin.

Declare the runtime anchor in `sprite-request.json`. A grounded example is:

```json
{
  "registration": {
    "method": "register_sprite_frames",
    "anchor": "body-bottom",
    "target_x": 0.5,
    "target_bottom": 496
  }
}
```

The extractor applies this registration while fitting the cutouts into their final cells. It must report the same grounded `bottom_y` for every grounded frame. Use `center` for hovering creatures. Do not align a multi-legged creature from one moving foot tip.

Do not use chroma-leak checks for neutral black, gray, or white sources. Run those checks only for `source_family: legacy-chroma`.

## Complete The Atlas

Continue with the normal path:

```bash
python scripts/check_generation_provenance.py --run-dir /abs/run --allow-imported-source
python scripts/extract_sprite_row_frames.py --run-dir /abs/run
python scripts/compose_sprite_atlas.py --run-dir /abs/run
python scripts/preview_animation.py --run-dir /abs/run
python scripts/check_frame_alignment.py --run-dir /abs/run
python scripts/check_identity_consistency.py --run-dir /abs/run
python scripts/check_animation_contracts.py --run-dir /abs/run
python scripts/check_motion_variation.py --run-dir /abs/run
python scripts/build_preview_workbench.py --run-dir /abs/run --force
python scripts/validate_run.py --run-dir /abs/run --stage post-extract --allow-imported-source
```

Use `register_sprite_frames.py` only for an imported or legacy run that cannot declare registration before extraction. Do not register an already registered output a second time.

Remove `--allow-imported-source` for a verified provider source such as Grok.

Review the matte, crop overlay, candidate loop, onion skin, runtime playback, identity, and motion contract. The user gives final visual approval.
