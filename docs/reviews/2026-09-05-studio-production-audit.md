# Spritesheet Expert — production-readiness audit

Date: 2026-09-05. Scope: user-requested integration branch, portable agent-first Studio, usable spritesheets, mid-pipeline editing, quality and end-to-end delivery. This is a code/contract audit plus targeted implementation and regression tests, not a claim that real generated art has passed a production benchmark.

## Branch and review identity

The supplied URL referred to `feat/integrate-studio-item-atlas-contracts`, initially at `2b14c16b01088608fe361690e9e2be3ea6bb2174`. The already open PR #2 used a different head: `feat/agent-studio-deterministic-item-atlas`, at `eca52d632ec9a9b717f31fbcf3a5ed22467c3254`. Both derive from `df70c6955e7c0d6a99bef5e1f3d02e903f92c4c4` and have divergent changes.

PR #3 reviews the integration branch explicitly requested by the user. It preserves its local-model runtime, source-pixel ownership editor and resumable CLI rather than resetting it to the older PR. PR #2 is historical context, not silently merged, closed or force-updated. No merge into main is authorized or performed by this audit.

## Executive finding

The project is not merely a prompt wrapper or a mock Studio. It has a meaningful deterministic core and useful review tools. Its largest weakness is that **different components use different definitions of ready**. A successful model call, absence of QA flags, a pending review, a valid atlas and an engine-ready asset are not interchangeable.

The safest improvement is an independent delivery gate over the actual current bytes, combined with clear lane routing and explicit visual approval. That gate is implemented in this revision. It does not by itself solve all source-intake, browser review, replacement, state-management and real-art evaluation gaps below. Keep the integration PR draft until the release-critical follow-ups are resolved.

## Inspected surfaces

| Surface | Files/functions examined | Main question |
| --- | --- | --- |
| Skill orchestration | `SKILLS/spritesheet-expert/SKILL.md`, production/provenance routing, supporting static/UI skills | Does the agent choose and complete the right asset lane? |
| Deterministic compiler | `scripts/spritecore/item_sheet.py`, especially extraction, packing and `write_item_atlas_run` | Are source pixels, crops, cells and manifests consistent? |
| Local model analysis | `scripts/run_item_model_worker.py`, result normalizers, Qwen/SAM loaders and checkpoints | Are masks/classes evidence, or wrongly treated as ground truth? |
| Workflow state | `scripts/run_item_atlas_workflow.py` | Does resume preserve the current reviewed successor? |
| Editing | `scripts/spritecore/item_ownership.py`, `compile_masks`, `apply_ownership_review` | Does every content-changing edit invalidate the right approval? |
| Local API | `scripts/serve_item_studio.py`, `snapshot`, `start`, `review`, export | Can an unreviewed or stale bundle be delivered? |
| Browser processing | `studio/local-workflow.js` | Are unresolved states and unsaved changes accurately represented? |
| Portable review | `studio/app.js`, path index, review documents, asynchronous replacements, handoff generation | Is the inspected image the same artifact being approved? |
| Package validation | `scripts/validate-studio.mjs`, `package.json`, `.github/workflows/ci.yml` | Do checks exercise behavior, or only marker presence? |

Paths in the remainder of this document are relative to `SKILLS/spritesheet-expert` unless otherwise stated. Findings refer to the baseline above; the status column distinguishes changes made during this audit.

## Strong foundations to retain

Native RGBA source evidence, source bounds, stable content fingerprints and explicit pixel ownership are the right foundation. The compiler does not need a vision model to invent atlas geometry. Its pending and discarded masks make unresolved work visible. Classification is a separate proposal layer. Review operations carry a parent manifest hash and create successor artifacts. The app is local-first and the model runtime is optional. Provider execution is deliberately separate from deterministic scripts and tests. The earlier animation pipeline already has useful motion, identity, chronological selection and playback gates; replacing it with a static item atlas would be a regression.

## Findings and disposition

