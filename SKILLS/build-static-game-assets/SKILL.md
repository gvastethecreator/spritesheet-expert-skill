---
name: build-static-game-assets
description: "Build and validate non-animated raster asset packs for games. Use for props, pickups, decals, item icons, environment objects, or other static assets that need pivots, sizing, licenses, hashes, and contact-sheet proof."
---

# Build Static Game Assets

Produce a portable static-asset pack with explicit roles, dimensions, pivots, crop policy, licensing, provenance, and deterministic proof.

## Workflow

1. Define the asset inventory.
   - Fix each id, role, target size, pivot, transparency rule, crop policy, scale class, license, and shared style fingerprint.
   - Use this skill only for non-animated assets. Route frame sequences and atlases to `$spritesheet-expert`, backgrounds to `$build-game-backgrounds`, and raster controls to `$build-game-ui-kits`.

2. Generate or import real source art.
   - Use `$imagegen` for new user-facing bitmap art and record provenance.
   - Keep sources below one pack root with portable relative paths and SHA-256 pins.
   - Preserve transparent margins intentionally; do not hide crop or pivot defects by resizing the proof.

3. Write `static-pack.json` against `references/schemas/static-asset-pack-v1.schema.json`.
   - Require `schema_version`, `kind`, `pack_id`, `style_fingerprint`, `licenses`, and `assets`.
   - Reject unknown licenses, duplicate ids, stale hashes, unsafe paths, invalid pivots, cyclic references, dimension mismatch, or unsupported crop/transparency policies.

4. Validate and render the contact proof.

```powershell
python scripts/validate_static_pack.py --pack <pack-root>/static-pack.json --root <pack-root>
```

The command writes `qa/static-pack-report.json` and `qa/static-pack-contact.png` atomically. From the installed skill directory run `python -m pip install -r requirements-runtime.txt` when needed.

5. Inspect the contact sheet.
   - Check silhouette, consistent scale, pivot intent, alpha edges, cropping, role coverage, palette/style continuity, and readability at target size.

## Completion Contract

Finish only when the validator exits zero, every source/license pin is current, paths are portable, the contact-sheet hash matches the report, and the actual sheet has been inspected. Failed validation must preserve previous proof.

## Resources

- `scripts/validate_static_pack.py`: public validation and contact-proof CLI.
- `scripts/static_assets/`: schema and semantic validation implementation.
- `references/schemas/static-asset-pack-v1.schema.json`: public pack contract.
