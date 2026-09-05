# Spritesheet Expert Studio

Portable, local-first interface for composing Spritesheet Expert jobs and reviewing deterministic item-atlas runs.

## Start locally

From the repository root:

```powershell
pnpm run studio
```

Then open:

```text
http://localhost:4173
```

A local HTTP server is required because the Studio loads `workflows.json` with `fetch()`. Opening `index.html` directly through `file://` is intentionally not the supported path.

## What the Studio does

### Process a sheet

- Import transparent source sheets and run the shared local workflow.
- Choose installed offline model profiles, padding and cell quantum.
- Cancel or resume saved runs; inspect failures and stage logs.
- Review source masks, merge components, paint pixel assignments and edit tags.
- Export a clean atlas, native crops, manifest and evidence; unresolved runs require explicit draft export.

From a standalone skill installation, run `.local/item-model-runtime/Scripts/python.exe scripts/serve_item_studio.py` after setup (use `bin/python` on Linux). See `../references/local-model-item-workflow.md` for runtime and checkpoint setup.

### Workflow Launcher

- Loads the portable workflow registry from `workflows.json`.
- Generates prompts, CLI commands, and `studio-handoff-v1` JSON jobs.
- Copies or downloads prepared work.
- Adds jobs to a local queue for explicit execution by another agent or provider.

### Atlas Lab

- Loads a `deterministic-item-sheet-v1` manifest.
- Resolves item images from a user-selected run folder.
- Reviews native-size crops on checker, black, gray, and white backgrounds.
- Filters and sorts items by source order, size, type, and review state.
- Records approval, rejection, replacement, regeneration, tags, type overrides, and notes.
- Hashes local replacement files in the browser.
- Exports an `item-review-v1` document.

### Agent Queue

- Holds prepared jobs only.
- Exports newline-delimited JSON.
- Does not execute paid or remote inference.
- Keeps one-item regeneration jobs isolated from unrelated batch categories.

## Security and privacy boundary

Studio uses a loopback Python service with session-token-protected operations. It has no account system, analytics, remote font, CDN dependency, or provider secret storage. Imported files and all processing remain local. Model installation and checkpoint downloads are separate explicit CLI commands.

Provider media must re-enter the deterministic pipeline through the repository's source-intake and provenance contracts. A filename alone is never accepted as proof of origin.

## Review files and replacement images

The exported review references replacement images by filename and SHA-256. Keep the review JSON and its replacement files in the same review workspace before applying it:

```text
review-workspace/
├── item-review.json
├── item_001.png
└── item_002.png
```

Then apply it into a new run:

```powershell
python SKILLS/spritesheet-expert/scripts/apply_item_review.py `
  --manifest build/item-atlas/manifest.json `
  --review review-workspace/item-review.json `
  --output-dir build/item-atlas-reviewed
```

The parent run remains unchanged. The command rejects a review when its source-manifest hash does not match the selected parent.

The successor preserves reviewed replacement sources and rebuilds the item crops, classification composites, atlas, and grid evidence.

## Validate the Studio bundle

```powershell
pnpm run validate:studio
```

The validator checks the portable files, workflow registry, prompt placeholders, regeneration isolation rules, required contracts, and absence of remote runtime dependencies.

## Current boundary

The Studio vertical slice deliberately does not include:

- automatic provider execution;
- provider API keys;
- model installation;
- lasso tools;
- Tauri packaging;
- collaborative review services.

Those features belong to later product stages described in `docs/architecture/agent-first-studio.md`.
