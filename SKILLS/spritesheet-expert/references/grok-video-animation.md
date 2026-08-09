# Grok Image And Video Provider

Use `$grok-imagine` as an optional provider. `$imagegen` remains the default still-image path.

This file defines the Grok boundary. Read `video-animation-workflow.md` for frame selection, imported videos, background removal, cropping, registration, and QA.

## Consent And Execution Boundary

1. Prepare the job with `scripts/prepare_grok_video_animation.py`.
2. Read the generated prompt and `job.json`.
3. Run `$grok-imagine` in `video-from-image` mode with the job's exact dry-run arguments.
4. Review the dry-run manifest. A real provider call requires explicit current-task consent and `--ack-run`.
5. Accept only the copied video listed in a completed `invocation.json` whose exact media count is one.

Tests, smoke checks, and fixtures must never call inference. A provider timeout is not permission to retry: inspect the output directory, `invocation.json`, status, and copied `media/` first. Zero Data Retention teams may need a caller-owned `output.upload_url` for video generation.

## First Frame To Video

The first frame is an approved production image, not a layout guide or procedural placeholder. It must show the full subject at the intended scale on the same flat neutral gray, black, or white background declared by `sprite-request.json`. Locomotion must start from a visually approved grounded contact pose with one support foot and a readable trailing leg; an airborne split or ambiguous double-contact pose is a hard failure before video generation.

Prepare one state:

```bash
python scripts/prepare_grok_video_animation.py \
  --repo-root /abs/project \
  --run-dir /abs/project/.scratch/sprite-run \
  --state walk \
  --first-frame provider/grok-imagine/walk/first-frame.png
```

This writes:

```text
provider/grok-imagine/walk/prompt.txt
provider/grok-imagine/walk/job.json
```

The prompt is structured instead of one long prose sentence. It records a `prompt_contract` in `job.json` with anatomy, locomotion, workflow, allowed motion driver, motion plane, early action window, edge margin, and phase semantics. Front-FPS creature preparation fails closed when the camera or movement/attack source is missing.

The prompt keeps camera, projection, framing, ground line, subject scale, center, identity, lighting, neutral background, and existing empty border fixed. It requests one continuous 6-second action with no cuts, camera motion, text, extra objects, detached effects, motion blur, or cast shadow. `image-plane` is the default for frontal sprites: “toward the player” means pose readability, not depth travel, foreshortening, giant foreground limbs, or body enlargement. Do not force an output aspect ratio; image-to-video should inherit the first frame instead of stretching it.

The first line also instructs the worker to call `image_to_video` exactly once and stop after the requested video exists. The wrapper still rejects extra media. Do not request multiple takes in one call: use the full native-rate timeline as the candidate pool, then regenerate only when no reviewed frame set is usable.

Optional state controls live under `states.<state>.video_prompt`:

```json
{
  "provider_action": "one compact frontal crawl cycle driven by alternating diagonal supports",
  "motion_window_seconds": 1.6,
  "edge_margin_ratio": 0.15,
  "motion_plane": "image-plane"
}
```

Keep the full state `action` as the durable animation design contract. Use optional `provider_action` as its short generation instruction when the full design text is repetitive. It must retain the creature-specific motion or attack source; never replace it with “walk” or “attack” alone.

The first complete action must occur inside the early motion window. Later motion may repeat only that stable action. This yields several candidate frames without asking the provider to target a low output frame rate.

When only one state's generation wording failed, prepare that state again without editing the shared request:

```bash
python scripts/prepare_grok_video_animation.py \
  --repo-root /abs/project \
  --run-dir /abs/project/.scratch/sprite-run \
  --state walk \
  --first-frame provider/grok-imagine/walk/first-frame.png \
  --provider-action "one stricter anatomy-specific in-place cycle" \
  --force
```

The job records `prompt_contract.provider_action_source: cli-override`. This keeps accepted sibling-state request hashes valid. It is a prompt-only repair; it cannot change declared anatomy, motion source, camera, or QA policy.

Before a retry, review every frame from the current video. If no selection works, make one state-local repair that names the joints, support/contact relation, centerline limit, and anatomy that must stay fixed. After two failures from the same driver, switch to a safer existing driver instead of repeating the same deformation. Examples include changing a fragile hand attack to a lower-shroud lash, or changing an unclear whole-body crawl to explicit diagonal paw pairs. Archive the old state under `rejected/<reason>` and do not regenerate its accepted sibling.

For `gesture-loop`, prompt preparation adds a planted-body lock. Pelvis, legs,
knees, ankles, both feet, and the contact footprint remain pixel-for-pixel
fixed; only the waving shoulder, arm, wrist, and hand carry the gesture, with
minimal torso/head motion. Post-extraction QA still measures lower-body
silhouette and center-x travel. A clean loop closure does not waive movement in
the middle frames.

