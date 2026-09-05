# Delivery Lab

A local, read-only inspector for `deterministic-item-sheet-v1` / `deterministic-item-atlas` runs. It does not generate artwork, call a model, upload files, edit masks or approve items.

## Open

From the repository root:

```powershell
pnpm studio
```

Open the local Studio address printed by the command, then navigate to `/delivery-lab.html` on that same address. The usual address is `http://127.0.0.1:4173/delivery-lab.html`; use the actual port printed by your server. From the installed skill directory, `python scripts/serve_item_studio.py` starts the same local server. The page uses only bundled HTML/JavaScript and browser APIs; model runtime installation is not needed for inspection.

## Load the correct artifacts

Select the complete run folder, not only `atlas.png`. Then explicitly select its active deterministic item manifest. A run may contain initial, segmented, classified and reviewed manifests; use the path identified by its `workflow.json` or the reviewed successor you intend to inspect. Do not assume the first manifest in the dropdown is the latest or approved one.

Every atlas, source and crop must exist at the exact path relative to the selected manifest. Original file-byte SHA-256 values are compared before drawing. A missing file, wrong hash or invalid supported geometry blocks display. The viewer deliberately has no basename fallback: selecting a same-named image from another run is not sufficient.

## Four views

| View | What it answers | What it does not prove |
| --- | --- | --- |
| Atlas | Which pixels belong to the selected runtime frame, versus its reserved cell? | Successful loading by a game engine |
| Source | Where did this item's pixels originate? | That the semantic grouping is correct without review |
| Placement | How does the native crop sit at its declared normalized pivot? | World footprint, collision shape, depth sorting or engine origin behavior |
| Delivery | Which files match, which reviews remain, and does a supplied Python receipt match this snapshot? | Signed user identity or automatic visual acceptance |

Use 1× for native-size inspection and 2×/4×/8× for edge inspection. Switch checker/black/gray/white backgrounds, hide overlays and step through the inventory with arrows. Amber identifies the selected frame; gray identifies reserved cells; the placement cross is the declared pivot. `source.bbox` is XYXY while `geometry.frame` is XYWH.

## Authoritative validation and receipt

From the skill directory:

```powershell
python scripts/validate_item_delivery.py --manifest <active-manifest.json>
python scripts/export_item_atlas.py --manifest <active-manifest.json> --output-dir <new-runtime-directory>
```

The validator prints JSON. Exit codes are 0 for pass, 2 for review required and 3 for invalid artifacts. Set `--max-texture-size` to the actual target limit. Add `--draft` only to permit unresolved review; it never bypasses corrupted hashes, missing pixels or invalid geometry.

The Studio audit ZIP includes `qa/delivery-check.json`; the static runtime export includes `delivery-check.json`. Delivery Lab automatically looks for those names beside the selected manifest root, or accepts a separately chosen receipt. It verifies the receipt contract, manifest hash, required recorded artifacts, artifact hashes and status consistency. A mismatching receipt is explicitly rejected. Receipts are unsigned technical evidence, not authentication.

`Download inspection record` exports `item-browser-inspection-v1`. It records browser file identity checks and the supplied receipt status. It is **not** an `item-review-v1` approval document and cannot substitute for Python pixel-ownership validation.

## Inspection versus editing versus delivery

Use the main Studio for source ownership editing and review operations. Cross-check exact files here before production acceptance; the audit records known identity and replacement-race issues in the older portable writable Atlas Lab. Do not assume this separate verified viewer silently fixes that old path.

The static JSON Hash exporter uses actual native frames and stable IDs. Its `source-manifest.snapshot.json` is an audit snapshot whose source-run artifacts are not all copied into the runtime bundle. Select the original complete run for this inspector. A runtime export alone is intentionally not a complete editable source project.

Actual Phaser/Godot playback and placement tests remain a separate gate. The existing animation Preview Workbench and video selector remain the appropriate interfaces for chronological frames; this static item inspector does not infer a timeline from packing order.

## Tests and limitations

`tests/browser/check_delivery_lab.py` exercises folder loading, all four views, zoom/background controls, receipt matching, stale receipt rejection and corrupted atlas blocking using synthetic geometry in a real Chromium browser. The CI job installs a pinned Playwright package and its Chromium runtime. No provider or model is invoked.

File selection and hashing need a modern browser with directory input and Web Crypto support; serve through the loopback Studio when file-origin behavior differs. Browser pixel-decoding and Canvas placement are not the independent Python validator. Very large runs still need the resource-budget/page work documented in the production backlog. Do not bypass a managed browser's security policy to run this tool.

See [production workflow](../references/production-workflow.md) and the repository audit/backlog for complete acceptance and known limitations.
