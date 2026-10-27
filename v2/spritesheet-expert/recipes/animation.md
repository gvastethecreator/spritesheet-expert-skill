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

`plan` writes:

| File | Use |
| --- | --- |
| `prompts/_all.txt` + `guides/_all.png` | One sheet for all states, one row per state (runs with 2+ states) |
| `prompts/<state>.txt` + `guides/<state>.png` | One sheet for one state |
| `poses/<state>/NN.png` | Pose guide per frame (`idle`, `attack`, `attack-overhead` today), also used by `repair` |
| `prompts/<state>/NN.txt` | One prompt per frame, for a frame you must draw alone |

## 2. Generate: one sheet, then repair

1. Generate `prompts/_all.txt` with the anchor and `guides/_all.png` attached.
   Ask for two candidates and keep the better one. All frames of all states
   are drawn together, so color, light, size and motion match.
2. Build it (step 3) and open `review.html`.
3. For each frame that is wrong (bad pose, broken detail, flagged check):

   ```bash
   python sprite.py repair runs/orc --state punch --frame 4
   ```

   This writes `repair/punch/04/` with the built neighbor frames, the pose
   guide and `prompt.txt`. Generate the in-between with those images attached,
   then rebuild with `--patch punch:4=<image>`. The patch is scaled to the
   body size of its neighbors.

Repair few frames. When more than a third of a row is wrong, regenerate the sheet.

When a row has many frames and they come out small, generate each state alone
(`prompts/<state>.txt` + `guides/<state>.png`): about 25% more pixels per frame
for a 6-frame row. The `match` check then compares each state's color and light
with the first one.

## 3. Build

```bash
python sprite.py build runs/orc --source all=sheet.png --provider "chatgpt via Cozy Studio"
python sprite.py build runs/orc --patch punch:4=punch-04.png --provider "chatgpt via Cozy Studio"
```

`all=` splits a combined sheet into one row per state. `--source punch=IMAGE`
takes a one-state sheet, `--source punch=FOLDER/` takes `01.png … NN.png`.
Build is safe to run again; pass only what you replace.

- Every grounded state of a run gets the same body size, so idle and attack match.
- With pose guides, each frame is rescaled to the body height its pose asks for
  (within ±25%), so a frame drawn too large or small comes back to size.
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
| `frames` | A cell had nothing in it | `repair` that frame |
| `source-edge` | The subject touches the image edge | Regenerate with more margin |
| `scale` | A frame is drawn more than 6% larger or smaller than the row (build already evens out smaller drift) | `repair` that frame |
| `size` | A frame needed the maximum size correction | `repair` that frame |
| `match` | A state's color or light differs from the first state | Regenerate it with the first state's frames attached |
| `identity` | A frame's colors differ from the anchor | `repair` that frame |
| `color` | A frame's color or light differs from its row | `repair` that frame |
| `motion` | Frames repeat or barely change | Regenerate the sheet |
| `loop` | The last frame does not lead back to the first | `repair` the last frame |
| `cell-edge` | A frame touches its runtime cell | Use a bigger `--cell` |
| `halo` | Matte color is left on edges | Ask for alpha or use `--cutout birefnet` |

Regenerate instead of patching pixels.
