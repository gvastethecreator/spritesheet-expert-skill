---
name: build-static-game-assets
description: "Build and validate non-animated raster game assets from imported art, Imagegen, or explicit Grok stills. Use for props, pickups, decals, item icons, neutral-background cutouts, pivots, sizing, provenance, hashes, and contact-sheet proof."
---

# Build Static Game Assets

Produce a portable static-asset pack with explicit roles, dimensions, pivots, crop policy, licensing, provenance, and deterministic proof.

## Workflow

1. Define the asset inventory.
   - Fix each id, role, target size, pivot, transparency rule, crop policy, scale class, license, and shared style fingerprint.
   - Use this skill only for non-animated assets. Route frame sequences and atlases to `$spritesheet-expert`, backgrounds to `$build-game-backgrounds`, and raster controls to `$build-game-ui-kits`.

2. Generate or import real source art.
   - Use `$imagegen` by default for new user-facing bitmap art. Load `$grok-imagine` only when Grok still generation is selected explicitly. Provider execution creates semantic pixels; local scripts may crop, remove backgrounds, resize, compose proof, and validate, but must not draw replacement production art.
   - Generate isolated sources on flat neutral gray, black, or white. Never request green, blue, cyan, or magenta chroma for new art. Preserve subject neutrals: prefer a model-backed cutout such as BiRefNet/BEN2 when edge-connected matte removal is ambiguous.
   - For Grok, review a `--dry-run` first and use `--ack-run` only with explicit current-task consent. Never call paid inference from tests.
   - Keep sources below one pack root with portable relative paths and SHA-256 pins.
   - Declare `source.provenance` for every asset. Generated sources identify Imagegen or Grok; imported art and fixtures stay explicit. A fixture can test the pipeline but is never representative production media.
   - Preserve transparent margins intentionally; do not hide crop or pivot defects by resizing the proof.
   - If identity, anatomy, edge quality, or requested semantics fail, regenerate through the selected provider. Do not procedurally repaint the failed asset and present it as generated art.

3. Write `static-pack.json` against `references/schemas/static-asset-pack-v1.schema.json`.
   - Require `schema_version`, `kind`, `pack_id`, `style_fingerprint`, `licenses`, and `assets`.
   - Reject unknown licenses, duplicate ids, stale hashes, unsafe paths, invalid pivots, cyclic references, dimension mismatch, or unsupported crop/transparency policies.

4. Validate and render the contact proof.

```powershell
python scripts/validate_static_pack.py --pack <pack-root>/static-pack.json --root <pack-root>
```

The command writes `qa/static-pack-report.json` and `qa/static-pack-contact.png` atomically. From the installed skill directory run `python -m pip install -r requirements-runtime.txt` when needed.

5. Inspect the contact sheet.
   - Check silhouette, consistent scale, pivot intent, alpha edges on checker/black/gray/white, cropping, role coverage, palette/style continuity, and readability at target size.
   - The contact sheet proves pack comparison, not animation, runtime interaction, or source provenance. Read those from the correct owner report and the hash-bound provenance fields.

## Completion Contract

Finish only when the validator exits zero, every source/license/provenance pin is current, `representative` is true, paths are portable, the contact-sheet hash matches the report, and the actual sheet has been inspected. Failed validation must preserve previous proof. Fixture reports may pass technical validation but cannot satisfy production completion.

## Resources

- `scripts/validate_static_pack.py`: public validation and contact-proof CLI.
- `scripts/static_assets/`: schema and semantic validation implementation.
- `references/schemas/static-asset-pack-v1.schema.json`: public pack contract.
