# `sideview-walk` acceptance contract

Status: **in progress**. Approved template: **none**.

## Eight-phase order

| Frame | Phase | Hard requirement |
|---:|---|---|
| 1 | left contact | Left/orange leg forward, right/green leg back; right/blue arm forward; both feet may contact. |
| 2 | left down | Weight settles over the leading left foot; trailing right toe remains in contact. |
| 3 | left passing | Right/green leg passes the planted left leg; pelvis rises toward neutral. |
| 4 | left up | Body reaches the high point; right leg prepares the opposite contact. |
| 5 | right contact | Exact support-side complement of frame 1. |
| 6 | right down | Exact support-side complement of frame 2. |
| 7 | right passing | Exact support-side complement of frame 3. |
| 8 | right up | Exact support-side complement of frame 4 and a clean lead-in to frame 1. |

## Hard invariants

- Exactly eight isolated poses in a `4x2`, row-major grid.
- At least one foot remains grounded in every frame; there is no flight phase.
- Arms counter-swing against the legs, with anatomical colors attached to the
  same limb in every overlap.
- Head, torso, pelvis, limb thickness, camera, scale, and horizontal root stay
  stable; only the expected vertical walk-cycle bob is allowed.
- No duplicated pose, high-knee march, running lean, cropping, text, grid line,
  scenery, shadow, gradient, or 3D rendering.
- Playback at the declared FPS reads as one continuous walk, and frame 8 flows
  back to frame 1 without a pop.

## Candidate log

| Candidate | Style | Mechanics | Decision |
|---|---|---|---|
| 001 3D | Too rendered and visually noisy | Repeated/high-knee progression | Rejected |
| 002 minimalist 2D | Passes the intended simple illustrated direction | Phase order, support continuity, and counter-swing are inconsistent | Rejected |
| 003 bilateral-pair sheet | Minimal style and clearer limbs | Root, scale, baseline, anatomy, and phase continuity drift between slots | Rejected |
| 004 isolated capsule mannequin | Every frame generated/edited separately; baseline can be registered | Cutout construction reads rigid, pass symmetry drifts, and repeated edits alter scale | Rejected |
| 005 organic isolated mannequin | Continuous illustrated anatomy removes the rigid capsule/circular-joint look | Opposite phases largely preserve the same silhouette and simulate alternation by recoloring limbs instead of moving them | Rejected |
| 006 articulated + mechanics controls | Organic Image Gen frames plus separate mechanics controls for failing passes/inbetweens | Six contacts/pass phases, permanent-color trajectories, foot clearance, head scale and root drift pass the mechanical checker | Mechanical checker and HTML playback pass; real-character transfer rejected |
| 006 real-character transfer | Six separate Image Gen renders in dependency order, using the accepted mannequin poses and a fixed courier identity | Identity is broadly stable and passing poses exist, but 1/2/4/5 collapse toward a generic stride, arm counter-swing fails, scale drifts, and frame 1 adds a ground line | Rejected; never promote to template |
| 007 QA-marked character transfer | Permanent wrist and shoe markers plus isolated Image Gen corrections for frames 2 and 5 | Counter-swing and intermediate arms improve; frame 5 needs reversible scale registration and frame 6 remains a high-knee pass against frame 3 | Candidate retained in the editor; blocked, not approved |

Candidate 005 proved that organic rendering alone is insufficient: fixed limb
colors are not motion evidence when the generator can repaint nearly frozen
geometry. Candidate 006 must preserve color identity and show a material
color-independent silhouette change between key poses before a frame can feed
the next generation.

## Six-frame isolated experiment

The current experiment generates one square frame at a time and uses this
reference dependency graph exactly:

```text
1 -> 6
1 + 6 -> 4
1 + 4 -> 2
2 + 4 -> 3
4 + 6 -> 5
```

The six runtime phases are left contact, left down, left pass/up, right
contact, right down, and right pass/up. Every edit must preserve the accepted
canvas, mannequin construction, anatomical colors, root x, baseline, scale,
and line weight. A frame is not allowed to become an input to another frame
until it passes its individual review.

## Review playback

Serve the repository root and open
`SKILLS/spritesheet-expert/scripts/motion-reference-review/index.html`. The
default sheet is candidate 006; a different candidate can be supplied with the
`sheet`, `columns`, `rows`, and `fps` query parameters. The viewer is a
non-destructive editor. It can register, compare, annotate, lock, replace and
export frames, but it never changes candidate or approval status; only the
versioned QA verdict can do that.

## Current pilot verdict

The mechanics master is the first candidate to pass both the colored-limb
checker and strict-order HTML playback at 8 FPS. That does **not** approve the
workflow. Its first real-character transfer failed contact-sheet review, which
proves that identity/style preservation and motion preservation must be
separate gates. The rejected transfer, registration report, and explicit QA
verdict are retained as a negative fixture.
