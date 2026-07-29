---
name: build-game-ui-kits
description: "Build and validate raster UI kits for games. Use for buttons, panels, icons, cursors, HUD parts, interaction states, density variants, nine-slice assets, or UI packs that need state and stretch proof."
---

# Build Game UI Kits

Produce a portable raster UI kit with explicit tokens, densities, component states, hashes, and visual proof.

## Workflow

1. Freeze the UI contract.
   - Name required components, base sizes, densities, interaction states, nine-slice regions, palette tokens, minimum contrast, and the shared style fingerprint.
   - Use this skill for raster UI families. Route animated character art to `$spritesheet-expert` and cross-family delivery to `$produce-2d-assets`.

2. Generate or import component art.
   - Use `$imagegen` for new user-facing bitmap art; retain provenance and source hashes.
   - Keep every density and state below one kit root. Use portable relative paths.
   - Include every required state such as default, hover, pressed, disabled, selected, focus, or checked when the component can enter it. Do not represent a state by renaming an identical file.

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
   - Treat the deterministic report as a gate, not a substitute for visual inspection.

## Completion Contract

Finish only when the validator exits zero, source hashes are current, every required state and density is present, paths are portable, and both proof boards have been inspected. Failed validation must not replace prior valid proof.

## Resources

- `scripts/validate_ui_kit.py`: public validation and proof CLI.
- `scripts/ui_kit/`: schema and semantic validation implementation.
- `references/schemas/ui-kit-v1.schema.json`: public kit contract.
