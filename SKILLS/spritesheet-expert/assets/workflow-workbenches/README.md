# Workflow workbenches

Each directory is a small, isolated production-and-review area for one motion
or asset workflow. A workbench owns its contract, candidate root, required
templates, gates, review artifacts, and promotion rule. It does not own or
silently approve another workbench's outputs.

`catalog.json` is the routing source of truth. Only entries with `status:
"active"` may generate new candidates. `blocked` entries can be prepared and
validated, but must not consume Image Gen calls until their dependency passes.

The first active workbench is `sideview-walk`. View transfer and the other
sprite families are intentionally present as test templates so their contracts
can be reviewed before generation, while remaining blocked from production.

The browser workbench under `scripts/motion-reference-review` is the shared
registration surface for these areas. It provides baseline, root-axis, thirds
and safe-bound guides; previous/next onion skin; reversible per-frame X/Y/scale
corrections; JSON transform import/export; and corrected-sheet PNG export. A
candidate remains unapproved while any contract gate fails, even if its visual
registration has been corrected.

The expanded editor also provides fit/zoom/pan, direct drag and scale handles,
center/baseline snapping, difference comparison, undo/redo, per-frame locks,
multi-selection, QA state and notes, hard gates, explicit identity/mechanics
reference slots, persistent non-destructive variants, and a correction queue.
Each Image Gen packet keeps five roles separate: identity, mechanics, previous,
target-to-edit and next. Jobs follow the workflow generation dependency order;
contracted frame order is intentionally not editable.

The canonical browser project is JSON v3 and uses IndexedDB for reference and
variant blobs when available. Export `alignment profile v2` alongside it when
the current Python correction scripts need the legacy transform schema.

Validate the complete structure with:

```powershell
python SKILLS\spritesheet-expert\scripts\check_workflow_workbenches.py
```
