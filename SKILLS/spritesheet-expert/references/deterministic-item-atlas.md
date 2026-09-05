# Deterministic Item Atlas

Use this workflow for a source image that contains many isolated props or items with irregular dimensions and spacing. It is especially useful for generated RGBA sheets that are visually organized but do not follow a reliable fixed grid.

The workflow separates semantic image creation from deterministic processing:

```text
existing/generated source sheet
-> alpha inspection
-> instance segmentation
-> exact RGBA crops
-> optional item classification
-> human review and replacements
-> rectangular multi-size packing
-> runtime atlas + manifest + QA evidence
```

## Non-negotiable invariants

- Preserve every accepted sprite at native pixel dimensions.
- Record `scale: 1` for compiled items.
- Disable rotation.
- Keep visual labels outside the runtime atlas.
- Reserve explicit transparent negative space around each sprite.
- Distinguish the reserved `cellRect` from the visible `frame`.
- Use stable item IDs that do not depend on final atlas coordinates.
- Do not mutate an approved parent run; create an immutable successor.
- Classification may name an item but may not change its geometry.
- A replacement changes only its target item and invalidates that item's prior approval.

## Alpha-first segmentation

Transparent sheets should not begin with a general vision model. The alpha channel already encodes the strongest separation signal.

The compiler uses hysteresis:

```text
alpha_high -> strong seeds and connected components
alpha_low  -> recover nearby antialiasing and weak alpha
halo       -> maximum growth distance from a strong seed
```

Default values:

```text
alpha_high = 64
alpha_low = 2
halo_radius = 6
connectivity = 8
```

Strong components below `min_strong_pixels` remain pending rather than becoming automatic candidates. Remaining strong components grow through weak-alpha pixels only within the configured halo. Competing growth fronts keep a deterministic tie break and produce a review flag. Every unassigned visible pixel remains in the pending mask; nothing is silently discarded.

This prevents a faint alpha bridge from joining unrelated objects across the sheet while retaining thin semitransparent edges near the accepted object.

### When alpha-first is insufficient

Escalate to a model-backed or manual segmentation lane only when one of these conditions is present:

- the source has no useful alpha;
- two intended items physically overlap;
- one intended item contains disconnected pieces beyond the halo;
- a background-removal model merged or damaged silhouettes;
- the source requires semantic prompts to distinguish instances.

The fallback model returns masks or component corrections. The deterministic compiler still owns crop geometry, IDs, packing, metadata, and evidence.

## Extraction outputs

For every item, preserve:

- stable ID;
- content SHA-256;
- source bounding box;
- strong, weak, and assigned pixel counts;
- exact RGBA crop;
- light RGB classification composite;
- dark RGB classification composite;
- native width and height;
- automatic QA flags.

The light and dark composites exist only for classification workers that do not preserve alpha. They never replace the original crop.

## Stable identifiers

The base ID is derived from native crop dimensions and RGBA bytes:

```text
item_<first 12 hex characters of content SHA-256>
```

Identical duplicate content receives a deterministic occurrence suffix. Atlas coordinates are not part of the ID, so repacking does not break semantic references.

## Rectangular multi-size cells

Let:

- `w`, `h` be native crop dimensions;
- `p` be requested transparent padding on every side;
- `q` be the grid quantum.

The reserved cell is:

```text
cellColumns = ceil((w + 2p) / q)
cellRows    = ceil((h + 2p) / q)
cellWidth   = cellColumns * q
cellHeight  = cellRows * q
```

The native image is centered inside this cell. For example:

```text
sprite: 95 x 126
padding: 16
quantum: 32
cell: 128 x 160
```

Manifest geometry:

```json
{
  "originalSize": [95, 126],
  "cellRect": [320, 128, 128, 160],
  "frame": [336, 145, 95, 126],
  "pivot": [0.5, 0.5],
  "scale": 1,
  "rotated": false
}
```

`cellRect` owns reserved grid space. `frame` owns visible pixels consumed by the runtime.

## Deterministic packing

Items are ordered by:

1. cell area descending;
2. largest side descending;
3. cell height descending;
4. stable item ID.

The packer places consecutive shelves in that visual order, without backfilling earlier gaps. Automatic width (`max_width=0`) is quantum-aligned and derived from total cell area and the widest cell. An explicit width bounds the rows. Height grows as needed. Rotation remains disabled.

