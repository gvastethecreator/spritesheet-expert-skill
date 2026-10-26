# Atlas recipe

Use for loose items with no grid: props, loot, pickups, decals. `build`
finds each item by its shape, keeps parts with their owner, names the items
in reading order and packs them tightly at one shared scale.

## 1. Plan

```bash
python sprite.py plan --out runs/props --lane atlas --subject "props for a cozy boxing gym" \
  --style "soft stylized 3D, satin finish" --cell 256 \
  --set "props=trophy,dumbbell,water-bottle,towel,boxing-glove,bell"
```

- One `--set` per sheet. The slot names become item names in reading order:
  rows from top to bottom, then left to right.
- `--cell` is the box the largest item fits in. Smaller items keep their
  size relative to it.
- Name one object per slot. A pair (two gloves) is two items unless they touch.

`plan` writes `prompts/<set>.txt`. There is no layout guide: the prompt asks
for wide empty space between objects instead of a grid.

## 2. Generate and build

```bash
python sprite.py build runs/props --source props=sheet.png --provider "<name>"
```

How separation works:

| Piece | Becomes |
| --- | --- |
| Pieces closer than 1.5% of the sheet's short side | One item (a bottle and its cork) |
| A group under 2% of the typical item area | A speck, dropped and counted |
| Everything else | One item each, named in reading order |

## 3. Review, check, repair

| Check | Meaning when it is not `pass` | Fix |
| --- | --- | --- |
| `items` | Fewer items than planned (some touch) or more (stray pieces) | Regenerate with wider gaps, or fix names |
| `source-edge` | An item touches the sheet edge | Regenerate with more margin |
| `halo` | Matte color is left on edges | Ask for alpha or use `--cutout birefnet` |

`repair --state props --frame N` and `build --patch props:N=image.png` redraw
one item; the patch takes the size of the item it replaces.

`atlas.json` lists each item as `{name, x, y, w, h}` in the packed `atlas.png`.
