# Motion reference templates

Five slots for approved Image Gen mannequin masters. Manifest marks a slot `needs-imagegen` until reviewed PNG, exact hash, and approval sidecar are promoted. Approved master: 8-frame `4x2` walk cycle. `prepare_sprite_run.py` derives 4- and 6-frame refs from protected phases; mirrors right-facing masters for left-facing rows. Never redraws anatomy procedurally.

Required master views:

- side right (left is mirrored);
- front;
- back;
- three-quarter front right (left is mirrored);
- three-quarter back right (left is mirrored).

Reusable after visual QA and manifest `status: "approved"` plus exact PNG `sha256`. Candidate or missing assets are ignored; run emits a generate-once prompt.

Generated attempts stay in a run/maintainer workspace outside the installed skill. Do not commit candidate dumps into the skill package. Monotonic filenames; never point a manifest asset at a candidate. Resolver consumes only approved hash-matching assets this manifest names.

Approval checks:

- exactly eight poses in a divisible `4x2` grid;
- contact/down/passing/up followed by the opposite four phases;
- opposite contact legs and cross-lateral arm swing;
- stable head, torso, pelvis, limb thickness, baseline, camera;
- anatomical colors stay attached to the same limb through every overlap;
- no labels, grid marks, scenery, shadows, clothing, style cues, cropping;
- frame 8 flows back to frame 1 without a pose or root-position pop.

