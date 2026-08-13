# Spritesheet Expert

![Spritesheet Expert banner](./assets/readme-banner.png)

> Codex skill pack for producing and validating sprites, static assets, backgrounds, UI kits, mockups, and coherent multi-family 2D deliveries.

[![License: MIT](https://shieldcn.dev/badge/license-MIT-yellow.svg?variant=secondary&size=xs)](./LICENSE)
[![Status](https://shieldcn.dev/badge/status-preview-purple.svg?variant=secondary&size=xs)](#status)

The suite turns game-art requests into repeatable, hash-backed pipelines. Use the focused leaf skills for one asset family and `produce-2d-assets` when a delivery spans several families.

- Prepare structured sprite and tileset runs from presets or custom contracts.
- Generate isolated sprites, props, and UI on neutral gray/black/white. Use pinned Lucida plus adaptive frame bounds for new character grids, with reviewed BiRefNet/BEN2 compatibility lanes. Keep full-bleed background scene pixels intact.
- Use `$imagegen` by default or the optional dry-run-first `$grok-imagine` image/video route.
- Turn an approved first frame into provider video, then deterministically sample it into the normal verified sprite pipeline.
- Compose atlas PNGs, manifests, deterministic previews, an interactive review workbench, GIFs, checker/black/gray/white alpha boards, and curation exports.
- Run checks for provenance, identity, alignment, animation contracts, and tileset placement.
- Validate static props, layered backgrounds, raster UI states, presentation truth, and aggregate delivery manifests.
- Keep semantic visual generation separate from deterministic extraction, registration, composition, preview, and QA. Fixtures can pass technical smoke gates but never count as representative production media.

## Quick Install

Install with the Skills CLI:

```powershell
npx skills add gvastethecreator/spritesheet-expert-skill
```

Or download this repo and ask Codex to install `spritesheet-expert` in your workspace.

Skills CLI publishes six packages: `produce-2d-assets`, `spritesheet-expert`, `build-static-game-assets`, `build-game-backgrounds`, `build-game-ui-kits`, and `compose-asset-mockups`.

## Useful Commands

Smoke test the deterministic pipeline:

```powershell
python .\SKILLS\spritesheet-expert\scripts\smoke_pipeline.py
```

Prepare the pinned Python environment and check it:

```powershell
pnpm run setup:test
pnpm run doctor:test
```

The smoke test uses fixtures. Representative game art still requires real generated or imported source images.

Validate the public skill package:

```powershell
pnpm run validate
```

Run the complete contract and integration suite, or the full release gate:

```powershell
pnpm test
pnpm run check
```

## What's Inside

- [`SKILL.md`](./SKILLS/spritesheet-expert/SKILL.md): routing, rules, and pipeline contract.
- [`references/`](./SKILLS/spritesheet-expert/references): atlas, pixel art, animation, isometric, workflow, and QA notes.
- [`scripts/`](./SKILLS/spritesheet-expert/scripts): extraction, curation, composition, preview, and validation helpers.
- [`agents/openai.yaml`](./SKILLS/spritesheet-expert/agents/openai.yaml): optional agent metadata.

Optional runtime extras are isolated by capability: install `SKILLS/spritesheet-expert/scripts/requirements-lucida.txt` for the preferred sprite cutout lane, `requirements-background.txt` for rembg/BiRefNet, and `requirements-video.txt` for video-frame ingestion.
- [`SKILLS/`](./SKILLS/README.md): routing and commands for all six published skills.

## Status

Validated multi-skill pack.

- Local smoke pipeline is available.
- Optional Lucida, rembg, and BEN2 background-removal dependencies are intentionally not bundled.
- Optional video decoding uses the pinned `scripts/requirements-video.txt`; provider inference is never part of tests.
- Generated sample art is not included by default; bring your own licensed source images.
- Rejected motion-reference candidates remain in repository-only `maintenance/` evidence and are never copied into an installed skill.

## License

MIT. Some bundled sprite pipeline files also preserve their original Apache-2.0 notice files inside the skill package.
