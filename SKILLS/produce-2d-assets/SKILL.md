---
name: produce-2d-assets
description: "Multi-family 2D asset packs: coordinate and validate when one delivery spans two or more of sprites, static props, backgrounds, UI, and mockups; reconcile Imagegen/Grok/imported provenance, representative proof, style, variants, owners, release manifests."
---

# Produce 2D Assets

Produce asset families with the bundled workflows, then validate one portable delivery pack. This folder includes all five family guides, scripts, schemas, assets, runtime requirements and licenses. No sibling skill installation is required. For a single family, use only its relevant bundled guide.

## Route By Asset Family

- Animated characters, VFX rows, tilesets, textures, or atlases: [sprite workflow](workflows/spritesheet-expert/WORKFLOW.md).
- Non-animated props, pickups, decals, and item icons: [static asset workflow](workflows/build-static-game-assets/WORKFLOW.md).
- Layered, scrolling, or parallax scenes: [background workflow](workflows/build-game-backgrounds/WORKFLOW.md).
- Raster controls, HUD components, states, densities, and nine-slice assets: [raster UI workflow](workflows/build-game-ui-kits/WORKFLOW.md).
- Contact sheets, store art, review boards, and reconstructed gameplay presentations: [presentation workflow](workflows/compose-asset-mockups/WORKFLOW.md).

Resolve a guide's relative paths and `<skill-root>` from its own `workflows/<family>/` folder. Run its CLI by absolute path; write media and reports to the delivery root. Install only the selected family's declared runtime requirements when authorized. Image-generation tools and optional model weights remain external capabilities, not bundled credentials or skills.

Execute directly for small local work. Delegate only when authorized and parallel ownership adds value. One owner per file; one coordinator for style and delivery.

## Workflow

1. Freeze the cross-family contract.
   - Pack id, owners, style bible, inventory, variant matrix, delivery targets, dependencies, acceptance proof.
   - One style fingerprint across families. State allowed differences; do not let families drift.
   - Semantic provider per generated family: available Imagegen tool by default, Grok only when selected. `$imagegen` and the Grok Imagine CLI are optional client tools; paid runs need reviewed dry-run plus current-task acknowledgement. For video-to-frames, follow the bundled sprite guide, including its runner-free existing-video intake.

2. Produce each family through its owner.
   - Real source provenance, licenses, portable paths, current hashes, and the selected bundled family's deterministic report/proof.
   - Inspect provenance and representative family proof before setting `evidence.production_media`: `representative: true`, `provenance_verified: true`, explicit `source_types`. These fields record declarations; keep the supporting evidence. Imagegen/Grok/imported stay distinct. Fixtures, placeholders, deterministic drawings, legacy-unverified media cannot satisfy a production family.
   - Isolated sprites, props and UI follow their leaf owner's alpha policy: prefer and preserve valid native transparency. Use a neutral gray/black/white matte only when required, with reviewed model-backed removal when extraction is ambiguous. Full-bleed backgrounds keep authored scene pixels.
   - Block a dependency until its upstream report passes. No placeholder deliverables to green the aggregate.
   - Diagnose provider failures in identity, anatomy, semantics, repeat behavior, or edge quality. Retry with a concrete change and valid authorization; otherwise record the blocker. Deterministic code may extract, align, compose, preview, and validate; it may not replace the failed semantic art.

3. Write `asset-pack.json` against the schemas under `references/schemas/`.
   - Require `schema_version`, `pack_id`, `owners`, `style_bible`, `inventory`, `variant_matrix`, and `delivery_manifest`.
   - Pin every deliverable and leaf validation report. Declare required variants and presentation status.

4. Validate the whole delivery.

```powershell
python scripts/validate_asset_pack.py --pack <pack-root>/asset-pack.json --pack-root <pack-root>
```

Writes `validation/asset-pack-validation-report.json`. Exit `0` pass, `1` contract failure, `2` real dependency still blocked, `3` operational failure. Installed skill directory: `python -m pip install -r requirements-runtime.txt` when needed.

Keep the report path separate from the pack document, declared leaf reports, deliverables, and style references. Collisions fail before writing.

5. Reconcile the real pack.
   - Inspect family proof together: scale, palette, camera, density, naming, variants, ownership, licensing, presentation truth.
   - Right proof per claim: animation playback/onion/contact, background composite plus scroll, UI state plus stretch boards, static contact/alpha, truth-labelled mockups. A single contact sheet cannot certify all families.
   - Refresh affected leaf validations after input changes, update their report hashes and fingerprint pins, then rerun the aggregate. It checks declared pins and file hashes; inspect the underlying source evidence for freshness and provenance.

## Completion Contract

Done when required family proof has been inspected, every required leaf report is current and passing, every required variant and deliverable exists with matching hashes, presentation is passed or deliberately absent, paths are portable, and the aggregate exits zero. Its contract check does not substitute for required visual review or operator acceptance.

## Resources

- `scripts/validate_asset_pack.py`: public aggregate validation CLI.
- `scripts/assetpack/`: schema, path, dependency, and delivery validation implementation.
- `references/schemas/`: style bible, inventory, variants, delivery manifest, and aggregate pack contracts.
- `workflows/`: the five bundled family implementations and their source/hash manifest. Maintainers refresh them with `pnpm run sync:bundles`; `pnpm run validate:bundles` rejects drift. These maintenance commands are not needed by an installed copy.
