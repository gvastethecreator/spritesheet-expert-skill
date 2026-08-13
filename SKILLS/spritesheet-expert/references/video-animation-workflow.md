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

The selector also writes paginated `timeline-page-*.png` evidence for every decoded frame. Re-selection therefore preserves exhaustive review evidence without a project-specific helper.

Process one creature state at a time. A batch manifest tracks work; it does not approve work.

## Early Rejection Gate

Watch the complete decoded video once before detailed frame selection. Reject the state before background removal when any hard failure appears:

- wrong creature type or motion family;
- three-quarter, side, top-down, or tilted projection when frontal is required;
- camera movement, approach, zoom, scale drift, ground-line drift, or background breathing;
- identity, face, limb count, weapon, wing, tail, or body-volume changes;
- generic mirrored biped motion applied to another anatomy;
- attack driven by the wrong body part;
- any source-edge contact or cropped anatomy.

Only viable videos enter detailed frame review. This is the main production-speed gate.

A late failure does not invalidate an already complete clean early cycle. Salvage the video only when all semantic phases exist before the first defective frame, every selected frame preserves identity and scale, and exact-idle recovery comes from the approved anchor. Record the first unsafe frame and keep every selected index before it. If the defect begins before a complete cycle, reject the state.

## Provider Prompt Contract

Generate source video for frame selection, not for cinematic presentation. The provider prompt must include:

- exact creature anatomy and only the declared movement or attack driver;
- clean articulated pose changes with constant segment lengths, limb thickness, topology, and body volume;
- stationary image-plane root, subject center, scale, camera, ground line, and background;
- stable non-driver anatomy with only connected secondary motion;
- one compact early action followed by repeat or idle hold;
- sharp readable pose plateaus rather than blur, twitching, or deformed in-betweens;
- enough source-edge clearance for every extreme pose.

Keep `provider_action` short, positive, and anatomy-specific. Describe what moves and what makes phase A different from phase B, or what makes anticipation different from contact. Global locks against morphing, mirror substitution, squash/stretch, approach, scaling, and camera movement belong to the structured prompt builder so they remain consistent across every creature.

Ask for one video per state and one provider call per job. Do not spend a generation on four low-rate output frames. Generate a native-rate action, scan the complete timeline, compare several candidate sets, and extract the four semantic poses after review.

Before preparing a quota-sealed batch, inspect every approved anchor individually. Base the prompt contract on visible anatomy rather than the inherited enemy label. Record exact support count, motion-driver count, wing or tentacle groups, mouth and weapon placement, and identity-critical face geometry. For uncanny or human-faced creatures, explicitly freeze that exact face during locomotion and name whether the mouth participates in attack. Generate exactly two videos per identity: one locomotion state and one attack state. Audit every dry-run, execute each once, then freeze video generation for that identity.

If a one-video provider job accidentally creates multiple videos in the same completed invocation, keep only the first discovered video, write the discarded overflow paths and recovery reason into the invocation provenance, and continue without another provider call. Do not silently accept overflow and do not retry it. Stop for diagnosis on any failure that is not this verified overproduction case.

Use a bounded repair ladder when the result fails:

1. Search the existing timeline for a safer pose set.
2. Tighten only the failed state's action with explicit joints, support/contact, centerline, and fixed-anatomy rules.
3. Regenerate only that state.
4. After two failures from the same motion driver, use another existing anatomy-safe driver instead of repeating the same failure.

If the batch is quota-sealed, step 3 is disabled. Exhaust the complete existing timeline, including early clean cycles and alternate chronological candidates. If exactly one semantic pose remains unusable, repair only that pose with `$imagegen` from the approved anchor and adjacent accepted poses. Do not regenerate the whole video or fabricate the frame procedurally. Record the repaired frame as mixed provenance, then rerun background removal, adaptive crop, registration, contact, onion, matte, white-background, and runtime checks for the state.

After the repaired sheet replaces `raw/<state>.png`, synchronize its exact bytes with provenance:

