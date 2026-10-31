# Skills

Six skills:

- [`produce-2d-assets`](./produce-2d-assets/SKILL.md): coordinate and validate multi-family 2D deliveries.
- [`spritesheet-expert`](./spritesheet-expert/SKILL.md): build spritesheets, tilesets, textures, animation rows, and atlases.
- [`build-static-game-assets`](./build-static-game-assets/SKILL.md): validate non-animated props, pickups, decals, and item packs.
- [`build-game-backgrounds`](./build-game-backgrounds/SKILL.md): validate layered, scrolling, and parallax backgrounds.
- [`build-game-ui-kits`](./build-game-ui-kits/SKILL.md): validate raster UI states, densities, and nine-slice assets.
- [`compose-asset-mockups`](./compose-asset-mockups/SKILL.md): prepare non-destructive evidence-backed presentations.

One leaf skill per family. `produce-2d-assets` only when a delivery needs two+ families plus shared manifest.

Each folder can be copied on its own. `produce-2d-assets/workflows/` includes the five family guides and their implementations, with `WORKFLOW.md` entrypoints to avoid duplicate skill discovery. No separate skills are required; the selected workflow still needs its declared runtime and an image tool or approved source media. Maintainers use `pnpm run sync:bundles` after changing a family and `pnpm run validate:bundles` to detect drift.

## Production Media Contract

- `$imagegen` default still provider. Grok Imagine explicit, dry-run-first; paid run needs current-task acknowledgment. Video-to-frames → `spritesheet-expert`.
- Deterministic code may prepare, extract, register, cut out, compose, preview, validate — not create replacement production art.
- Isolated sprites, props, and UI prefer native alpha and preserve valid transparency. Use gray/black/white source backgrounds only when a matte is required; never request new green/blue/cyan/magenta chroma. Full-bleed backgrounds keep authored scene pixels.
- Every produced source declares verified provider/import provenance. Fixtures and placeholders stay non-representative even if validation passes.
- Inspect matching proof: playback/contact/onion for animation; composite plus scroll for backgrounds; state plus stretch boards for UI; multi-background alpha contact for static art; hash-backed truth labels for mockups.

