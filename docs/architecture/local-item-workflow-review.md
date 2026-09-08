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

## PR 3 integration and portable workspaces — 2026-09-05

The clean integration branch was fast-forwarded from `2b14c16` to PR 3 head
`55ef21e9299d67db72d843f1081b93e795419fa5` (19 commits). The PR's independent
delivery validator, draft/final boundary, native exporter, Delivery Lab and
production audit remain in place. PR 3 was not merged into `main`.

The workspace increment adds `sprite-workspace-v1` identity, a generated folder
guide, collections, archive/restore, disk-backed agent jobs, linked source
imports, validated run copying and persistent ZIP delivery records. Studio and
`manage_studio_workspace.py` share these operations and the existing runner.
Paths in the descriptor and artifact records remain relative. Runtime and
checkpoint configuration stay on the host. Switching workspaces rotates the
session token; an old tab cannot write to the newly opened project.

Review also found that the processing UI hid unflagged pending items and that
direct CLI replay could replace a reviewed head. The UI now lists all unapproved
items. Completed replay checks current evidence and preserves the reviewed head
without loading a model environment. Review and ZIP export honor the existing
run lock. This is not a claim that all approval invalidation or cross-process
transaction requirements in STUDIO-102/103 are complete.

Verification of this increment:

- `pnpm run check`: passed, including 732 tests (572.66 seconds), structural
  validators and the smoke pipeline. Five existing motion templates remain
  `needs-imagegen`; this static workspace change does not deliver those assets.
- The existing Chromium browser script now covers workspace creation/opening,
  stable job IDs across output formats, queue persistence, linked alpha imports,
  unflagged pending review, saved exports, collection edits, archive/restore,
  isolated workspaces and rejection of stale tokens at 1440 × 1000. It also
  retains the Delivery Lab hash/tamper checks. No JavaScript errors occurred.
  The static test server still logs a missing favicon; it is not a failed flow.
- Relocation tests copy workspace data and run the CLI from a separate skill
  script directory. Sources, IDs, collections, review heads, jobs and saved ZIP
  hashes survive; corrupt copies and archives fail closed. Opening a completed
  model-profile run is tested without an available model runtime.
- The three existing final model runs were copied into the dedicated local
  Black Flag workspace. Current manifests passed strict draft integrity checks.
  A real Studio pass opened their light/dark crop previews, kept final export
  disabled and saved three drafts (15,905,652 / 19,528,930 / 19,530,260 bytes).
  `workspace-validation/receipt.json` in that workspace records the exact run,
  manifest and archive hashes. Prior visual inspection evidence was copied into
  a separate `prior-validation/` folder and remains explicitly historical.

No Qwen/SAM inference was rerun for workspace management. No engine rendering
proof is claimed. All 159 stored proposals remain unapproved, with the pending
ownership and semantic issues recorded above. The old Atlas Lab still needs
verified artifact resolution, durable replacement editing and hash-bound
approval invalidation; the production backlog remains open.

This increment is local and uncommitted. Sources, weights, workspace data and
browser evidence are outside the published file set.

## Five audit improvements — 2026-09-07

The implementation adds five related changes without merging the workflow lanes:

1. Recoverable directory publication, exact browser artifact identities, captured
   asynchronous edit targets, and input-bound pixel/semantic/placement approvals.
   Replacements preserve their original bytes, retire old owned pixels explicitly,
   and produce a new source composition and successor ID. Review does not approve
   a replacement implicitly.
2. One lane registry and final-check dispatcher. Native alpha is the default for
   isolated stills. Static character variants no longer inherit animation loops,
   phase prompts or nonexistent accepted anchors. Imported sources and identity
   proxy metrics survive registration. The aggregate recognizes `2:1 isometric`.
3. Portable workspace snapshots for grids, animation and tilesets, with exact
   artifact hashes, evidence previews and draft ZIPs. Their existing processors
   remain authoritative. Optional Lucida/BEN2 dependencies now share the locked
   Python 3.12 CPU/NVIDIA runtime; checkpoint preparation is separate and verifies
   required shards before publishing its receipt.
4. Pre-allocation page budgets, deterministic largest-first shelves, page-aware
   review/validation/Studio, and an index of native JSON Hash export pages.
5. An executable grouped-pixel/label evaluator, external-image sample annotations,
   independent workflow evaluations, and named model/runtime measurements.

### Verification and observed failures

The full suite executed 739 cases: 729 initially passed. The ten failures exposed
lost slot labels during registration and outdated fixtures/assertions for the
new alpha, workflow and packing contracts. They were corrected, not waived.
The affected six files then ran 122 cases (including two new regressions): 121
passed; the remaining snapshot error-message case passed on its focused rerun.
This covers 741 distinct cases across the full run and focused closeout, not a
claim that a second full suite was run. Final diff review found two remaining
boundary defects: an explicit CLI lane could bypass semantic selection, and
review publication resolved its output symlink before checking it. These were
fixed. Single-frame effects now use the same temporal lane as the gate policy.
A final 21-case check passed, including three new regressions, bringing distinct
coverage to 744 cases. The environment doctor, skill/routing/
Studio validators and smoke pipeline passed. Five existing motion templates
remain `needs-imagegen` with `ready=false`.

