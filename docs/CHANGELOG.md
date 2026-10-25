# Changelog

## 2026-09-08

- Added an opt-in, project-owned pixel-art converter for explicit conversion requests. It uses one scale and shared RGB palette, preserves sampled alpha and frame placement, and writes a separate source snapshot, manifest, frames, and comparison player.
- Linked the converter to the existing atlas importer. Timing and cell rectangles transfer; the recorded pivot still requires the downstream registration contract. Conversion remains subject to visual review and does not replace normal extraction or generation.

## 2026-08-15

- Updated pnpm to 11.21.0 and aligned the optional rembg requirement with the Python project pin.
- Repaired cross-platform CI by installing pnpm explicitly and pinning all GitHub Actions.
- Added a project site, sponsor metadata, contribution guidance, adaptive badges, and four real pipeline review sheets.
- Updated the isolation contract to prefer trustworthy provider-native alpha before approved fallback removal lanes.

## 2026-08-12

- Migrated validator scripts/CI/docs to pnpm 11.20.0 and generated `pnpm-lock.yaml`.
- Updated rembg CPU extra to 2.0.78; verified all other Python pins are current.



