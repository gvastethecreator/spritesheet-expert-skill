# Consolidated PR: local item segmentation and atlas workflow

Suggested title: `feat: consolidate portable local segmentation, atlas and Studio review`

## Change summary

Consolidate PR #1 (production-media contract markers) and PR #2 (Studio and deterministic item atlas). Keep their production provenance and regeneration boundaries. Add one local workflow shared by Studio and CLI.

The existing integration branch uses rewritten commits, not merge ancestry.
Its committed tree equals PR #2 (`eca52d6`) plus the six-skill marker repair
from PR #1 (`ae39e56`). Earlier cleanup commits remove internal docs and local
media from the public tree; this consolidation does not reintroduce them.

- Bundle Studio inside the published skill, with a loopback Python service.
- Preserve imported bytes and hashes. Compile exclusive masks against the original RGBA source. Keep every visible pixel owned, pending, or explicitly discarded.
- Use Qwen3-VL for visual groups and closed-taxonomy labels, and SAM2.1 for mask proposals. Keep model revisions, raw results and lineage.
- Pack consecutive rectangular shelves, ordered by cell area, maximum side, height and stable ID. Default quantum is 32; padding is 16 per side. No rotation or resampling.
- Review ambiguous results through source masks, merge, brush reassignment, explicit discard, tags and immutable successors. Labels never enter the exported atlas.
- Install locked Python 3.12 CPU/NVIDIA profiles with uv. Download checkpoints separately; the shared workflow uses pinned, offline checkpoints.
- Record stage status, cancellation, errors, output hashes and resume state. Unresolved runs can export only an explicit draft.

## Review order

1. `scripts/spritecore/item_sheet.py`: exact pixels, pending/discarded accounting and shelf geometry.
2. `scripts/spritecore/item_ownership.py` and `item_segmentation.py`: mask conflicts, source hashes and successor lineage.
3. `scripts/run_item_model_worker.py`: model validation and sequential Qwen/SAM memory use.
4. `scripts/run_item_atlas_workflow.py`: stage receipts, cancellation and resume.
5. `scripts/serve_item_studio.py` and `studio/local-workflow.js`: local API and actual review path.
6. Runtime lock, guidance and existing test additions.

Paths above are relative to `SKILLS/spritesheet-expert/`.

## Verification

- Existing suite: 674 tests passed in 137.67 seconds. The full `pnpm run check` also passed package, routing, Studio and smoke gates.
- After whole-group preservation, stable-ID collision and review-lineage fixes: 48 focused unit/integration/relocation tests passed in 31.32 seconds; Studio validation passed. Total collected tests are now 675. The unchanged broad suites were not repeated.
- Package, routing, Studio and skill-frontmatter checks passed. Smoke pipeline passed.
- RTX 3090: actual Qwen4B and SAM2 inference, not mocked output.
- Moved skill: rebuilt the NVIDIA environment with `UV_OFFLINE=1` and reused the cache. The current 65-package lock installed 40 selected packages in 1.79 seconds after cache preparation. No model weights were downloaded by setup.
- Actual inference from the moved skill passed with offline mode, local-only loading and unavailable HTTP/HTTPS proxy: Qwen4B, 40.078 seconds including load, 8790.6 MiB peak allocated. The same weights were reused.
- A real character/object taxonomy mismatch was rejected during villager classification. Coupled schema branches now constrain family and canonical type together. The exact failed crop passed real inference after the fix (36.032 seconds, 8704.2 MiB); its targeted regression test passed.
- Chromium, 1440 x 1000: import, processing, visible failure, review-required state, mask overlay, backgrounds, native light/dark crops, zoom, tag successor, keyboard traversal and draft download. A separate brush check reassigned the same source pixel in chronological order and verified the successor hash and pending count.
- Actual GPU cancellation stopped the owned process tree. Resume reused two completed model-job checkpoints. Changed implementation hashes require a fresh run; failed runs were kept as failed.
- The later inherited-label and merge-review fix passed its focused regression. Merging does not approve an asset; changed pixels keep inherited labels as suggestions requiring review.

## Real-sheet validation

Counts below are emitted proposals, not expected object counts. Automatic
processing and human approval are separate. Every result remains a review draft.
Local evidence lives under `.local/evidence/`; it is not part of this PR.