### F01 — final export accepted unflagged pending items [P0; fixed at delivery boundary]

Evidence: baseline server `snapshot()` counted `bool(item.qaFlags) and status != approved`; POST export checked only that count and pending pixels. A clean-looking item with `review.status: pending` could therefore pass final export. Compiler completion flags also mixed absence of flags with completed review.

Reproduction: compile a normal transparent item with no flags, retain pending review, then request final export. Expected: blocked until explicit review. This revision counts all non-approved items, validates the actual bundle again in `Studio.export`, and refuses every unresolved final item. Draft relaxes review only, never integrity. Legacy completion booleans are not authoritative and still need schema/state cleanup (STUDIO-102).

### F02 — metadata could be trusted without a full pixel-level recheck [P0; independent gate implemented]

Evidence: the baseline ZIP path collected files after shallow snapshot checks. A later-modified crop or atlas could be bundled without independently proving source/crop/frame equivalence and ownership.

Implemented: `spritecore/item_delivery.py` checks exact paths, hashes, actual dimensions/modes, crop content fingerprints, native scale, no rotation, finite pivots, frame/cell containment, padding/quantum alignment, cell overlap, exact atlas crop pixels, source pixel preservation, transparent atlas gutters and source ownership partition. It verifies binary pending/discard masks against current source pixels instead of trusting counters. Source-edge contact and fixture provenance cannot be approved into a final production delivery.

Export copies rechecked critical bytes under the server mutation lock; it rejects symlink artifacts, bounds archive input size and emits the matching receipt. This is not a cryptographic signature or a global cross-process transaction. External mutation and multi-process coordination still require STUDIO-103.

### F03 — portable viewer could display the wrong file for an approval [P0; legacy path remains open]

Evidence: `studio/app.js::indexRunFiles` registers basename aliases; `resolveRunFile` falls back to a suffix match; loading another manifest does not create a fully verified artifact set. Two folders may both contain `atlas.png` or the same crop filename, but only one set matches the current manifest.

Implemented mitigation: the new Delivery Lab resolves only exact manifest-relative paths and verifies original source/atlas/item byte hashes before rendering. It blocks missing and stale artifacts.

Not claimed fixed: the old portable Atlas Lab review implementation. Production approval must not rely on an unverified legacy thumbnail. STUDIO-101 must bind all writable views to the same verified resolver, not merely add another visual warning.

### F04 — asynchronous replacement may attach to a changed selection [P0; open]

Evidence: the replacement file handler awaits hashing and subsequently uses mutable `state.selectedItemId`. A user can select another item while hashing. A filename-only review reference also does not transport the actual replacement bytes.

Required: capture item ID, manifest hash and session revision before awaiting; commit only if they still match; bundle exact candidate bytes under collision-free paths; show before/after at identical scale. STUDIO-101 and STUDIO-106 include regression cases. Do not describe “replacement request prepared” as “replacement applied.”

### F05 — resume can reset the reviewed active manifest [P0; server path fixed, direct CLI open]

Evidence: the CLI workflow rebuilds the active manifest pointer from processing outputs when replaying cached stages. That can supersede a later manual review head. Baseline server start allowed that replay.

Implemented: server start on `processingComplete` returns `already-complete` without spawning a process or changing the review head. Open: direct CLI replay and explicit changed-input branches must preserve review lineage and require a new processing revision. See STUDIO-102.

### F06 — approvals can survive material edits [P0; open]

Evidence: `compile_masks` can retain old review metadata while pixels change through ownership resolution; some explicit paint operations invalidate review, but the invariant is not universal. Tag/classification editing does not consistently invalidate the corresponding semantic acceptance. The final gate verifies current pixels but cannot establish what a person actually saw if the approval itself was inherited incorrectly.

Required: hash-bound, scoped acceptance: source/crop/visual brief, taxonomy/classification, geometry and engine proof each have explicit dependencies. Changed inputs clear only the affected decision and downstream proofs. STUDIO-102 is a release blocker, not optional polish.