## CLI

```powershell
python SKILLS/spritesheet-expert/scripts/build_deterministic_item_atlas.py `
  source/items.png `
  --output-dir build/item-atlas `
  --provenance imported `
  --alpha-high 64 `
  --alpha-low 2 `
  --halo-radius 6 `
  --grid-quantum 32 `
  --padding 16 `
  --max-width 4096
```

Set `--provenance` to the actual source route. The accepted values are `imagegen`, `grok-imagine-image`, `imported`, `fixture`, and `mixed`.

Outputs:

```text
build/item-atlas/
├── atlas.png
├── manifest.json
├── items/
│   └── item_*.png
├── inference/
│   ├── item_*-light.png
│   └── item_*-dark.png
└── qa/
    ├── source-components.png
    └── atlas-grid.png
```

## Classification workflow

Prepare jobs:

```powershell
python SKILLS/spritesheet-expert/scripts/prepare_item_classification.py `
  --manifest build/item-atlas/manifest.json `
  --taxonomy SKILLS/spritesheet-expert/references/taxonomies/generic-props-v1.json `
  --out build/item-atlas/inference/jobs.jsonl
```

Each job describes exactly one item. A worker must choose values from the closed taxonomy or return `unknown`.

Apply results:

```powershell
python SKILLS/spritesheet-expert/scripts/apply_item_classification.py `
  --manifest build/item-atlas/manifest.json `
  --results build/item-atlas/inference/results.jsonl `
  --taxonomy SKILLS/spritesheet-expert/references/taxonomies/generic-props-v1.json `
  --minimum-confidence 0.60 `
  --out build/item-atlas/manifest.classified.json
```

Low-confidence predictions are converted to `unknown` and receive `low_classification_confidence`. Values outside the taxonomy fail closed.

Write the classified manifest beside its parent. This location keeps all relative item and evidence paths valid.

## Review workflow

Review states:

- `pending`
- `approved`
- `rejected`
- `replace`
- `regenerate`

A review may also override family, canonical type, tags, notes, and a replacement record.

Apply a completed review:

```powershell
python SKILLS/spritesheet-expert/scripts/apply_item_review.py `
  --manifest build/item-atlas/manifest.json `
  --review review-workspace/item-review.json `
  --output-dir build/item-atlas-reviewed
```

The command requires the exact parent-manifest hash from `sourceManifest.sha256`. It rejects stale reviews and unresolved regeneration requests.

The successor includes current item composites, source-component evidence, reviewed replacement sources, rebuilt atlas evidence, and `parentManifestSha256`.

## Regeneration isolation

A replacement handoff must:

- target one item ID;
- request exactly one isolated image;
- mention only that item's semantic category;
- prohibit grids, collages, contact sheets, concept sheets, multiple panels, and alternate object categories;
- avoid a failed multi-object image as an image-to-image reference;
- preserve the accepted art direction, camera, and apparent visual scale;
- return through source intake and review before application.

A failed replacement does not advance a batch counter and does not regenerate unrelated items.

## QA flags

| Flag | Meaning |
| --- | --- |
| `touching_source_edge` | The accepted component reaches a source boundary. Pixels may be clipped. |
| `small_instance_review` | Strong seed is unusually small and may be noise or a fragment. |
| `high_weak_alpha_ratio` | A large percentage of assigned pixels came from weak alpha. |
| `sparse_shape_review` | The bounding box is mostly empty and may contain a long fragment or accidental grouping. |
| `neighbor_alpha_conflict` | Two growth fronts competed for weak-alpha pixels. |
| `low_classification_confidence` | Prediction fell below the configured confidence threshold. |
| `replacement_imported` | Final item bytes came from a reviewed replacement. |

Flags are evidence requests, not silent repair instructions.

## Completion

The deterministic item-atlas workflow is complete when:

- source provenance and SHA-256 are recorded;
- every retained item has a stable ID and exact crop;
- source overlay has been inspected;
- atlas cell and frame geometry validate without overlap;
- no item is rescaled or rotated;
- classification status is explicit;
- review status is explicit;
- unresolved replacements or regenerations are absent;
- atlas, manifest, item crops, and QA evidence match current hashes.
