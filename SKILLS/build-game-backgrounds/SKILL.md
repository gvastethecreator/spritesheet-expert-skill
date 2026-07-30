---
name: build-game-backgrounds
description: "Build and validate layered raster game backgrounds from imported art, Imagegen, or explicit Grok stills. Use for full-bleed parallax scenes, scrolling panoramas, environment layers, horizon-safe composition, provenance, manifests, and visual proof."
---

# Build Game Backgrounds

Produce a portable layered-background pack whose source files, camera contract, hashes, composite, and scrolling proof agree.

## Workflow

1. Define the scene contract before generating art.
   - Fix canvas size, aspect ratio, horizon, focal safe zone, layer order, depth, parallax factors, repeat behavior, and style fingerprint.
   - Use this skill for background planes. Route animated sprites and atlases to `$spritesheet-expert`; route isolated props to `$build-static-game-assets`.

2. Generate or import the layers.
   - Use `$imagegen` by default for new user-facing bitmap art. Load `$grok-imagine` only when Grok still generation is selected explicitly. Provider execution creates semantic pixels; deterministic code may assemble layers, scroll them, measure seams, and render proof, but must not paint replacement production scenery.
   - Full-bleed scene layers keep their authored scene pixels; do not force them onto a neutral matte. If a layer is an isolated transparent overlay, generate it on flat gray, black, or white and use model-backed removal when connected-matte removal threatens subject colors. Never request new green, blue, cyan, or magenta chroma.
   - For Grok, review `--dry-run` first and use `--ack-run` only with explicit current-task consent. Video animation belongs to `$spritesheet-expert`; this skill accepts still layers.
   - Keep every source below one pack root. Use portable relative paths and record SHA-256 for each layer.
   - Declare provenance for every layer as Imagegen, Grok still, imported, or fixture. Fixtures may exercise composition and seam gates but are not representative art.
   - Keep sky, far, mid, near, foreground, overlay, and effects roles explicit. Do not bake gameplay-critical objects into a background without naming the tradeoff.
   - If composition, continuity, depth, or requested semantics fail, regenerate the affected provider layer. Edge harmonization may touch only a narrow provider-derived repeat band and must retain the original hash; it cannot become procedural replacement art.

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
   - The composite proves layer order and framing. The scrolling GIF proves the declared offset/repeat behavior. Inspect both; one cannot substitute for the other.
   - Fix the source or contract and rerun. Do not approve from JSON alone.

## Completion Contract

Finish only when the validator exits zero, every input/provenance hash is current, `representative` is true, all paths are portable, the report references current proof hashes, and both proof images have been inspected. Fixture reports may pass technical validation but cannot satisfy production completion. Keep prior proof unchanged when contract validation fails.

## Resources

- `scripts/validate_background_pack.py`: public validation and proof CLI.
- `scripts/background_pack/`: schema and semantic validation implementation.
- `references/schemas/background-pack-v1.schema.json`: public pack contract.
