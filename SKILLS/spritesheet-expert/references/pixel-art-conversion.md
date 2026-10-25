# Optional conversion of existing art to pixel art

Use this route only when the user explicitly asks to convert existing imagery to pixel art, or asks about that conversion and wants an alternative. A request for retro styling, sprite extraction, packing, registration or animation alone does not activate conversion. Preserve existing workflow defaults.

This is a project-owned Pillow implementation. It does not import or execute Pixel Asset Converter, use model weights, or call a provider. It is a lossy import operation on known cells, not new artwork generation. Imported provenance remains imported.

## Input contract

Use one still sheet with an exact grid and one state, in row-major chronological order for animation. Separate irregular items through their existing workflow first. Split multiple states before conversion. The source dimensions must divide exactly by the grid, and the target cell must have the same aspect ratio. No per-frame crop, centering, foot alignment, alpha threshold, dithering or component deletion occurs.

Every cell receives the same nearest-neighbor scale. RGB colors are reduced using a shared palette learned from sampled visible pixels across the whole sheet; transparent pixels do not bias it. The sampled alpha channel is retained exactly, including partial alpha and empty frames. Reduction can still miss a small feature: preservation of sampled alpha is not preservation of every source detail. Review at native size.

Example request for one temporal row:

```json
{
  "operation": "convert-to-pixel-art",
  "source": "input.png",
  "grid": [4, 1],
  "cell": [64, 64],
  "palette_size": 24,
  "semantics": "animation",
  "state": "jump",
  "fps": 8,
  "loop": true,
  "pivot": [96, 168]
}
```

Here each source cell is 192x192, so the common scale is 1/3. The pivot becomes `[32, 56]`. Pivots use continuous cell-edge coordinates; they are not rounded or inferred from a visible bounding box. Temporal input requires an explicit pivot, integer FPS and loop policy. Unequal per-frame durations are not supported in this first route; do not replace them with an invented FPS. `effects` is temporal too. For `variants` or `still-assets`, omit FPS and loop. A pivot is optional for static cells.

## Invoke and inspect

```bash
python <skill-dir>/scripts/convert_pixel_art.py convert --request conversion-request.json --output work/pixel-conversion
python <skill-dir>/scripts/convert_pixel_art.py validate work/pixel-conversion
```

The output must be new. It contains an exact source snapshot, portable request, converted sheet, separate frames, nearest-neighbor reference, conversion metadata and standalone `index.html`. The viewer shows native and 4x views, plus playback at the declared FPS for temporal input. It starts paused and never treats a variant list as an animation.

Validation recomputes palette, frames, layout and preview from the copied source and settings. It detects missing/extra frames, pixel changes and metadata drift. It is not an artistic review. The manifest records the Pillow version; use the same environment when reproducing palette choices.

## Continue the existing workflow

After inspecting the conversion, import its exact layout through the existing entry point:

```bash
python <skill-dir>/scripts/unpack_atlas_run.py --manifest work/pixel-conversion/conversion.json --out-dir work/converted-run --frame-semantics animation --background-removal none --extraction-mode slots
```

Use the actual semantics instead of `animation` for another kind. The existing manifest reader carries the rectangles, integer FPS and loop policy. The converted source has imported provenance. Keep the conversion bundle linked in the run's source evidence.

The converted pivot remains in `conversion.output_pivot`; the importer does not apply that field as runtime registration. Carry it into the explicit registration/runtime contract before packaging. Do not infer a new foot baseline from the reduced frames. Run the lane's existing playback/contact/identity and final validation gates. Recheck any accepted source or art review because conversion creates new pixels. Tiles and seamless textures need their adjacency/repeat contract and are outside this first converter.

## When to suggest it

- “Convert this animation sheet to pixel art”: offer or invoke this route after the cell, palette and temporal contract are known.
- “Make these imported characters 64x64 pixel art”: use static semantics if the poses are variants.
- “Pack these sprites without changing their pixels”: keep the normal exact-RGBA workflow; do not invoke conversion.
- “Generate a retro animation”: follow the provider and animation workflows; retro style alone does not authorize converting an existing source.