After `$grok-imagine` completes, ingest its exact invocation manifest:

```bash
python -m pip install -r scripts/requirements-video.txt
python scripts/ingest_grok_video_animation.py \
  --run-dir /abs/project/.scratch/sprite-run \
  --state walk \
  --invocation /abs/project/.scratch/agent-cli-delegation/grok-imagine/spritesheet-video/<run>/invocation.json
```

Ingestion fails before mutation unless all of these match:

- job, prompt, first-frame hash, state, frame count, and repo root;
- provider `grok-imagine`, mode `video-from-image`, completed status, and exit code zero;
- enforcement source list containing only the exact first frame;
- zero generated images and exactly one generated video;
- wrapper-owned `media/video-01.*` inside the job output directory;
- a decodable video with a stable size/fps and enough unique frames.

Ingestion enters the common video analyzer. It scans every decoded frame and creates several candidate sequences. Watch the entire video before selection; reject a bad state before Lucida. Then review every frame, compare several candidates, and inspect final active frames at full source size.

The command also builds the required minimal selector. Re-ingest reviewed indices with `--force`. This action does not call Grok again.

The selected frames keep the first-frame aspect ratio. An approved first frame replaces decoder frame 0 at exact pixels.

Outputs:

```text
raw/<state>.png
provider/grok-imagine/<state>/video-source.json
source-provenance.json
qa/<state>-video-frame-selector/index.html
qa/<state>-video-frame-selector/selector.evidence.json
```

The video source report records hash-bound copies of the sprite request, job,
prompt, first frame, provider invocation, provider result, and video, plus the
decoder/version, decoded dimensions/fps/count, selected indices and timestamps,
and raw-grid hash. `source-provenance.json` uses
`source_type: grok-imagine-video`; runs that combine providers use
`source_type: mixed` with per-source provider fields.

## Common Atlas And QA Path

Video ingestion does not approve animation or align frames. Continue with the common workflow in `video-animation-workflow.md`.

`gesture-loop` extraction preserves each provider frame's full canvas. It uses one shared canvas-to-cell transform.

```bash
python scripts/check_generation_provenance.py --run-dir /abs/project/.scratch/sprite-run
python scripts/extract_sprite_row_frames.py --run-dir /abs/project/.scratch/sprite-run
python scripts/compose_sprite_atlas.py --run-dir /abs/project/.scratch/sprite-run
python scripts/check_frame_alignment.py --run-dir /abs/project/.scratch/sprite-run
python scripts/check_identity_consistency.py --run-dir /abs/project/.scratch/sprite-run
python scripts/check_animation_contracts.py --run-dir /abs/project/.scratch/sprite-run
python scripts/preview_animation.py --run-dir /abs/project/.scratch/sprite-run
python scripts/render_runtime_preview.py --run-dir /abs/project/.scratch/sprite-run --state walk --kind runtime-playback
python scripts/build_preview_workbench.py --run-dir /abs/project/.scratch/sprite-run --force
python scripts/validate_run.py --run-dir /abs/project/.scratch/sprite-run --stage post-extract
```

Render runtime playback once per animated state. Build or rebuild the
workbench only after the final reports and runtime evidence exist so the
self-contained review page cannot capture a stale evidence set.

Review the workbench on checker, black, gray, and white. Reject identity morphing, limb invention/loss, background breathing, camera motion, root drift, scale drift, loop pops, matte fringe, or frames that only look plausible in isolation. Repair or regenerate the smallest failing state; do not hide video defects with registration.

## Optional Grok Still Images

For a Grok-generated first frame or row, use `$grok-imagine image-generate` or `image-edit` with the same flat neutral background contract. Start with dry-run and accept only copied media from a completed invocation manifest. Keep that provider manifest with the run evidence; source intake alone does not prove that inference occurred.

Copy the selected image into the run, create a `source-intake-v1` document, then ingest it:

```bash
python scripts/ingest_source.py \
  --run-dir /abs/project/.scratch/sprite-run \
  --intake /abs/project/.scratch/sprite-run/provider/grok-imagine/<state>/source-intake.json
```

The intake uses `source_type: grok-imagine-image`, `engine: grok-imagine`, `source_stage: provider-output`, `provider.name: grok-imagine`, `provider.status: succeeded`, and the exact candidate/request hashes. The command validates the selected bitmap, dimensions, request binding, state, license policy, and output containment before writing `raw/<state>.png`. Its verified provenance records `art_engine: grok-imagine`, per-source provider fields, and `qa/source-intake-report.json`. A real completion claim still requires the retained completed `$grok-imagine` invocation, acknowledged execution, copied provider media, and visual review.