| Sheet | Run | Candidates | Atlas | Pending pixels | Automatic stages | Peak allocated GPU memory |
| --- | --- | ---: | --- | ---: | ---: | ---: |
| Heraldry | `cb35204262a84dc9a307ba13be85ca61` | 62 | 1728 x 2784 | 168131 | 1351.248 s | 8861.0 MiB |
| Villagers | `ac6ccc26d3fd4287b8d63d9b51095d78` | 81 | 1536 x 1696 | 115026 | 1726.593 s | 8774.9 MiB |
| Buildings | `c930ba450aba451b9349851681140cde` | 16 | 1408 x 2144 | 55634 | 475.545 s | 8883.4 MiB |

Times sum the recorded stages, including model loading, with prepared local
checkpoints. They exclude dependency installation, downloads and human review.
Memory is PyTorch peak allocated GPU memory, not whole-device VRAM or system
RAM. The host is an RTX 3090 with 24576 MiB. CPU inference and the selectable
Qwen 2B profile have not been exercised on this host.

All 62 heraldry crops were inspected at native resolution on light and dark
backgrounds. Assigned pixels had zero RGBA mismatches and zero duplicate
ownership. This does not mean the segmentation is semantically correct:

- One banner remains joined to a separate round shield.
- Conflicting masks produced partial flag outlines and damaged fittings.
- Some bird ornaments were labeled as characters; a few tags invented a
  franchise association or copied unrelated taxonomy terms.
- Model confidence did not predict these errors. None of these items was
  approved by the visual inspection or by the browser tag-edit test.

The initial villager classifier rejected a real invalid family/type pair after
45 jobs. The fresh run completed all 81 classifications with the corrected
coupled schema and passed the Studio review/tag/draft-download path. All 81
final crops and labels were inspected on both backgrounds. Assigned pixels had
zero RGBA mismatches and zero duplicate ownership. A detached barrel,
censer/smoke and small residue still require review; they are not silently
discarded or counted as accepted independent objects. One character was labeled
as its lantern, and some figures received overly broad or inconsistent roles.

All 16 building crops were inspected at native resolution on both backgrounds,
then their final labels were checked against those crops. The windmill, forge,
hospital and watchtower retain much more complete groups than the earlier
draft. However, one proposal joins the stable and lighthouse through a source
connection, and one tiny fragment remains ambiguous. A courthouse was labeled
as a house with an unsupported `gargoyle` subtype; another utility building was
labeled as a workshop without enough evidence. All 16 proposals remain flagged.
Assigned pixels had zero RGBA mismatches and zero duplicate ownership. The
Studio review/tag/draft-download path passed without captured UI errors.

In total, 159 final emitted crops were inspected. This is not 159 accepted
assets. Pixel-exact output, exclusive masks and valid taxonomy are useful
mechanical guarantees; grouping and semantic labeling still need correction.
The final-delivery gate remains blocked by unresolved pixels and review flags.

### Local evidence index

- `heraldry-final/visual/receipt.json`, `villagers-validated/visual/receipt.json`,
  and `buildings-validated/visual/receipt.json`: metrics and pixel accounting.
- Each corresponding `visual-review.md` and `visual/crops-*.png`: observed
  geometry and label issues, with native light/dark inspection pages.
- `*-studio-proof.json` and `*-studio-draft.zip`: the three completed UI paths.
- `final-studio-review-proof.json`: chronological brush assignment, keyboard
  traversal, labels and native preview checks.
- `relocation-offline/results.jsonl`: real inference from the moved skill.
- `classification-regression/results.jsonl`: the exact rejected-crop rerun.
- `studio-screenshots/`: retained desktop browser captures.

The last changes after the focused checks were documentation and the saved-run
label prefix. No broad test suite or extra viewport was rerun for those changes.
`git diff --check` passed. The three original sources and all model weights
remain outside the published file set.

## Model limits observed during validation

The first building inventory omitted a watchtower and left gaps in the lighthouse terrain. Its 15 emitted candidates retained 888444 source pixels; 107357 remained pending. No emitted RGBA mismatches or duplicate ownership were found. This is diagnostic history, not the final validation or an approved atlas. A later 23-candidate run over-split the windmill; it prompted whole-group preservation and a stronger building-context instruction.

The dense villager sheet exposed two prompt failures: zero objects when context strips were interpreted as duplicates, then one whole-sheet group despite a claimed count of 100. Both outputs stayed failed or review-required. Alpha-region hints were added as proposals, not as reference counts.

Confidence is not a correctness score. Pixel accounting is not semantic validation. These cases must remain visible, and final export must stay blocked until they are resolved.

## Publication boundary

Source images, model weights, virtual environments, local runs and screenshots remain ignored under `.local` or `.scratch`. Do not publish these production inputs. No PR, push or commit has been performed by this implementation turn. Human review and commit consent remain required.
