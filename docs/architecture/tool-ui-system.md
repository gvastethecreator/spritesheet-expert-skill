# Tool UI system

All review tools that the skill generates use one visual system. The source is
`SKILLS/spritesheet-expert/scripts/spritecore/tool_theme.py`.

## Rules

- English is the default language for every label, status, and message.
- A tool page is one file. The emitter inlines `TOOL_CSS` in a `<style>` tag.
  Do not link a stylesheet. Do not use remote URLs.
- The artifact (stage, canvas, or item) gets the most space. Controls and
  evidence stay at the edges.
- Dark theme is the default. The light theme follows `prefers-color-scheme`.
  `data-theme="light"` or `data-theme="dark"` on `<html>` overrides it.
- Pixel art is shown with nearest sampling and integer zoom only.

## Tokens

| Group | Tokens |
| --- | --- |
| Surfaces | `--bg`, `--surface`, `--raised`, `--sunken` |
| Lines | `--line`, `--line-strong` |
| Text | `--ink`, `--muted`, `--faint` |
| Accent (one only) | `--accent`, `--accent-ink`, `--accent-soft` |
| Status | `--ok`, `--warn`, `--bad` |
| Review mattes | `--checker-a`, `--checker-b`, `--checker-size`, `--matte-black`, `--matte-gray` (`#808080`), `--matte-white` |
| Type | `--font-ui` (system sans), `--font-mono` (numbers, ids, readouts) |
| Shape | `--radius`, `--radius-lg` |

Use the tokens. Do not add new color values in a tool.

## Components

| Class | Use |
| --- | --- |
| `.tool`, `.tool-header`, `.brand`, `.status` | Page shell, header, live status line (`aria-live="polite"`) |
| `.btn`, `.btn-icon`, `.btn-primary`, `aria-pressed="true"` | Buttons and toggles |
| `.field`, `select` | Labeled select or input |
| `.toolbar`, `.group`, `.seg` | Control rows and segmented groups |
| `.stage[data-background=checker\|black\|gray\|white]` | Review stage with the four standard mattes |
| `.swatch[data-swatch=…]` | Small matte sample inside a background button |
| `canvas[data-sampling=nearest\|linear]` | Pixel-honest or smooth canvas |
| `.transport`, `.scrub`, `.readout` | Play controls, frame slider, frame counter |
| `.filmstrip`, `.film-frame`, `.bar` | Frame timeline with thumbnails and duration bars |
| `.rail`, `.rail-section`, `.rail-title` | Side inspector |
| `.list`, `.list-row`, `.meta` | Selectable rows and evidence links |
| `.facts` | Key and value pairs (`<dl>`) |
| `.chip[data-status=approved\|rejected\|pending]` | Review decisions |
| `.chip[data-status=pass\|fail\|warn\|missing\|file]` | QA gate status. `file` is evidence with no verdict. `missing` is an expected report that does not exist yet |
| `.list-row[aria-disabled="true"]` | A row with no link, such as a missing report |
| `.card`, `.empty`, `kbd`, `.keys`, `.sr-only` | Panels, empty text, shortcut help |

`THEME_SCRIPT` adds an optional theme toggle. Give a button the id
`theme-toggle`. The script saves the choice in `localStorage` and works when
storage is blocked.

## Adopt the system in an emitter

1. Import `TOOL_CSS` (and `THEME_SCRIPT` if the page has a toggle).
2. Write `<style>{TOOL_CSS}{PAGE_CSS}</style>`. Keep `PAGE_CSS` for layout only.
3. Build the page from the classes above. Remove local copies of checkers,
   scrollbars, buttons, and color values.
4. Keep test-pinned ids, `aria-label` values, and data attributes.
5. Check the page in a browser at 1280 px and 390 px, in dark and light themes.
   There must be no horizontal page scroll.

The preview workbench (`spritecore/preview_workbench.py`) is the reference
implementation.

## Studio and Delivery Lab

Studio is served as static files, so it cannot inline Python strings at build
time. It uses generated copies instead:

- `studio/tool-theme.css` is `TOOL_CSS`.
- `studio/tool-theme.js` is `THEME_SCRIPT`.

Do not edit these files. After a change to `tool_theme.py`, run
`pnpm run sync:theme`. It also updates the curator and the motion reference
review. `pnpm run validate` fails when any copy is out of sync.

`studio/styles.css` holds Studio layout only. Its legacy button classes
(`primary-button`, `secondary-button`, `quiet-button`) map onto the shared
button look. `studio/matte.js` paints the four standard mattes on a canvas from
the same tokens; Process a sheet and Delivery Lab use it.

Studio-only pieces that could move into the shared system later:

- `.chip[data-status=replace|regenerate]` (accent-colored decision chips).
- Sidebar navigation with group labels (`.nav-group`, `.nav-item`).
- `paintMatte()` for canvas tools that cannot use `.stage[data-background]`.
