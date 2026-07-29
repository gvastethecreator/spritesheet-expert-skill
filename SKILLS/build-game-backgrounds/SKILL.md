---
name: build-game-backgrounds
description: "Build and validate layered raster backgrounds for games. Use for parallax scenes, scrolling panoramas, environment layers, horizon-safe compositions, or background packs that need deterministic manifests and visual proof."
---

# Build Game Backgrounds

Produce a portable layered-background pack whose source files, camera contract, hashes, composite, and scrolling proof agree.

## Workflow

1. Define the scene contract before generating art.
   - Fix canvas size, aspect ratio, horizon, focal safe zone, layer order, depth, parallax factors, repeat behavior, and style fingerprint.
   - Use this skill for background planes. Route animated sprites and atlases to `$spritesheet-expert`; route isolated props to `$build-static-game-assets`.

2. Generate or import the layers.
   - Use `$imagegen` for new user-facing bitmap art and preserve its provenance.
   - Keep every source below one pack root. Use portable relative paths and record SHA-256 for each layer.
   - Keep sky, far, mid, near, foreground, overlay, and effects roles explicit. Do not bake gameplay-critical objects into a background without naming the tradeoff.

3. Write `background-pack.json` against `references/schemas/background-pack-v1.schema.json`.
   - Require `schema_version`, `kind`, `pack_id`, `style_fingerprint`, `canvas`, `camera`, and `layers`.
   - Reject duplicate order/depth ambiguity, hash drift, missing sources, unsafe paths, invalid safe zones, or incompatible dimensions.

4. Validate and generate deterministic proof.

```powershell
python scripts/validate_background_pack.py --pack <pack-root>/background-pack.json --root <pack-root>
```

The command writes `qa/background-pack-report.json`, `qa/background-composite.png`, and `qa/background-scroll.gif` atomically. From the installed skill directory run `python -m pip install -r requirements-runtime.txt` when the preflight reports a missing module.

5. Inspect the actual composite and scrolling preview.
   - Check seams, focal readability, horizon stability, parallax order, crop behavior, contrast behind gameplay, and repeated-edge continuity.
   - Fix the source or contract and rerun. Do not approve from JSON alone.

## Completion Contract

Finish only when the validator exits zero, every input hash is current, all paths are portable, the report references current proof hashes, and both proof images have been inspected. Keep prior proof unchanged when contract validation fails.

## Resources

- `scripts/validate_background_pack.py`: public validation and proof CLI.
- `scripts/background_pack/`: schema and semantic validation implementation.
- `references/schemas/background-pack-v1.schema.json`: public pack contract.
