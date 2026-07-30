---
name: compose-asset-mockups
description: "Compose already validated game assets into non-destructive presentation mockups. Use for store art, review boards, gameplay reconstructions, pitch layouts, or evidence-backed presentations that preserve source hashes, licenses, provenance, representative-media status, and truth labels."
---

# Compose Asset Mockups

Create derived presentations from already validated assets without mutating sources or presenting a reconstruction as captured gameplay.

## Workflow

1. Accept only pinned inputs.
   - Require each asset and font to reference its artifact, upstream manifest, validation report, SHA-256, license, and provenance.
   - Send unvalidated sources back to their owning asset skill. Do not repair or regenerate them inside this skill.
   - Reject upstream reports whose production-media evidence is missing, stale, or marked non-representative. A deterministic fixture, placeholder, or reconstructed substitute cannot stand in for a rejected source asset.

2. Define the presentation contract.
   - Write `presentation.json` against `references/schemas/presentation.schema.json`.
   - Fix the brief, approved copy, brand kit, inventory, gameplay scenes, compositions, licenses, provenance, and output manifest.
   - Label every scene as runtime-captured, reconstructed, or illustrative. Attach capture evidence only to runtime-captured truth.

3. Seal and resolve imported content.

```powershell
python scripts/prepare_presentation.py --presentation <root>/presentation.json --root <root>
```

The command validates the contract, writes canonical prepared/resolved JSON, verifies every pin, and copies imported content into `presentation/content-addressed/`. Use `--validate-only` when no import copy is wanted. From the installed skill directory run `python -m pip install -r requirements-runtime.txt` when needed.

4. Build only derived outputs.
   - Compose from the resolved content store using the project's existing image, HTML/canvas, or design tooling.
   - Respect canvas, safe zone, layer order, asset list, licensed fonts, approved copy, and resampling rules.
   - Deterministic composition is allowed because it arranges approved pixels. It must not invent missing character, prop, background, or UI art. Return missing production media to `$imagegen`, the explicitly selected `$grok-imagine` still route, or the owning asset skill.
   - Keep outputs under `presentation/outputs/`; never overwrite source assets, manifests, reports, fonts, or licenses.

5. Capture and reconcile proof.
   - Inspect each output at delivery size and verify crop, readability, source fidelity, license/provenance coverage, truth label, and hash.
   - A contact board proves presentation layout only. Runtime-captured claims require hash-backed capture evidence; reconstructed and illustrative outputs keep their truth labels visible in the contract.
   - Update the presentation manifest and any runtime capture evidence. Revalidate before handing the presentation to `$produce-2d-assets`.

## Completion Contract

Finish only when preparation exits zero, all imports are hash-verified, every output belongs to a declared composition, licenses and provenance are complete, truth labels are honest, and the actual mockups have been inspected.

## Resources

- `scripts/prepare_presentation.py`: public validation, sealing, and import CLI.
- `scripts/presentation_pipeline/`: contract and content-addressed preparation library.
- `references/schemas/`: presentation, brief, composition, evidence, inventory, license, provenance, and manifest contracts.
