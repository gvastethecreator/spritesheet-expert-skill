---
name: build-game-backgrounds
license: MIT
description: "Game backgrounds: layered raster packs from imported art, Imagegen, or explicit Grok stills; full-bleed parallax, scrolling panoramas, environment layers, horizon-safe composition, provenance, manifests, visual proof."
---

# Build Game Backgrounds

Create a portable layered pack whose sources, declared camera contract and proof agree. Full-bleed scene layers belong here; animated sprites, atlases and isolated prop production are separate scopes. This folder contains the complete background workflow.

## Workflow

1. Define the requested scene before generating art. Record canvas/aspect, horizon, focal safe zone, layer order/depth, parallax, repeat behavior and style fingerprint. Keep the pack's supported schema roles rather than inventing aliases. Done when the requested view and layer responsibilities are explicit.
2. Import approved art or generate it through an available image tool. Use Imagegen by default for new bitmap art; Grok stills require explicit provider selection. Keep the exact request, provider result and selected bytes, then fill the bundled schema's provenance fields. No separate skill is required. `$imagegen` and the Grok Imagine CLI are optional client tools; a paid Grok run requires a reviewed dry run and current-task consent. Missing generation tools block new art, not approved-source import. Deterministic code may assemble, measure seams and render proof. It must not paint replacement production scenery. Done when source paths, hashes and provenance for every layer are recorded below one pack root.
3. Preserve full-bleed authored pixels and valid alpha. For an isolated overlay, prefer native transparency. If a matte is necessary, use neutral gray/black/white and a reviewed cutout when subject colors are at risk; do not request new green, blue, cyan, or magenta chroma. A composition or semantic failure needs the affected provider layer regenerated. Narrow repeat-edge harmonization must preserve the original source/hash and identify the derivative. Done when required media is actual approved/provider/imported art, with fixtures explicitly separated.
4. Write `background-pack.json` against [the schema](references/schemas/background-pack-v1.schema.json). Validate through this skill's CLI from any working directory, resolving the installed skill root:

   ```powershell
   python "<skill-root>/scripts/validate_background_pack.py" --pack "<pack-root>/background-pack.json" --root "<pack-root>"
   ```

   Use the existing Python runtime and [requirements](requirements-runtime.txt). Install missing requirements only within the task's authority. Do not change the project toolchain to run a proof. Done when validation passes for the current bytes or the actual failure is retained.
5. Inspect the composite and scroll sample. The composite proves layer order and blend placement for that rendered view. Judge continuity, readability behind gameplay, depth and framing. The GIF samples horizontal offsets; it does not prove vertical parallax, every camera crop, horizon behavior or a game's runtime integration. Add the actual requested view/interaction proof when needed. Done when all applicable visual claims are observed and missing proof stays explicit.

## Validator and proof scope

The CLI writes `qa/background-pack-report.json`, `qa/background-composite.png` and `qa/background-scroll.gif`. Replacement is atomic per file, not a transaction across the set. Output-path preflight errors print JSON to stdout without writing a report. Other contract failures can write a failure report while preserving existing proof images; old images alone are not a current successful result. An I/O failure can leave a mixed generation, so check final report/proof hashes before accepting it.

Schema, path, ordering, dimension, source-hash and declared-provenance checks do not establish artistic quality or authenticity. The repeat-edge metric is a technical gate, not proof of seamless scrolling at every view. Keep the gate; resolve a real contract problem rather than repainting approved art to make a metric pass.

`representative` means the supplied provenance is not marked fixture. It does not independently verify authorship, licenses or resemblance to the requested art. Fixture reports can exercise technical behavior but cannot close production-art delivery.

## Completion

Require a successful current report, matching source/proof hashes, portable paths, valid provenance and all requested visual proof. Keep both composite and scroll sample inspection; neither substitutes for the other. State any runtime/camera coverage still missing. Preserve useful failed or prior evidence and follow project authority for cleanup.

[validation module](scripts/background_pack/validation.py) owns validation and proof rendering. The bundled MIT [LICENSE](LICENSE) covers this skill's code; source-art rights and provider records remain a separate responsibility.
