# Isometric Tileset Workflow

For isometric terrain, object/decor, building, or mixed environment atlases.

## Contract First

Declare the engine grid before generation:

```json
{
  "asset_kind": "tileset",
  "extraction_mode": "slots",
  "asset_catalog": {
    "projection": "2:1 isometric",
    "tile": {
      "width": 128,
      "height": 64,
      "runtimeCell": [224, 224]
    }
  }
}
```

- `tile.width` / `tile.height`: logical diamond footprint, normally 2:1.
- `runtimeCell`: rectangular atlas slot; may be taller than the diamond so sides, cliffs, props, and shadows can extend below/above the floor.
- `runtimeCell` must match `request.cell`. `prepare_sprite_run.py` blocks isometric generation when these disagree.
- Each slot needs a `pivot` at the floor/contact point. Do not use the image center unless it is also the runtime contact point.
- Rectangular slicing is allowed; rectangular placement is not. Runtime placement uses the pivot plus the 2:1 footprint.

## Required Catalog

Every slot needs reviewed metadata:

```json
"grass-flat": {
  "category": "terrain",
  "tile_role": "base",
  "collision": "walkable",
  "pivot": [112, 168]
}
```

Use specific runtime names, not `tile-1` or `row-0`.

Minimum terrain roles:

- `tile_role=base`: flat walkable floor.
- `edge_role=north/south/east/west`: visible ledge or transition sides.
- `edge_role=inner-corner/outer-corner`: corner closure.
- `tile_role=transition/detail/hazard/water/bridge`: optional overlays and gameplay surfaces.
- `collision`: `walkable`, `blocked`, `ledge`, `slow`, `damage`, or project vocabulary.

For props/decor, use `asset_kind: asset`, `collision`, `category`, and `pivot`. Cut props as isolated objects, not scene fragments.

## Generation Direction

Ask `$imagegen` for grouped rows, not a finished scene:

- one row for base ground variants;
- one row for edges/corners/height transitions;
- one row for hazards/overlays;
- one row for decor/props/building pieces.

Prompt constraints:

- transparent or simple matte background;
- no scene background, labels, shadows crossing slot borders, or overlapping slots;
- all tiles on the same 2:1 isometric grid;
- follow the generated layout guide's diamond and floor/contact pivot as placement guides only; never draw the guide marks into final art;
- consistent light direction and scale;
- diamond floor footprint visible or inferable;
- enough padding for tall/side geometry inside `runtimeCell`.

## Slicing Rules

Production slicing — one of:

- exact grid where source width/height divide by rows/columns with no remainder;
- trusted manifest rectangles;
- authored boxes from manual review.

Auto-detect is diagnostic only. If generated dimensions do not divide the grid, crop/resize/regenerate or author boxes before approval.

## QA Gates

Run:

```bash
python scripts/check_generation_provenance.py --run-dir /abs/run
python scripts/unpack_atlas_run.py --atlas /abs/source.png --grid 8x4 --asset-kind tileset --extraction-mode slots --asset-labels-file /abs/labels.json --asset-catalog-file /abs/catalog.json --out-dir /abs/run --force
python scripts/compose_sprite_atlas.py --run-dir /abs/run
python scripts/check_asset_slots.py --run-dir /abs/run
python scripts/check_isometric_tiles.py --run-dir /abs/run
```

Review:

- `qa/segmentation-overlay.png`: cuts match authored slots.
- `qa/asset-slot-overlay.png`: labels, bboxes, pivots, and clipping.
- `qa/tile-repeat-review.png`: repeated slots do not expose seams.
- `qa/isometric-pivot-overlay.png`: 2:1 footprint and pivot match the visual floor.
- `qa/isometric-map-review.png`: tiles compose into a coherent map.
- `qa/isometric-depth-review.png`: height/depth sorting reads correctly.
- `qa/isometric-runtime-metadata.json`: calibrated runtime footprint, pivots, and placement formula for prototypes/importers.
- `qa/isometric-calibrated-catalog.json`: human-review candidate catalog; copy approved footprint/pivots back into the source catalog before final packaging.

Hard failures:

- source dimensions do not divide the declared grid;
- missing or generic labels;
- missing catalog metadata;
- `runtimeCell` does not match the actual cut cell;
- footprint ratio is not 2:1 unless the request explicitly chooses another projection;
- pivots outside the cell or placed away from the floor/contact point;
- missing base/edge/corner roles for terrain;
- props touching/crossing slot borders;
- white/key/matte edge artifacts visible after background removal;
- prototype/runtime ignores calibrated metadata and positions cells by rectangular top-lefts, image centers, or stale requested footprint.

## Runtime Rules

Editor-style row/column model:

```text
center_x = origin_x + (col - row) * tile_width / 2
center_y = origin_y + (col + row) * tile_height / 2 - z_height
object_anchor_y = center_y + tile_height / 2
draw_x = center_x - pivot_x
draw_y = object_anchor_y - pivot_y
```

Floor-grid diamonds are centered at `center_x, center_y`. Sprites, props, and extruded terrain chunks are anchored at the diamond's bottom/contact point (`center_y + tile_height / 2`). Do not place a rectangular sprite cell by top-left or image center.

Draw in stable depth order:

```text
depth = row + col + z_offset
tie_breakers = base row/col depth, then creation/source order
```

Tall props and characters share the same ground-contact sorting rule. Prototype placement by top-left cell coordinates invalidates isometric review.

When importing generated art, calibrate the real grid from extracted frames first. If the catalog says `128x64` but alpha bboxes show ~`206x104`, renderer and QA must use the calibrated footprint and block the stale catalog.

`check_isometric_tiles.py` writes two handoff artifacts:

- `qa/isometric-runtime-metadata.json`: runtime SSoT for prototype placement.
- `qa/isometric-calibrated-catalog.json`: editable candidate catalog for manual approval.

Use runtime metadata in preview/prototype code immediately. For final atlas packaging, review the calibrated catalog visually, copy approved values into the source catalog, rerun unpack/compose/check, and require the isometric gate to pass. Do not silently accept inferred values as final authoring metadata.

## Manual Review

Required for every isometric tileset:

- check slot label against visual content;
- check pivot against the floor/contact point;
- check edge/corner compatibility in a small map;
- check collision role against visual affordance;
- check props do not carry background fragments or clipped silhouettes;
- check lighting and scale match across terrain, props, and characters.