### F07 — forced rewrites and independent processes risk losing prior work [P0; partly mitigated]

Evidence: forced compiler output replacement removes the old directory before replacing it with staging. A failure between deletion and rename loses the last valid artifact set. An in-process server lock does not coordinate direct CLI access.

Implemented: the new runtime exporter has no force mode, writes to a new unrelated directory and publishes staged output without deleting a prior delivery. Open: shared run transaction/lock/recovery across existing writers. STUDIO-103 requires failure injection and Windows coverage.

### F08 — masks/components do not establish semantic object correctness [P1; workflow clarified]

Disconnected handles, straps and spark fragments can belong to one item; touching objects can form one connected component. Weak-alpha ownership ties must not become confident semantics. Qwen classification and SAM mask proposals do not validate camera, style, complete anatomy or correct category count.

Preserve unresolved pixels, expose source overlays and support merge/split/assign/discard decisions. Separate mask quality, taxonomy validity and human visual acceptance. Do not replace the whole tool with a larger model before collecting error cases and correction-time measurements. STUDIO-107 and STUDIO-111.

### F09 — input and resource policies are not shared across lanes [P1; open]

Browser intake and CLI/compiler paths do not have one canonical decoder/alpha policy. Fully transparent images, opaque input, palette transparency, animated containers, declared extensions and actual formats need consistent outcomes. The delivery gate now rejects corrupt or inconsistent results, but that happens after processing.

Packing also needs pre-allocation limits for width, height, pages, total pixels and memory, not only a width option or a post-build validator. A giant source must not silently force rescaling or create an oversized texture. STUDIO-104 and STUDIO-109.

### F10 — local editing has incomplete durable-draft and interaction guarantees [P1; open]

Evidence: polling can clear brush state on a changed manifest; edits and selection are held in browser variables; “doubts” filters only QA flags rather than all unapproved items. Brush points are not interpolated into continuous lines. Duplicate IDs in merge/discard operations and nondeterministic set-to-list flag ordering need normalization.

A usable mid-pipeline editor needs explicit dirty-state handling, durable undo/redo and selected-revision binding, not merely more buttons. STUDIO-105 and STUDIO-106.

### F11 — handoff preparation needs typed arguments and stable identity [P0/P1; open]

Evidence: launcher templates interpolate raw form text into command strings; required/min/max constraints are not consistently enforced before copy/queue; `makeJob` creates new IDs when rerendering output. No command is executed by this browser, but the generated handoff is an execution trust boundary.

Required: validate fields, distinguish display text from structured argv, quote per target shell only for presentation, preserve one prepared job ID, and maintain explicit accepted/rejected delivery counts. STUDIO-108. A global ban on all grids would break valid animation workflows; quota policy belongs to the selected project/lane.

### F12 — model caching/provenance needs stage separation [P1; open]

Evidence: the Qwen checkpoint cache key includes job/model/revision/worker/tokens/device but not the mask-model selection, while cached result metadata includes mask revision. SAM refinement is a later stage and can rerun after cached Qwen work. Peak-memory reporting also needs a clearly reset measurement window.

Required: independently version semantic proposal, mask refinement and classification stages; bind their checkpoint revisions and hashes; make cold/warm/cache-invalidated work visible. Do not publish RTX 3090 performance or VRAM promises without an actual run. STUDIO-107.

### F13 — an atlas is not an engine integration [P1; static format adapter implemented]

Implemented: `export_item_atlas.py` emits TexturePacker-style JSON Hash using actual `geometry.frame` and stable item IDs. It preserves native crop size and normalized pivots and explicitly declares no animation/engine smoke. Two identical-input exports are covered by byte-identical regression tests.

Still required: actual target loader test, device texture limits, origin behavior, filtering/bleed behavior, multi-page policy and separate Godot adapter where requested. World footprint and collision geometry cannot be derived from a rectangular pack cell. STUDIO-109 and STUDIO-110.

