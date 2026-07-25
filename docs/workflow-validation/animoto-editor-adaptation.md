# Animoto editor adaptation

## Scope

`D:\DEV\animoto` was inspected as a reference product, not as a dependency.
The review covered its running interface and the implementations of
`MainViewer`, `TransformGizmo`, `Timeline`, `FrameAlignmentModal`,
`FrameCorrectionModal`, project persistence and keyboard shortcuts.

## Capabilities adopted

| Animoto pattern | Sprite workbench adaptation | Reason |
|---|---|---|
| Zoom, fit and pan in the main viewer | 25-400% zoom, automatic fit, wheel zoom and Space/middle-button pan | Inspect pixels and silhouettes without losing the complete frame |
| Direct transform gizmo | Drag the current raster plus a visible scale handle | Correct registration where the error is seen instead of only through numeric fields |
| Center snapping guides | Optional center and registered-baseline snap with live blue guides | Prevent almost-aligned frames from accumulating small root or foot drift |
| Onion-skin light table | Previous/next onion skin plus a difference blend mode | Separate motion changes from background and registration changes |
| Timeline frame state | Per-frame lock, `review/pass/fail`, multi-selection and queue badges | Protect accepted frames, batch triage and keep blockers visible without changing phase order |
| Undo/redo history | In-memory history for transforms, gates, QA, variants and correction jobs | Make experimentation reversible |
| Explicit reference tray | Separate identity, mechanics, previous and next slots | Prevent one ambiguous composite from hiding which reference controls identity or motion |
| Contextual frame correction | Five-role context board plus target PNG and correction JSON | Give Image Gen identity, mechanics and the exact temporal neighborhood as inspectable inputs |
| Non-destructive variants | Every returned frame is retained as a named variant with one active choice | Compare or reject a generated return without overwriting the source candidate |
| Project persistence | Canonical project JSON v3, local project index and IndexedDB-backed reference/variant blobs | Resume a review while keeping raster assets out of oversized localStorage payloads |
| Contract gates and correction queue | Hard gates per frame plus jobs sorted `1 → 6 → 4 → 2 → 3 → 5` | Keep manual triage separate from promotion and preserve generation dependencies |

## Project contract

The durable root is `kind: sprite-animation-editor-project`, version 3. It
contains the animation contract, source grid, transforms, frame metadata,
hard-gate assessments, reference-slot metadata, immutable variant metadata and
correction jobs. The active six-frame contract fixes both phase order and the
generation dependency graph:

```text
F1 → F6(1) → F4(1,6) → F2(1,4) → F3(2,4) → F5(4,6)
```

Selection, zoom, pan, playback and the transform clipboard remain session UI.
The exported v3 file records the selected-frame snapshot for handoff, but a
reload starts at F1 rather than restoring a stale UI selection.

Binary references and frame variants are stored in IndexedDB when available.
Project JSON deliberately stores their keys and provenance, not base64 data.
The separate `alignment profile v2` export preserves compatibility with the
existing Python scripts.

`Usar templates versionados` binds the checked-in character identity anchor
and all six articulated mannequin frames directly from the workbench. The
mechanics role follows the selected target frame rather than sending one generic
pose or regenerating references. Custom uploads can still replace either role.

## Quality behavior

- `review/pass/fail` is frame triage; it never completes hard gates.
- Opposite contacts, passing-foot clearance, arm counter-swing, root lock,
  scale lock, clean background, loop seam and identity transfer are assessed
  separately for every frame, matching the active workbench contract.
- Changing registration or the active variant turns prior passing assessments
  into `stale`, and prepared jobs become stale as needed.
- Replacing identity or mechanics references invalidates open correction jobs.
- A returned raster creates a variant. Accepting it resolves its correction
  job but does not bypass the gates or hash-bound CLI review.
- Multi-selection applies triage or prepares jobs only. The timeline exposes
  no insert, remove, move or reorder action.

## Deliberately deferred

- Arbitrary compositing layers are not part of the motion-reference gate. The
  current editor manipulates a complete frame so body parts cannot be silently
  detached or reordered.
- Frame insertion, deletion and free reordering are disabled for contracted
  cycles because phase count and order are hard invariants.
- AI calls remain outside the browser editor. The exported correction packet
  is consumed by the controlled one-frame-per-ImageGen-call workflow.
- Video, GIF and MP4 export are not evidence for sprite correctness; the
  corrected PNG sheet and project JSON remain the durable artifacts.

## Browser proof

The editor was reloaded from the local HTTP workbench with the six-frame
candidate and no console errors. The browser exercise selected F1, F4 and F6,
applied batch QA without changing gates, and prepared jobs in contractual order
F1, F6, F4. Because identity and mechanics had not been supplied, every job
correctly remained blocked. A separate exercise marked one gate passing,
changed frame registration and observed that gate immediately become `stale`.
Undo restored the fixture. Static editor-contract tests also assert the
required project, reference, gate, queue, variant and export surfaces and the
absence of timeline mutation actions.

This proof covers the editor mechanics, not motion approval. Candidate 007
remains rejected until its visual defect is corrected and the hash-bound review
passes.
