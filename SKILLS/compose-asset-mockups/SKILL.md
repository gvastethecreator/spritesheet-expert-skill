---
name: compose-asset-mockups
description: "Asset mockups: non-destructive presentations of validated game assets; store art, review boards, gameplay reconstructions, pitch layouts; preserve source hashes, licenses, provenance, representative-media status, truth labels."
license: MIT
---

# Compose Asset Mockups

Derived presentations from validated assets. This folder includes the presentation preparation and validation code; upstream artifacts and their real validation reports are inputs, not installed-skill dependencies. Do not mutate sources or present reconstruction as captured gameplay. Code: [MIT notice](LICENSE); imported media keep their own license terms.

## Workflow

1. Accept only pinned inputs.
   - Each asset and font must reference artifact, upstream manifest, validation report, SHA-256, license, provenance.
   - Review the owning validator's pass result and artifact coverage; report pins identify supplied bytes. Unvalidated sources return to their producer with the exact failed contract. Do not repair or regenerate them here.
   - Reject upstream reports whose production-media evidence is missing, stale, or marked non-representative. Fixture, placeholder, or reconstructed substitute cannot replace a rejected source.

2. Define the presentation contract.
   - Write `presentation.json` against `references/schemas/presentation.schema.json`.
   - Fix brief, approved copy, brand kit, inventory, gameplay scenes, compositions, licenses, provenance, output manifest.
   - Set `truth_type` to `concept`, `reconstructed`, or `runtime-captured`; set `proof_role` to `illustrative` or `runtime-proof`. Runtime proof requires runtime-captured truth and capture evidence.

3. Seal and resolve imported content.

```powershell
python "<skill-dir>/scripts/prepare_presentation.py" --presentation "<root>/presentation.json" --root "<root>"
```

`<skill-dir>` is the installed directory containing this file. Normal execution validates and seals the contract, verifies asset/font artifact, manifest and report pins, checks asset production-media declarations, and copies artifacts into `presentation/content-addressed/`.

`--validate-only` still writes prepared JSON; it skips file-pin verification, imports, and resolved JSON. Use the project's selected Python. Install from the absolute `requirements-runtime.txt` path only within authorized dependency setup.

4. Build only derived outputs.
   - Compose from the resolved store with the project's existing image, HTML/canvas, or design tooling.
   - Respect canvas, safe zone, layer order, asset list, licensed fonts, approved copy, and resampling rules.
   - Deterministic composition may arrange approved pixels. It must not invent missing character, prop, background, or UI art. Missing production media returns to the source producer or an available image tool within authorized scope. Keep its actual provider receipt and provenance; an external skill is not required.
   - Outputs under `presentation/outputs/`. Never overwrite source assets, manifests, reports, fonts, or licenses.

5. Capture and reconcile proof.
   - Inspect each output at delivery size: crop, readability, source fidelity, license/provenance coverage, truth label, hash.
   - Contact board proves layout only. Runtime-captured claims require hash-backed capture evidence; reconstructed and illustrative outputs keep truth labels visible in the contract.
   - Update presentation manifest and any runtime capture evidence. Revalidate before handing the artifacts and current report to a cross-family delivery, when requested.

## Completion Contract

Done: preparation exit 0; all imports hash-verified; every output belongs to a declared composition; licenses and provenance complete; truth labels honest; mockups inspected.

## Resources

- `scripts/prepare_presentation.py`: validation, sealing, and import CLI.
- `scripts/presentation_pipeline/`: contract and content-addressed preparation.
- `references/schemas/`: presentation, brief, composition, evidence, inventory, license, provenance, and manifest contracts.
