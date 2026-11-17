---
name: build-static-game-assets
license: MIT
description: "Static game assets: non-animated raster from imported art, Imagegen, or explicit Grok stills; props, pickups, decals, item icons, native alpha or reviewed cutouts, pivots, sizing, provenance, hashes, contact-sheet proof."
---

# Build Static Game Assets

Create a portable non-animated raster pack with explicit roles, sizes, pivots, crop policy, source rights, provenance and proof. This folder contains the complete static-asset workflow. Animation, backgrounds and raster controls are separate scopes.

## Workflow

1. Define the inventory and intended use. Record each id, role, target size, pivot, transparency/crop policy, scale class, license reference and shared style fingerprint. Done when the required assets and their contracts are explicit.
2. Import approved source art or use an available image tool, with Imagegen as the default and Grok stills only when explicitly selected. Keep the exact request, provider result and selected bytes, then fill the bundled schema's `source.provenance` fields. No separate skill is required. `$imagegen` and the Grok Imagine CLI are optional client tools; a paid Grok run requires a reviewed dry run and current-task consent. Missing generation access blocks new art, not approved imports. Never call paid inference from tests. Deterministic tools may crop, cut out, resize and assemble proof. They must not draw replacement production art. Done when each source path/hash and real provenance is recorded below the pack root.
3. Preserve accepted identity, transparent margins and valid native alpha. If a matte is needed, use neutral gray, black, or white. Do not request new green, blue, cyan, or magenta chroma. Use a reviewed cutout where subject neutrals make removal ambiguous. BiRefNet/BEN2 are scoped comparison options, not permission to replace valid alpha. Regenerate semantic/anatomical failures through the selected provider rather than procedurally repainting them. Done when preparation preserves the intended silhouette, crop and pivot instead of hiding defects by scaling a proof.
4. Write `static-pack.json` against [the schema](references/schemas/static-asset-pack-v1.schema.json), then run the installed CLI from any working directory:

   ```powershell
   python "<skill-root>/scripts/validate_static_pack.py" --pack "<pack-root>/static-pack.json" --root "<pack-root>"
   ```

   Use the existing Python runtime and [requirements](requirements-runtime.txt). Installing missing packages needs the task's authority. Done when current schema, paths, hashes, declared license references, dimensions, lineage and transparency checks pass or the actual failure is recorded.
5. Inspect the contact sheet and assets at intended render size. Check silhouette, relative scale, alpha edges, crop, palette/style and readability. Inspect pivot behavior in its actual coordinate/engine context when that claim is required; the contact sheet does not draw or exercise every pivot. Done when requested visual/use claims have appropriate proof and remaining gaps are explicit.

## Rules that fail a pack

Plan sizes and margins against these before generating; the validator rejects each one.

- Each source is exactly `target.width` × `target.height`. Resize or pad to the target before hashing. A generator's default square output rarely matches.
- `transparency: required` needs at least one pixel with alpha below 255. `opaque` forbids any alpha below 255. `either` checks neither.
- Isolated roles (`prop`, `item`, `pickup`, `icon`, `cursor`, `badge`) fail when visible pixels touch any image edge. Keep a transparent margin of at least 1 px; 2–4 px leaves room for outlines and filtering. `portrait` and `key-art` may bleed.
- Occupancy is the share of pixels with alpha above 0. Every asset needs at least 1%, and isolated roles may not exceed 95%.
- License status must match provenance: `imagegen` and `grok-imagine-image` need `generated`, `fixture` needs `fixture`, and `imported` needs `user-owned` or `licensed`.
- A variant's `parent_sha256` must equal its parent's current source hash. Regenerating a parent makes every child stale. Cycles fail.
- `pivot` is normalized (`x`, `y` in 0–1). Use bottom-center (0.5, 1.0) for grounded props and center (0.5, 0.5) for icons and pickups, unless the engine says otherwise. The contact sheet does not draw pivots.
- Paths are relative POSIX paths inside the pack root, and `grok-imagine-image` sources need a `provider_record` inside it.

## Validator and proof scope

The CLI writes `qa/static-pack-report.json` and `qa/static-pack-contact.png`. File replacements are atomic individually, not together. Path-preflight errors emit stdout JSON without a report write. Other contract failures can write a failure report while preserving old proof images; old images do not establish a successful current result. Operational failure can leave mixed generations, so verify report/proof hashes before accepting delivery.

The contact sheet is a resized comparison on checker/black/gray/white backgrounds, not a one-to-one render, animation, interaction or authorship test. Read actual source bytes and metadata for the requested claim. Validator occupancy/edge checks are contract gates, not universal measures of good art; do not alter approved pixels merely to obtain green output.

`representative` is derived from the supplied non-fixture provenance. Hash checks bind those bytes and records, not independent authorship or legal clearance. Keep generated, imported and fixture sources explicit; license references must describe the actual art rights. A fixture can validate the pipeline but cannot close production-art delivery.

## Completion

Require a successful current report, matching source/proof hashes, portable paths, valid provenance/license records and inspected applicable visual proof. Keep any missing target-size, pivot or runtime claim unverified. Preserve accepted media and useful evidence; cleanup follows project authority.

[validation module](scripts/static_assets/validation.py) owns validation and contact rendering. The bundled MIT [LICENSE](LICENSE) covers the skill code separately from pack artwork.
