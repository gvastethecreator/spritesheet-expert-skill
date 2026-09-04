# Spritesheet Expert Studio architecture

## Decision

Spritesheet Expert evolves from a collection of callable skills and deterministic scripts into a portable, local-first production studio. The skill remains the source of production policy. The Studio is a client of that policy, not a second implementation of it.

The product has four cooperating layers:

1. **Skill layer** — routing, generation constraints, provenance rules, workflow selection, and completion contracts.
2. **Deterministic core** — extraction, alpha analysis, registration, packing, hashing, manifests, review application, and QA.
3. **Studio layer** — workflow forms, prompt composition, visual review, corrections, and artifact export.
4. **Agent handoff layer** — explicit jobs sent to an external image provider, local model worker, CLI agent, or human operator.

Provider inference never runs implicitly while a user is editing a manifest. Every paid or remote action is represented by a reviewable handoff job first.

## Product principles

### Agent-first, not agent-only

Every workflow must be callable as structured data without the graphical interface. The Studio renders and edits the same contracts that an agent consumes. A user can therefore:

- prepare a job in the Studio and execute it with an agent;
- ask an agent to prepare a run and inspect it in the Studio;
- export a prompt without granting provider access;
- perform all deterministic work offline;
- preserve review decisions as files committed beside the assets.

### Immutable runs

A completed or reviewed run is never edited destructively. Applying a classification result, replacement, or review creates a successor run with a `parent_manifest_sha256`. This keeps provenance and approval evidence valid.

### One source of geometric truth

The runtime manifest distinguishes:

- the source bounding box;
- the extracted crop dimensions;
- the reserved atlas cell;
- the visible frame inside that cell;
- the pivot and optional baseline;
- sampling and extrusion policy.

A visual label is never baked into the runtime atlas. Human-readable labels are rendered only in review artifacts.

### Deterministic before generative

Transparent item sheets are segmented from alpha whenever possible. Local or remote segmentation models are fallback workers for opaque backgrounds, touching objects, ambiguous fragments, or manual prompts. Classification is an optional semantic step after deterministic extraction.

## Main workspaces

### Workflow Launcher

A registry-driven prompt and job editor. Each workflow declares:

- identifier and version;
- owning skill;
- input schema;
- output contract;
- prompt template;
- CLI template;
- required evidence;
- provider boundary;
- destructive or paid-action flags.

The launcher can render a prompt, CLI command, or JSON job. Copying a prompt does not mark a job as executed.

### Asset Library

A run-scoped browser for source sheets, extracted sprites, masks, atlases, manifests, reports, and replacements. Assets use stable content-derived IDs rather than atlas coordinates.

### Atlas Lab

The visual workspace for irregular item sheets. It supports:

- source and alpha inspection;
- component overlays;
- merge and split review;
- item classification and tags;
- rectangular multi-size cell preview;
- padding, grid quantum, and width experiments;
- pivot and baseline inspection;
- deterministic rebuilds.

### Animation Lab

Extends the existing preview workbench with frame curation, chronological playback, onion skin, registration, replacement, and provider handoffs.

### Tile Lab

Reviews projection, adjacency, map repetition, pivots, edge/corner coverage, and depth sorting for top-down and isometric tilesets.

### Delivery Inspector

Reconciles all required evidence before export: provenance, hashes, review records, QA gates, atlas manifests, licenses, and target-engine metadata.

## Handoff contract

A provider job is a portable JSON document. It includes exact inputs and never relies on browser-only state.

```json
{
  "schemaVersion": "studio-handoff-v1",
  "jobId": "job_01J...",
  "workflowId": "regenerate-single-item",
  "ownerSkill": "spritesheet-expert",
  "inputManifest": "manifest.json",
  "targetItemId": "item_45d2f31b73ce",
  "prompt": "Generate one isolated rusted metal oil can...",
  "expected": {
    "count": 1,
    "background": "transparent",
    "kind": "image"
  },
  "forbidden": [
    "collage",
    "contact sheet",
    "multiple object categories",
    "reuse of a failed multi-object image"
  ],
  "status": "prepared"
}
```

Returned media enters the pipeline only through source intake, hash pinning, provenance declaration, and visual review.

## Deterministic Item Atlas

The item-sheet compiler performs:

1. alpha inspection;
2. strong-component detection;
3. bounded weak-alpha recovery;
4. connected-component filtering;
5. exact RGBA extraction;
6. stable ID generation;
7. QA flagging;
8. optional classification handoff;
9. rectangular cell sizing;
10. deterministic packing;
11. runtime manifest and review artifact generation.

For a sprite of width `w`, height `h`, padding `p`, and grid quantum `q`:

```text
cellColumns = ceil((w + 2p) / q)
cellRows    = ceil((h + 2p) / q)
cellWidth   = cellColumns * q
cellHeight  = cellRows * q
```

The sprite remains at scale `1`. Rotation is disabled. The atlas may grow, but source pixels do not.

## Classification architecture

Classification is model-neutral and runs per extracted item, never on the whole sheet. The core produces light and dark RGB composites plus the original RGBA crop. A worker returns candidates against a closed taxonomy.

Recommended worker lanes:

- embedding retrieval for broad candidate selection;
- VLM verification over the top candidates;
- explicit `unknown` below confidence thresholds;
- human review for ambiguous or novel categories.

The deterministic core validates and applies results. It does not import model libraries unless that optional worker is selected.

## Review model

Each item has a review state:

- `pending`;
- `approved`;
- `rejected`;
- `replace`;
- `regenerate`.

A review record may also override taxonomy, tags, pivot, baseline, merge group, or replacement source. Changing source bytes invalidates prior item approval.

## Storage layout

```text
workspace/
├── project.json
├── workflows/
├── runs/
│   └── <run-id>/
│       ├── source/
│       ├── items/
│       ├── masks/
│       ├── inference/
│       ├── atlas/
│       ├── review/
│       ├── qa/
│       └── manifest.json
├── taxonomy/
├── handoffs/
└── exports/
```

## Staged roadmap

### Stage 1 — portable vertical slice

- static Studio bundle;
- workflow registry and prompt composer;
- deterministic alpha item segmentation;
- rectangular multi-size packing;
- item review export;
- immutable replacement application;
- schemas and golden fixtures.

### Stage 2 — editing and local workers

- mask brush, lasso, merge, and split;
- classification worker registry;
- Qwen/embedding local worker;
- SAM-compatible fallback worker;
- duplicate detection;
- batch review shortcuts;
- resumable job queue.

### Stage 3 — production shell

- Tauri packaging;
- filesystem permissions and workspace migration;
- provider adapters with dry-run and spend confirmation;
- GPU/model diagnostics;
- crash recovery and structured logs;
- Phaser, Godot, Unity, and generic atlas exporters.

### Stage 4 — collaborative production

- review receipts and signatures;
- remote artifact stores;
- shared taxonomy packages;
- role-based approval;
- evaluation datasets built from accepted corrections;
- reproducible release receipts.

## Acceptance criteria

The architecture is working when:

- every Studio action can be represented as a portable contract;
- provider execution is explicit and reviewable;
- deterministic outputs are reproducible from pinned inputs;
- replacing one item does not regenerate unrelated items;
- source scale and orientation are preserved;
- review evidence is invalidated after relevant input changes;
- a run can be opened without network access;
- the skill, CLI, and Studio agree on ownership and completion rules.
