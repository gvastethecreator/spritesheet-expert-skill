---
name: build-game-ui-kits
license: MIT
description: "Game UI kits: raster UI from imported art, Imagegen, or explicit Grok stills; controls, icons, HUD parts, native alpha or reviewed cutouts, interaction states, density variants, nine-slice assets, provenance, state/stretch proof."
---

# Build Game UI Kits

Create a portable raster family with explicit components, tokens, densities, states and nine-slice geometry. This folder contains the complete raster UI workflow. Animation and cross-family coordination are separate scopes.

## Workflow

1. Define components, intended sizes/densities, required states, stretch regions, color tokens and style fingerprint. Use the state keys supported by [the schema](references/schemas/ui-kit-v1.schema.json). A missing state contract needs a decision; do not silently rename it to a different behavior. Done when the requested controls and state coverage are explicit.
2. Import approved art or use the available image tool, with Imagegen as the default and Grok stills only when explicitly selected. Keep the exact request, provider result and selected bytes, then fill the bundled schema's provenance fields. No separate skill is required. `$imagegen` and `$grok-imagine` are optional client adapters; Grok's `--ack-run` requires a reviewed dry run and current-task consent. Without generation access, use approved imports or record the missing provider. Keep real provenance on every state/density variant. A fixture tests geometry, not production media. Deterministic tools may prepare and validate assets; they must not draw replacement production UI. Done when current source paths and hashes identify the actual art.
3. Preserve accepted identity, text/icon geometry and valid native alpha. For a necessary matte, use flat gray, black, or white. Do not request new green, blue, cyan, or magenta chroma. Use a reviewed cutout when neutral subject colors make removal ambiguous. BiRefNet/BEN2 comparison requires that scope; it does not justify replacing good native alpha. Regenerate a failed semantic state from the accepted provider base instead of procedurally repainting production UI. Done when every required state is actually distinct where its behavior requires it and all art is below the kit root.
4. Write `ui-kit.json` and run the installed skill's CLI from any working directory:

   ```powershell
   python "<skill-root>/scripts/validate_ui_kit.py" --kit "<kit-root>/ui-kit.json" --root "<kit-root>"
   ```

   Use the existing runtime and [requirements](requirements-runtime.txt); installation needs the task's authority. Done when schema, source hashes, states/densities and geometry checks pass or failures are recorded.
5. Inspect state and stretch evidence, plus the source variants at their intended render sizes. The state board proves state/density comparison only at thumbnail scale. Check identity, legibility, alignment, focus cues, alpha edges and required density/state parity. A thumbnail comparison cannot establish one-to-one readability or an interactive control's behavior. Done when each requested visual/state/stretch claim has relevant proof, with gaps kept visible.

## Validator and proof scope

The CLI writes `qa/ui-kit-report.json`, `qa/ui-state-board.png` and `qa/ui-nine-slice.png`. Each replacement is atomic individually. Path-preflight errors emit stdout JSON without writing a report; other contract failures may replace the diagnostic report while retaining old proof images. This is not a transaction, and operational failures can leave a mixed set. Verify the final hashes and current result.

The state board fits variants into thumbnail cells. Contrast is calculated from declared foreground/background tokens, not measured from rasterized text or every state image. The helper's stretch board uses density 1 and the first required state where applicable. An empty placeholder or an unrendered required variant is not stretch proof. Mark truly inapplicable checks as such; supply the missing applicable stretch/state evidence before claiming completion.

`representative` reflects non-fixture provenance declarations. Hash checks bind bytes and supplied records; they do not independently prove authorship, art rights, acceptable cutout quality or complete accessibility. Keep actual visual inspection and relevant runtime/input proof when the requested delivery includes it.

## Completion

Require a current successful report, matching source/proof hashes, portable paths, valid provenance, all required states/densities and inspected applicable boards. A fixture pass or token contrast value is not production-art or whole-control approval. Preserve accepted sources and useful proof; cleanup needs the project's authority.

[validation module](scripts/ui_kit/validation.py) owns the validator/rendering. The bundled MIT [LICENSE](LICENSE) is for the skill code, not a substitute for the source-art rights record.
