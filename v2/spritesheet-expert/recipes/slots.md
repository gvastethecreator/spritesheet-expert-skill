# Slots recipe

Use for named cells that do not play in time: a character's poses and
gestures, icon and item sets, UI element states and stretchable panels.

## 1. Plan

```bash
python sprite.py plan --out runs/ui --lane slots --subject "a game UI kit for a cozy fighting game" \
  --style "soft stylized 3D, satin finish, calm saturation" --view "straight front view" --cell 256 \
  --notes "Pressed is darker and slightly lower; disabled is desaturated gray." \
  --set "icons:fill=heart,coin,gem,key" --set "button=normal,hover,pressed,disabled" --set "panel:nine=dialog"
```

`--set NAME[:FIT]=SLOT,SLOT,...` is repeatable. Keep slot names short; they
become the names in `atlas.json`. Put details in `--notes`.

| Fit | Use for | Build places each cell |
| --- | --- | --- |
| `ground` | Poses and gestures of one character | One scale for the set, feet on the baseline |
| `center` (default) | UI states of one element | One scale for the set, centered |
| `fill` | Icons, items, props | Each one scaled to fill its cell, centered |
| `nine` | Panels, windows, frames | Like `center`, plus nine-slice margins |

For a character, pass `--anchor` as in the animation lane. With two or more
sets, `plan` also writes `prompts/_all.txt` and `guides/_all.png` for one
sheet with every set: the best way to keep one light and one palette.

## 2. Generate, build, repair

Generate the sheet with the guide attached (and the anchor, if any), then:

```bash
python sprite.py build runs/ui --source all=sheet.png --provider "<name>"
python sprite.py repair runs/ui --state icons --frame 3
python sprite.py build runs/ui --patch icons:3=key.png --provider "<name>"
```

`repair` writes `repair/<set>/NN/` with the neighbor cells and a prompt to
redraw one cell in the same style.

## 3. Review and check

Open `review.html`. Step through each set; for `nine` sets, press
**Stretch** to see the panel at 2× width and 1.5× height with fixed corners.

| Check | Runs for | Meaning when it is not `pass` |
| --- | --- | --- |
| `scale` | `ground`, `center` | A cell is drawn larger or smaller than the others |
| `color`, `identity` | `ground` | A pose changes the character's colors or light |
| `stretch` | `nine` | No plain middle band; the panel will smear when stretched |
| `frames`, `source-edge`, `cell-edge`, `halo` | all | As in the animation lane |

`atlas.json` names every cell; `nine` cells carry
`nine_slice: {box, slice: [left, top, right, bottom]}` in cell pixels.