```bash
python scripts/sync_imagegen_repair_provenance.py --run-dir /abs/run
```

The command reads `qa/quota-sealed-repair-plan.json`. It accepts only completed repair states. It changes those accepted sources to `imagegen`, updates their hashes and sizes, and keeps the other video states unchanged. A run that contains both source types becomes `mixed`. Run the provenance gate again after this command.

Archive each rejected state and preserve accepted sibling-state sources, selected frames, matte panels, and provenance.

## Batch Completion And Quota Accounting

A passing run does not prove a passing batch. Keep these records separate:

1. **Quota source:** the one provider video allocated to each required state. It remains quota evidence even when Imagegen later replaces one bad pose or state sheet.
2. **Accepted source:** the exact raw sheet used by extraction and packaging. It can be Grok video, imported video, Imagegen, or mixed provenance.
3. **Archived source:** an old, rejected, overflow, or alternate `video-source.json`. It is retained for diagnosis and never increases the quota count.

Do not count every recursive `video-source.json`. Prefer the canonical state report at `provider/grok-imagine/<state>/video-source.json`, then `provider/video/<state>/video-source.json`. If both are historical or the active quota record lives elsewhere, pin the intended report in the batch entry:

```json
{
  "review": {
    "quota_sources": {
      "idle-step": "provider/video/idle-step/video-source.json",
      "attack": "provider/grok-imagine/attack/video-source.json"
    }
  }
}
```

The batch manifest also pins the approved identity source hash, reviewed state sources, validation fingerprint, and packaged candidate hash. Declare reusable policy at the top level:

```json
{
  "generation_policy": {
    "quota_sealed": true,
    "identity_fields": ["biome", "enemy"],
    "states_per_identity": ["idle-step", "attack"],
    "expected_identities": 110,
    "max_provider_videos_per_identity": 2
  }
}
```

After all runs are reviewed, validated, and packaged, audit the complete set:

```bash
python scripts/check_animation_batch_completion.py \
  --repo-root /abs/project \
  --batch-manifest /abs/project/path/to/batch-manifest.json
```

The command writes `batch-completion-report.json` beside the manifest by default. It verifies unique identities, exact identity-source bytes, reviewed states, requested and extracted frame counts, source provenance, quota video bytes, selector/editor and timeline hashes, completed Imagegen repair plans, final workbench evidence, pre-package validation, source atlas, and packaged candidate. It reports archived provider records without counting them as active work. Any changed byte, stale selector, missing evidence, unplanned repair, duplicate identity, missing state, or quota mismatch fails the batch.

For creatures with oversized hands, very long forearms, tendrils, or other long levers, inspect non-driver anatomy first: providers often preserve the torso while stretching those distal parts late in the shot. Prefer a short clean early window. If hand- or body-mass attacks fail twice, switch to a compact existing driver such as jaw, head, lower shroud, or tail instead of asking the same long limbs to move again.

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

The editor contains the complete video, one thumbnail for each decoded frame, candidate presets, semantic frame slots, a loop preview, the declared creature type/motion source, and five review checks. Frames whose foreground reaches the decoded source boundary are marked `BORDE`. Locomotion frames whose subject height leaves `0.78x..1.22x` of the anchor are marked `ESCALA`. Either condition blocks export for an active selected slot. Safe, scale-stable cycles rank above clipped or zoomed poses even when the invalid pose has more motion.

Review every decoded frame, not only the top-ranked candidate. Compare several candidate sets. Open the final active frames at full decoded resolution when thumbnails hide face, limb, weapon, crop, or perspective errors.

For compact frontal creature cycles, use these semantic slots:

- Movement: exact idle, anatomy-specific phase A, exact idle, complementary phase B.
- Attack: exact idle, compact anticipation, clear contact, exact idle recovery.

Changing a frame or candidate invalidates the checklist. Confirm it again for the new exact selection.

