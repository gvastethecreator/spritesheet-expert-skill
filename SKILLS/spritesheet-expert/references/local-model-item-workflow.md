# Local item-sheet workflow

Use this workflow for an existing transparent sheet of characters, buildings,
heraldry, or objects. A visual group includes its accessories and detached
effects. Qwen proposes groups. SAM2 proposes masks. The compiler copies exact
source pixels into size-ordered rectangular cells.

Qwen receives a thumbnail of the sheet and a close view of one alpha region
with nearby context. These regions are not reference object counts: the model
may split a joined component or include detached parts. Repeated proposals
with strong mask agreement are merged but flagged for review. Queries and
validated Qwen results are saved separately so a retry can reuse completed work.
Model text is constrained with [LM Format Enforcer](https://github.com/noamgat/lm-format-enforcer):
a compact numeric-box grammar for segmentation and a taxonomy schema for
classification. This limits malformed responses, not semantic mistakes. The
compiler still validates every result, hash and mask before accepting pixels.

## Install and run

Run commands from this skill directory. Python 3.12 is managed by uv.

```powershell
python scripts/setup_item_model_runtime.py --profile nvidia
.local/item-model-runtime/Scripts/python.exe scripts/prepare_item_models.py --cache-dir .local/model-cache --profile standard
.local/item-model-runtime/Scripts/python.exe scripts/serve_item_studio.py
```

For CPU hosts, install the `cpu` runtime profile. On Linux, use
`.local/item-model-runtime/bin/python`. The `light` checkpoint profile uses
Qwen3-VL-2B-Instruct; `standard` uses Qwen3-VL-4B-Instruct. Both include
SAM2.1 Hiera Small. Download each selected profile explicitly. Inference then
uses the recorded checkpoint revisions and the local cache without network access.

The installer uses `model-runtime/uv.lock`. It does not download model weights.
The checkpoint command records model IDs, immutable revisions, and relative
snapshot paths. Cache and runtime directories are configurable. After moving
the skill, rerun setup with the retained cache directory to rebuild the environment.

The same workflow is available without a browser:

```powershell
.local/item-model-runtime/Scripts/python.exe scripts/run_item_atlas_workflow.py source.png --output-dir build/sheet --models standard
```

`--models none` performs alpha extraction and packing without classification.
`--grid-quantum 32` and `--padding 16` set the cell dimensions and transparent
margin per side. `--max-width 0` selects automatic width. Sprites are never
rotated or scaled. Cells follow descending area, maximum side, height, and ID.
Rows preserve this order instead of filling earlier gaps with small sprites.

## Review and ownership

Studio imports the source bytes into its workspace. Processing uses one worker
at a time. Saved runs expose progress, logs, cancel, and resume operations.
The source remains immutable. Edits create successor manifests.

Review only the flagged items by default. Disable the filter to inspect every
sprite. Select several items to merge their source masks. Use the source brush
to assign pixels to the selected sprite, a new sprite, the pending set, or an
explicit discard. Accept an item after inspecting its borders. Tags are keyed
by stable item IDs and shown outside the sprite preview.
When a mask changes, inherited labels retain their parent item/hash and require
review. Merging masks is not approval: inspect the merged crop and its labels,
then accept it explicitly.

The source mask overlay shows the selected sprite in green. With no selection,
it shows pending pixels in magenta. Light and dark backgrounds reveal edge
problems. Zoom uses nearest-neighbor display. Brush coordinates remain in the
original source space.

Every visible source pixel is owned, pending, or explicitly discarded. Model
mask conflicts remain pending. Small alpha fragments are not deleted as noise.
Component agreement can restore exact alpha edges around a model mask. Touching
components that span several proposals remain flagged for review.
If Qwen proposes one intact source group and its mask overlaps that target,
the compiler preserves the full alpha group, including thin edges and props.
It flags this decision for review instead of allowing SAM to erase those parts.

Model confidence is not calibrated accuracy. Invalid JSON, hashes, or mask
dimensions stop processing. A reported count that differs from the returned
instance array is preserved as a warning; the actual array defines the count.
Semantic errors and source occlusions require review. The workflow does not
reconstruct hidden pixels or generate replacement art.

## Files and state

- `workflow.json`: inputs, checkpoint revisions, compiler fingerprint, stage
  status, elapsed time, output hashes, and current manifest.
- `input/source.png`: exact imported file bytes.
- `alpha/`: initial candidates, source reference, atlas, and pending mask.
- `segmentation/`: region jobs, raw Qwen output, per-job checkpoints, results,
  and full-source SAM2 masks.
- `segmented/`: source-preserving groups, native-size crops, classification,
  ordered atlas, and ownership report.
- `reviews/`: immutable successors with portable source-coordinate operations.

The ownership report checks RGBA equality, duplicate ownership, pending pixels,
and explicit discards. It proves accounting, not semantic correctness. Inspect
the source, masks, and crops before marking ambiguous items accepted.

Resume reuses completed stages only when recorded input and output hashes
match. Changed source, parameters, taxonomy, checkpoints, or compiler require a
new output directory. Interrupted model stages may need to run again.

Processing completion and review completion are separate. Export a delivery
only after pending pixels and review flags are resolved. Draft export is
explicit and records `draft: true`. The archive contains native crops, the clean
atlas, the current manifest, and evidence. It does not include model weights.

The local server binds to loopback. Mutation routes require a session token
and the local origin. Routes accept typed operations, never shell commands.
All outputs remain inside the selected workspace. The CLI remains the owner
of processing behavior.

## Verification

Use the existing unit and integration suites for masks, packing, lineage,
resume, cancellation, and relocation. Model inference is an explicit manual
integration check; ordinary tests never download or execute checkpoints.
Verify real sheets visually and record actual model time and peak CUDA memory.
Keep supplied production sheets and downloaded weights out of the published skill.
