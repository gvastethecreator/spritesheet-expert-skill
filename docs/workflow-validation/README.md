# Motion workflow validation

Motion-reference templates are stabilized one workflow at a time. Work starts
with `sideview-walk`; later workflows remain blocked until the current one is
approved.

The browser editor and the capability decisions adapted from Animoto are
documented in [`animoto-editor-adaptation.md`](animoto-editor-adaptation.md).

## Order

1. `sideview-walk`
2. `sideview-run`
3. `topdown-locomotion`
4. `idle-breath`
5. `fighting-stance-idle`
6. `responsive-jump`
7. `quick-strike`
8. `power-strike`
9. `topdown-weapon-attack`
10. `hit-reaction-knockdown`
11. `run-gun-layered-motion`
12. `pickup-feedback`
13. `tiny-motion`
14. `vfx-buildup-peak-decay`
15. `water-loop`
16. `wind-ambient-loop`

## Promotion gate

A workflow advances only after all of these artifacts agree:

1. an authoritative phase contract and expected timing;
2. a numbered Image Gen mannequin candidate;
3. frame-by-frame static review;
4. strict-order HTML playback, including the loop seam;
5. a real-character transfer using the accepted mechanics;
6. browser proof with no console or resource errors;
7. an approval sidecar bound to the exact PNG SHA-256.

Style quality cannot override a motion failure. A candidate with the right look
but incorrect contact, support, silhouette, order, or seam is rejected.
