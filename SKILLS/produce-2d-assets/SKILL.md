---
name: produce-2d-assets
description: "Coordinate and validate coherent multi-family 2D game asset packs. Use when one delivery spans two or more of sprites, static props, backgrounds, UI, and mockups and must reconcile Imagegen/Grok/imported provenance, representative proof, style, variants, owners, and release manifests."
---

# Produce 2D Assets

Coordinate multiple asset families through their owning skills, then validate one portable delivery pack. For a single family, use its leaf skill directly.

## Route By Asset Family

- Animated characters, VFX rows, tilesets, textures, or atlases: `$spritesheet-expert`.
- Non-animated props, pickups, decals, and item icons: `$build-static-game-assets`.
- Layered, scrolling, or parallax scenes: `$build-game-backgrounds`.
- Raster controls, HUD components, states, densities, and nine-slice assets: `$build-game-ui-kits`.
- Contact sheets, store art, review boards, and reconstructed gameplay presentations: `$compose-asset-mockups`.

Do not delegate merely because multiple skills exist. Execute directly when the work is small and local; use separate workers only when parallel asset ownership adds value. Keep one owner for every file and one final coordinator for style and delivery reconciliation.

## Workflow

1. Freeze the cross-family contract.
   - Define pack id, owners, style bible, inventory, variant matrix, delivery targets, dependencies, and acceptance proof.
   - Reuse one style fingerprint across participating families. Make allowed differences explicit instead of letting families drift.
   - Record the selected semantic provider per generated family: `$imagegen` is the still default; `$grok-imagine` is explicit and paid runs require reviewed dry-run plus current-task acknowledgement. Grok video-to-frames belongs to `$spritesheet-expert`.

2. Produce each family through its owner.
   - Require real source provenance, licenses, portable paths, current hashes, and the leaf skill's deterministic report/proof.
   - Require `evidence.production_media` from every production leaf with `representative: true`, `provenance_verified: true`, and explicit `source_types`. Imagegen/Grok/imported sources remain distinct; fixtures, placeholders, deterministic drawings, and legacy-unverified media cannot satisfy a production family.
   - For isolated sprites, props, and UI use neutral gray/black/white source backgrounds and reviewed model-backed removal when matte removal is ambiguous. Full-bleed backgrounds retain authored scene pixels.
   - Keep a dependency blocked until its upstream report passes. Do not create placeholder deliverables to make the aggregate green.
   - When a provider result fails identity, anatomy, semantics, repeat behavior, or edge quality, retry that provider route. Deterministic code may extract, align, compose, preview, and validate; it may not replace the failed semantic art.

3. Write `asset-pack.json` against the schemas under `references/schemas/`.
   - Require `schema_version`, `pack_id`, `owners`, `style_bible`, `inventory`, `variant_matrix`, and `delivery_manifest`.
   - Pin every deliverable and leaf validation report. Declare required variants and presentation status explicitly.

4. Validate the whole delivery.

```powershell
python scripts/validate_asset_pack.py --pack <pack-root>/asset-pack.json --pack-root <pack-root>
```

The command writes `validation/asset-pack-validation-report.json`. Exit `0` passes, `1` means contract failure, `2` means a real dependency remains blocked, and `3` means an operational failure. From the installed skill directory run `python -m pip install -r requirements-runtime.txt` when needed.

5. Reconcile the real pack.
   - Inspect the family proof artifacts together for scale, palette, camera, density, naming, variants, ownership, licensing, and presentation truth.
   - Inspect the right proof for each claim: animation playback/onion/contact evidence, background composite plus scroll, UI state plus stretch boards, static contact/alpha proof, and truth-labelled mockups. A single contact sheet cannot certify all families.
   - Run the aggregate validator again after any leaf changes; stale leaf reports must fail.

## Completion Contract

Finish only when every required leaf report is current and passing, every required variant and deliverable exists with matching hashes, the presentation is passed or deliberately absent, paths are portable, and the aggregate report exits zero.

## Resources

- `scripts/validate_asset_pack.py`: public aggregate validation CLI.
- `scripts/assetpack/`: schema, path, dependency, and delivery validation implementation.
- `references/schemas/`: style bible, inventory, variants, delivery manifest, and aggregate pack contracts.
