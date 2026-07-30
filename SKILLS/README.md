# Skills

This repo ships six focused Codex skills:

- [`produce-2d-assets`](./produce-2d-assets/SKILL.md): coordinate and validate multi-family 2D deliveries.
- [`spritesheet-expert`](./spritesheet-expert/SKILL.md): build spritesheets, tilesets, textures, animation rows, and atlases.
- [`build-static-game-assets`](./build-static-game-assets/SKILL.md): validate non-animated props, pickups, decals, and item packs.
- [`build-game-backgrounds`](./build-game-backgrounds/SKILL.md): validate layered, scrolling, and parallax backgrounds.
- [`build-game-ui-kits`](./build-game-ui-kits/SKILL.md): validate raster UI states, densities, and nine-slice assets.
- [`compose-asset-mockups`](./compose-asset-mockups/SKILL.md): prepare non-destructive, evidence-backed asset presentations.

Use one leaf skill for a single family. Use `produce-2d-assets` only when one delivery needs two or more families and a shared manifest.

## Production Media Contract

- `$imagegen` is the default still provider. `$grok-imagine` is explicit, dry-run-first, and requires current-task acknowledgement for a paid run; video-to-frames belongs to `spritesheet-expert`.
- Deterministic code may prepare, extract, register, cut out, compose, preview, and validate. It must not create replacement production art.
- Isolated sprites, props, and UI use gray/black/white source backgrounds, never new green/blue/cyan/magenta chroma. Full-bleed background scenes retain authored scene pixels.
- Every produced source declares verified provider/import provenance. Fixtures and placeholders remain non-representative even when technical validation passes.
- Inspect the proof that matches the claim: playback/contact/onion for animation, composite plus scroll for backgrounds, state plus stretch boards for UI, multi-background alpha contact boards for static art, and hash-backed truth labels for mockups.
