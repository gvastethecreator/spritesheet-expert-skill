# Animation recipe

Use for any frame sequence: character cycles, actions, and effects.

## 1. Plan

```bash
python sprite.py plan --out runs/orc --subject "a hulking orc brawler with tusks and clawed boots" \
  --style "late-1990s low-poly 3D game model, hand-painted textures" --view "side view, facing right" \
  --anchor orc-anchor.png --cell 512x448 \
  --state idle:4 --state punch:6:attack:12
```

- `--state NAME:FRAMES[:MOTION[:FPS]]`. Built-in motions: `idle`, `walk`,
  `walk-quadruped`, `run`, `attack` (straight thrust), `attack-overhead`,
  `jump`, `hurt`, `cast`, `vfx`. Any other name works; the prompt then numbers
  the steps of that action.
- `--cell` is the runtime frame size. Make it wide enough for the widest pose.
  `--baseline` is the ground line as a fraction of cell height (default 0.9).
- `--view` decides the facing. "facing left" mirrors the pose guides.
- `--pose-guide mannequin` (default) or `openpose`. Every frame also gets an
  OpenPose JSON (`poses/<state>/NN.openpose.json`) for ControlNet pipelines.

`plan` writes, per state:

| File | Use |
| --- | --- |
| `prompts/<state>/NN.txt` | One prompt per frame for the chained route |
| `poses/<state>/NN.png` | Pose guide per frame (`idle`, `attack`, `attack-overhead` today) |
| `prompts/<state>.txt` + `guides/<state>.png` | One-sheet prompt for a fast draft |

## 2. Generate: chained frames (best)

Generate frames in order. For frame `k`, attach:

1. the anchor image;
2. frame `k-1` (skip for frame 1);
3. `poses/<state>/kk.png`.

Send `prompts/<state>/kk.txt` as the prompt. Each frame edits the previous
one, so textures and equipment stay the same and only the pose changes. Save
the frames as `01.png … NN.png` in one folder per state.

The one-sheet route (`prompts/<state>.txt` with the layout guide) is faster but
redraws every frame, so details flicker. Use it for drafts.

## 3. Build

```bash
python sprite.py build runs/orc --source punch=frames/punch/ --source idle=frames/idle/ --provider "chatgpt via Cozy Studio"
```

A folder is laid into the state's grid without changing pixels; a single image
is used as a sheet. Build is safe to run again; pass only the states you replace.

- Every grounded state of a run gets the same body size, so idle and attack match.
- Actions in place pin the feet; walk and run center the body; jump and VFX keep their motion.
- Frame durations follow the phase: anticipation and impact hold longer than the swing.

## 4. Review and check

Open `runs/orc/review.html`. Play each state at speed, step through it, use
onion skin and the four backgrounds, and read each check that is not `pass`.

```bash
python sprite.py check runs/orc --strict   # exit 1 while anything is open
```

| Check | Meaning when it is not `pass` | Fix |
| --- | --- | --- |
| `frames` | A cell had nothing in it | Regenerate the frame |
| `source-edge` | The subject touches the image edge | Regenerate with more margin |
| `scale` | A frame is drawn larger or smaller than its neighbors | Regenerate that frame from the previous one |
| `identity` | A frame's colors differ from the anchor | Regenerate that frame |
| `motion` | Frames repeat or barely change | Regenerate with clearer poses |
| `loop` | The last frame does not lead back to the first | Regenerate the last frame |
| `cell-edge` | A frame touches its runtime cell | Use a bigger `--cell` |
| `halo` | Matte color is left on edges | Ask for alpha or use `--cutout birefnet` |

Regenerate instead of patching pixels.
