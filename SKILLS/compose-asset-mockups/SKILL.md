---
name: compose-asset-mockups
description: "Compose validated game assets into non-destructive presentation mockups. Use for contact sheets, store art, review boards, gameplay reconstructions, pitch layouts, or evidence-backed presentations that must preserve source hashes, licenses, provenance, and truth labels."
---

# Compose Asset Mockups

Create derived presentations from already validated assets without mutating sources or presenting a reconstruction as captured gameplay.

## Workflow

1. Accept only pinned inputs.
   - Require each asset and font to reference its artifact, upstream manifest, validation report, SHA-256, license, and provenance.
   - Send unvalidated sources back to their owning asset skill. Do not repair or regenerate them inside this skill.

2. Define the presentation contract.
   - Write `presentation.json` against `references/schemas/presentation.schema.json`.
   - Fix the brief, approved copy, brand kit, inventory, gameplay scenes, compositions, licenses, provenance, and output manifest.
   - Label every scene as runtime-captured, reconstructed, or illustrative. Attach capture evidence only to runtime-captured truth.

3. Seal and resolve imported content.

```powershell
python scripts/prepare_presentation.py --presentation <root>/presentation.json --root <root>
```

The command validates the contract, writes canonical prepared/resolved JSON, verifies every pin, and copies imported content into `presentation/content-addressed/`. Use `--validate-only` when no import copy is wanted. Install core dependencies from the repository root with `python -m pip install -e .` when needed.

4. Build only derived outputs.
   - Compose from the resolved content store using the project's existing image, HTML/canvas, or design tooling.
   - Respect canvas, safe zone, layer order, asset list, licensed fonts, approved copy, and resampling rules.
   - Keep outputs under `presentation/outputs/`; never overwrite source assets, manifests, reports, fonts, or licenses.

5. Capture and reconcile proof.
   - Inspect each output at delivery size and verify crop, readability, source fidelity, license/provenance coverage, truth label, and hash.
   - Update the presentation manifest and any runtime capture evidence. Revalidate before handing the presentation to `$produce-2d-assets`.

## Completion Contract

Finish only when preparation exits zero, all imports are hash-verified, every output belongs to a declared composition, licenses and provenance are complete, truth labels are honest, and the actual mockups have been inspected.

## Resources

- `scripts/prepare_presentation.py`: public validation, sealing, and import CLI.
- `scripts/presentation_pipeline/`: contract and content-addressed preparation library.
- `references/schemas/`: presentation, brief, composition, evidence, inventory, license, provenance, and manifest contracts.