Select any chronological frame set. Then copy the re-ingestion command or download the selection JSON.

The reviewed indices must be strictly increasing. Exact-idle slot replacement happens after selection, so still choose a chronological placeholder for that slot. Run and confirm re-ingestion before starting Lucida; if ingestion rejects the indices, extraction would only recompute the previous raw sheet.

### Prompting rigid and bilateral motion

Split difficult anatomy into one animated driver region and one explicitly pixel-locked region. Use visible boundaries and quantities: `bottom 15 percent of the puddle`, `legs below fixed hips`, `existing horizontal jaw opens 18 pixels`, or `wings only around a fixed body`. Lock total height, center, ground line, silhouette width, and identity landmarks independently.

For paired-limb attacks, name both original limbs, their permitted joints, maximum height, motion plane, same-size rule, anticipation pose, shared contact pose, and exact recovery. Avoid depth verbs unless perspective growth is intentionally part of the art. `Inward and downward across the torso plane` is safer for a frontal sprite than `toward the player`.

Tall faceless bipeds with declared long-arm counter-swing are a special identity-proxy case: shoulder and hand motion can cross the narrow top bands and look like head-width growth numerically. For this anatomy, rely on body-mass, opaque-area, baseline, scale, contact/onion evidence, and explicit visual confirmation of the actual head and eyes.

Do not widen global identity thresholds to silence pose-driven proxy failures. After reviewing the exact affected contact sheet, onion skin, matte, final sheet, and runtime playback, record a confirmed false positive with:

```bash
python scripts/record_identity_proxy_review.py --run-dir /abs/run --reason "The declared appendage crosses the narrow proxy band while the reviewed head, torso, scale, and root stay exact."
python scripts/check_identity_consistency.py --run-dir /abs/run
```

The review covers the current exact error strings and hashes its request, extracted manifest, sheet, matte, contact, and onion evidence. It fails closed if any covered error or artifact changes. A proxy review is not an anatomy waiver and cannot replace an uncertain or failed visual inspection.

Explicit workflow ids also win over action prose during QA routing. `front-fps-creature-attack` is never sent through the locomotion variation gate merely because its action mentions retreat or recovery. Legacy rows without `animation_workflows` still use state/action word matching.

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

Re-ingestion records `reviewed_indices` and `reviewed_selection` metrics for the exact chosen frames. For locomotion, it fails before background removal when an active pose changes subject height outside `0.78x..1.22x` of the exact first frame. Treat this as a fast camera/scale/morph rejection gate, then correct the selection or regenerate only that state.

## Remove The Background

Run `extract_sprite_row_frames.py` after frame selection.

Video-derived grids use independent-frame removal. Lucida processes each selected frame separately.

Start Lucida at `384` input pixels for a clean, high-contrast neutral sheet. Review the matte before another run. Increase to `512`, then `1024`, only when the smaller input loses fur, translucent edges, thin appendages, or glow. Process one Lucida extractor at a time. Do not reduce the request default or batch-approve the faster matte without visual review.

The extractor adds a neutral context border before model inference. Then it removes small disconnected matte noise.

The extractor calculates one alpha box for each frame. It adds transparent crop padding around that box.

Each extraction refresh writes `qa/<state>-background-matte-review.png`. The aggregate `qa/background-matte-review.png` is rebuilt from all durable state panels, so an attack-only repair cannot erase the accepted locomotion matte evidence.

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

`render_runtime_preview.py` uses an automatic viewport by default. The viewport fits the largest manifest frame at the requested scale. Use `--viewport WIDTHxHEIGHT` only when the project requires a larger fixed capture surface.

Use `register_sprite_frames.py` only for an imported or legacy run that cannot declare registration before extraction. Do not register an already registered output a second time.

Remove `--allow-imported-source` for a verified provider source such as Grok.

Review each output individually: matte, adaptive crop boxes, contact sheet, candidate loop, onion skin, runtime playback, identity, creature type, and motion contract. The user gives final visual approval.
