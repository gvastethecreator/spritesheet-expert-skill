# Workflow workbenches

Each directory is an isolated production-and-review area for one motion or asset workflow. Owns contract, candidate root, required templates, gates, review artifacts, promotion rule. Does not own or silently approve another workbench's output.

`catalog.json` is the routing source of truth. Only entries with `status:
"active"` may generate new candidates. `blocked` entries can be prepared and validated; no Image Gen calls until their dependency passes. Candidate roots are workspace-relative destinations, not bundled sample art. Writable project copy before generation; never write new evidence into an installed skill directory.

First active workbench: `sideview-walk`. View transfer and other sprite families exist as test templates so contracts can be reviewed before generation, still blocked from production.

Browser workbench under `scripts/motion-reference-review` is the shared registration surface: baseline, root-axis, thirds and safe-bound guides; previous/next onion skin; reversible per-frame X/Y/scale corrections; JSON transform import/export; corrected-sheet PNG export. Candidate stays unapproved while any contract gate fails, even if visual registration is corrected.

Expanded editor: fit/zoom/pan, direct drag and scale handles, center/baseline snapping, difference comparison, undo/redo, per-frame locks, multi-selection, QA state and notes, hard gates, explicit identity/mechanics reference slots, persistent non-destructive variants, and a correction queue. Image Gen packet keeps five roles separate: identity, mechanics, previous, target-to-edit and next. Jobs follow workflow generation dependency order; contracted frame order is not editable.

Canonical browser project is JSON v3; IndexedDB for reference and variant blobs. Export `alignment profile v2` when Python correction scripts need the legacy transform schema.

Validate with:

```powershell
python SKILLS\spritesheet-expert\scripts\check_workflow_workbenches.py
```
