# Motion reference templates

This library stores approved Image Gen mannequin masters. Each master is an
8-frame `4x2` walk cycle. `prepare_sprite_run.py` derives 4- and 6-frame
references by selecting protected phases, and mirrors right-facing masters for
left-facing rows. It never redraws anatomy procedurally.

Required master views:

- side right (left is mirrored);
- front;
- back;
- three-quarter front right (left is mirrored);
- three-quarter back right (left is mirrored).

A template is reusable only when visual QA has passed and its manifest entry
has `status: "approved"` plus the exact PNG `sha256`. Candidate or missing
assets are ignored, causing the run to emit a generate-once prompt instead.

Generated attempts belong in an explicit run or maintainer workspace outside
the installed skill. The canonical repository keeps historical attempts under
`maintenance/motion-reference-candidates/`; Skills CLI packages do not copy
that corpus. Use monotonically numbered filenames and never point a manifest
asset at a candidate. The resolver consumes only approved, hash-matching
assets named by this manifest.

Approval checks:

- exactly eight poses in a divisible `4x2` grid;
- contact/down/passing/up followed by the opposite four phases;
- opposite contact legs and cross-lateral arm swing;
- stable head, torso, pelvis, limb thickness, baseline, and camera;
- anatomical colors stay attached to the same limb through every overlap;
- no labels, grid marks, scenery, shadows, clothing, style cues, or cropping;
- frame 8 flows back to frame 1 without a pose or root-position pop.
