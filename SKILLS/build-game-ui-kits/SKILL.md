---
name: build-game-ui-kits
description: "Build and validate raster game UI from imported art, Imagegen, or explicit Grok stills. Use for neutral-background controls, icons, HUD parts, interaction states, density variants, nine-slice assets, provenance, and state/stretch proof."
---

# Build Game UI Kits

Produce a portable raster UI kit with explicit tokens, densities, component states, hashes, and visual proof.

## Workflow

1. Freeze the UI contract.
   - Name required components, base sizes, densities, interaction states, nine-slice regions, palette tokens, minimum contrast, and the shared style fingerprint.
   - Use this skill for raster UI families. Route animated character art to `$spritesheet-expert` and cross-family delivery to `$produce-2d-assets`.

2. Generate or import component art.
   - Use `$imagegen` by default for new user-facing bitmap art. Load `$grok-imagine` only when Grok still generation is selected explicitly. Provider execution creates semantic pixels; deterministic code may cut out, resize, assemble states, stretch nine-slices, and render proof, but must not draw replacement production UI.
   - Generate isolated controls and icons on flat gray, black, or white. Never request new green, blue, cyan, or magenta chroma. Preserve neutral fills and outlines; use BiRefNet/BEN2 or another reviewed model-backed cutout when connected-matte removal is ambiguous.
   - For Grok, review `--dry-run` first and use `--ack-run` only with explicit current-task consent. Route animated UI/VFX sequences to `$spritesheet-expert`.
   - Keep every density and state below one kit root. Use portable relative paths.
   - Declare provenance on every state/density variant as Imagegen, Grok still, imported, or fixture. A fixture may validate state geometry but is not representative production media.
   - Include every required state such as default, hover, pressed, disabled, selected, focus, or checked when the component can enter it. Do not represent a state by renaming an identical file.
   - If a state loses identity, text/icon geometry, edge quality, or semantics, regenerate it through the provider using the accepted base state as reference. Do not procedurally repaint the failed state and label it generated.

3. Write `ui-kit.json` against `references/schemas/ui-kit-v1.schema.json`.
   - Require `schema_version`, `kind`, `kit_id`, `style_fingerprint`, `densities`, `tokens`, and `components`.
   - Reject missing states/densities, hash drift, unsafe paths, invalid nine-slice geometry, inconsistent sizes, and insufficient declared contrast.

4. Validate and render proof.

```powershell
python scripts/validate_ui_kit.py --kit <kit-root>/ui-kit.json --root <kit-root>
```

The command writes `qa/ui-kit-report.json`, `qa/ui-state-board.png`, and `qa/ui-nine-slice.png` atomically. From the installed skill directory run `python -m pip install -r requirements-runtime.txt` when needed.

5. Inspect the boards at intended scale.
   - Verify state distinction, legibility, optical alignment, pixel snapping, focus visibility, density parity, and nine-slice corners/edges.
   - The state board proves state/density comparison. The stretch board proves nine-slice behavior. Inspect alpha edges against checker/black/gray/white when transparency is present.
   - Treat the deterministic report as a gate, not a substitute for visual inspection.

## Completion Contract

Finish only when the validator exits zero, source/provenance hashes are current, `representative` is true, every required state and density is present, paths are portable, and both proof boards have been inspected. Fixture reports may pass technical validation but cannot satisfy production completion. Failed validation must not replace prior valid proof.

## Resources

- `scripts/validate_ui_kit.py`: public validation and proof CLI.
- `scripts/ui_kit/`: schema and semantic validation implementation.
- `references/schemas/ui-kit-v1.schema.json`: public kit contract.