One Chromium desktop viewport (1440 × 1000) covered current file hashes, stale
receipts, corrupt images, exact paths despite matching basenames, a replacement
delayed across selection changes, all three test atlas pages, workspace switching,
saved jobs, review/export, row-lane adoption/evidence/snapshot and archive/restore.
Canvas pixels matched the native crop on every test page. No JavaScript errors
occurred. The static diagnostic server's favicon and absent session endpoint
return 404; the full workspace path uses the Python service. Screenshots were
inspected; this is browser proof, not a game-engine test.

The independent evaluator ran six requests (41 commands), then rechecked the
failing static-grid, tileset and no-source pose-set cases (21 commands plus the
final prompt rerun). It found defects missed by structural validation. Static
and isometric technical gates now pass with complete fixture catalogs; visual
approval correctly remains pending (exit 2). It read the final static prompt
without the former timeline/anchor contradictions. Chronology rejection and the
pending-template boundary were also exercised. No provider artwork or human
approval was fabricated.

### Local models on the RTX 3090

An isolated Python 3.12.14 environment was installed from the NVIDIA lock with
Lucida and BEN2 extras (torch 2.10.0+cu128, transformers 4.57.6). Each inference
test blocked socket connections and used prepared snapshots.

| Check | Wall time | Peak allocated GPU memory | Scope |
| --- | ---: | ---: | --- |
| Lucida | 109.485 s | 1192.1 MiB | One neutral-composited church crop; strong-alpha IoU 0.989583 |
| BEN2 | 7.282 s | 2587.8 MiB | Same crop; strong-alpha IoU 0.993170 |
| Qwen + SAM, cold | 74.453 s | Qwen 8818.1 MiB; SAM 463.2 MiB | One full-sheet-context building region; one proposed object |
| Qwen proposal reused, SAM rerun | 0.859 s | SAM 525.9 MiB | Cached Qwen proposal, current SAM revision and new mask timing |

GPU memory is stage-scoped allocated memory, not total device occupancy.
Lucida/BEN2 process peak working sets were 2366.8/1580.7 MiB respectively.
Qwen revision: `ebb281ec70b05090aa6165b016eac8ec08e71b17`.
SAM revision: `ee5bba1d82bb8749febdf90f45e84b687142ba03`.
Lucida revision: `6ee11122534c8de59402a589d2293c198cfbf848`.
BEN2 revision: `e48a20765fb421d19dcdb0bf3cc61e802ca5ec8f`.
The doctor reports prepared standard/Lucida/BEN2 capabilities separately from
inference evidence. Light-profile weights are absent from this validation cache.
CPU and 2B inference were not measured in this increment.

### Three-sheet comparison

`evals/item-group-samples.json` identifies the original source hashes and 13
selected groups. Every selected crop was inspected on light and dark backgrounds;
annotation errors (neighbor fragments and clipped medallion edges) were corrected
before the final comparison. Annotations are agent-authored, not human ground
truth. IoU below uses alpha >= 64; weak-alpha ownership and all pending pixels
remain separately visible. Production pixels were not thresholded away.

| Sample | Groups | Exact strong-alpha groups, alpha/model | Mean IoU, alpha/model | Matching labels, alpha/prior model |
| --- | ---: | ---: | ---: | ---: |
| Gothic buildings | 4 | 3 / 3 | 0.999988 / 0.999988 | 0 / 4 |
| Gothic villagers | 5 | 4 / 4 | 0.999711 / 0.999711 | 0 / 5 |
| Raven heraldry | 4 | 4 / 4 | 1 / 1 | 0 / 1 |

Each source was rebuilt independently. Combined alpha/repacking time was
26.479/43.886/48.575 seconds respectively. The model comparison reuses historical
Qwen/SAM proposals and labels, rebuilt with the current bounded writer; it is
not three fresh full-sheet inference runs. Model-repacked sources still have
55,634 / 115,026 / 168,131 pending pixels. One selected villager group splits.
The small selected sample does not prove whole-sheet grouping, calibrated
confidence, artistic yield or better model segmentation. Human correction time
is null, not estimated. No new model/prompt is declared superior from these data.

### Evidence and remaining boundaries

Local evidence is under `.scratch/evals/2026-09-07/`: `tests.log`, `recheck.log`,
`final-paths.log`, `validate.log`, `smoke-recheck.log`, `browser-final.log`, `agent-forward/`,
`agent-forward-after/`, `representative-v3/comparison.json`, `model-lucida/`,
`model-ben2/`, and `qwen-cache/`. Browser captures are in
`.scratch/delivery-browser/`. Sources, weights, caches and these media remain
outside the published tree.

No target-engine rendering, full human-approved corpus, correction-cost benchmark,
paid generation, Linux process-crash test or power-loss simulation was performed.
The publication regression injects a failed rename and verifies restoration and
predecessor retention; it does not certify every crash boundary. Row snapshots
retain their own final gates. Browser review drafts still require explicit export.
The broader Studio backlog remains open where these five changes do not meet its
full acceptance conditions. No commit or push was made.