### F14 — quality evaluation is missing representative evidence [P1; specification added]

Synthetic fixtures prove pixel/accounting and failure handling, not artistic quality, segmentation usefulness or improved generation yield. A representative corpus needs approved object masks, expected classes and visual acceptance, including difficult failures rather than only clean demo sheets. Report accepted yield, native-size consistency and time to correct; use held-out cases. STUDIO-111.

### F15 — CI marker drift stopped tests before execution [P1; fixed]

Observed GitHub Actions run `33948326199` failed on both Ubuntu and Windows at skill validation because `build-static-game-assets` and `build-game-ui-kits` omitted the required `BiRefNet/BEN2` contract marker. Setup and installation had succeeded; pytest never ran in that run.

Restored the explicit reviewed model-comparison sentence while preserving native-alpha-first rules. Did not remove the validator or weaken production-media boundaries. Added an independent real-Chromium Delivery Lab smoke job. Consult the final PR checks for the current head: older failed or cancelled runs are not evidence that the final revision passed.

## Implementation added in this revision

| Addition/change | Practical result | Deliberate limit |
| --- | --- | --- |
| `spritecore/item_delivery.py` + `validate_item_delivery.py` | Fail-closed current-byte gate and JSON receipt; exits 0/2/3 | Not visual judgment, signed approval or engine execution |
| `export_item_atlas.py` | Immutable native static JSON Hash runtime bundle | Not animation/Godot/multi-page export |
| `serve_item_studio.py` | Strict final and draft checks; all-item review count; completed-start protection | Direct CLI/shared transaction work remains |
| `studio/delivery-lab.html` + `.js` | Exact-hash atlas/source/placement/evidence views | Read-only; legacy writable viewer not automatically fixed |
| `tests/unit/test_item_delivery.py` | 45 deterministic adversarial/export cases | Synthetic geometry, not representative art |
| `tests/unit/test_item_delivery_server.py` | Real compiler/ownership/server integration cases | No GPU/provider |
| `tests/browser/check_delivery_lab.py` + CI job | Actual browser workflow and tamper/stale-receipt rejection | Not a game engine or exhaustive cross-browser suite |
| Core skill and production reference | Lane routing, style lock, quota discipline, rejection/repair loops and honest completion | Agent-authored brief/ledger guidance, not an invented universal parser |

## Validation record and honesty boundaries

The audit container had a partial source workspace because repository network materialization was unavailable; GitHub connector reads and writes were available. The independent delivery/export unit suite executed locally with **45 passing tests**. JavaScript syntax and server compilation checks passed. Full-backend integration is covered by the newly committed tests and the repository CI, not claimed to have run in the partial local workspace.

The local browser environment blocked loopback navigation with `ERR_BLOCKED_BY_ADMINISTRATOR`; that policy was not bypassed. Static HTML layout was rendered and inspected, but that alone does not prove the interactive flow. The added GitHub Actions Chromium job exercises the real flow in its own permitted environment. Record its observed final status in the PR summary.

No Qwen/SAM inference, production image generation, GPU performance benchmark or Phaser/Godot runtime smoke was executed as part of the local audit. Existing source files were inspected; visual art-quality claims remain unproven until the representative evaluation and actual engine tests are run.

## Release acceptance

Do not merge on a nice screenshot alone. Minimum closure: current full CI and browser checks; STUDIO-101/102/103 trust/state blockers; a complete imported real-sheet workflow with all-item review and matching delivery evidence; one requested engine loader smoke; a rejected generation/replacement scenario that cannot increment accepted quota or overwrite a valid asset. Expand to animation and tilesets using their existing lane-specific gates rather than pretending the static-item tests cover them.

Follow-up tickets and dependency order: [studio-production-backlog.md](../architecture/studio-production-backlog.md). Operator/agent workflow: [production-workflow.md](../../SKILLS/spritesheet-expert/references/production-workflow.md).
