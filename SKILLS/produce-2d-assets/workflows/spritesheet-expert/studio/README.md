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

### Workspace

- Create or open a folder in **Workspace → Create, open or import work**.
- Keep source bytes, processing runs, review successors, prepared jobs and ZIP exports together.
- Name runs, assign collections, filter the catalog and archive or restore runs without deleting files.
- Copy existing workflow runs into the workspace after validation. Original runs stay unchanged.
- Copy relative artifact paths and blockers as context for the active agent. This does not grant execution permission.

Each folder has a stable `workspace.json` identity and a `WORKSPACE.md` guide.
Stop processing, then move or copy the whole folder and open it from another
skill installation. No model weights are needed to inspect, review or export
saved results. Install the skill's Python dependencies on the new host; configure
its runtime and model cache separately if new inference is needed.
Incomplete runs require matching inputs, implementation and checkpoint receipts
to resume. Completed runs retain their reviewed head when reopened.

From the installed skill directory, the same operations are available to an agent:

```powershell
python scripts/manage_studio_workspace.py create --workspace X:/art-workspaces/blackflag --name "Black Flag"
python scripts/manage_studio_workspace.py inspect --workspace X:/art-workspaces/blackflag
python scripts/manage_studio_workspace.py import --workspace X:/art-workspaces/blackflag --source returned.png --collection Heraldry --job-id studio-JOB_ID
python scripts/manage_studio_workspace.py run --workspace X:/art-workspaces/blackflag --run-id RUN_ID --models none
python scripts/manage_studio_workspace.py export --workspace X:/art-workspaces/blackflag --run-id RUN_ID --draft
python scripts/serve_item_studio.py --workspace X:/art-workspaces/blackflag
```

Use `handoff --file operation.json` for `{ "kind": "add", "job": ... }` or
`{ "kind": "archive", "jobIds": [...] }`. Jobs use `studio-handoff-v1`.
Source import can link to a saved job ID, but that link is not provider provenance.
Prepared CLI paths are relative to the installed skill directory, or absolute.
Workspace records locate their artifacts relative to the workspace. Historical
absolute paths inside logs remain evidence; they do not locate current artifacts.

Exports are stored under `exports/` with archive and manifest hashes. Downloading
checks the archive bytes again. Saved ZIPs are limited to 256 MiB; run copying is
limited to 2 GiB and rejects linked paths. No files or models are uploaded.
Archive only hides a run or job; it is not deletion or approval. Old browser-only
queues are not automatically assigned to a workspace; existing browser storage
is left untouched. Atlas Lab still requires explicit review JSON export; its
unsaved editor state is not a portable workspace record.

Copy row/grid/animation/tileset runs with `adopt-run --source <run>` (or the same
Studio form). The request determines the lane; optional `--lane` asserts it.
These runs retain `workspace-run.json`, source evidence and their existing QA
files. Studio can inspect those files, group/archive the run, and save a snapshot
ZIP. CLI `export --draft` saves the same snapshot. It is not an approved engine
delivery. Use `check_workflow.py --run-dir <copied-run> --describe` for the typed
final command, and the existing lane CLI to process a new successor.

### Process a sheet

- Import transparent source sheets and run the shared local workflow.
- Choose prepared offline model profiles, padding, cell quantum and page budgets.
- Cancel or resume saved runs; inspect failures and stage logs.
- Review source masks, merge components, paint pixel assignments and edit tags.
- Export a clean atlas, native crops, manifest and evidence; unresolved runs require explicit draft export.

From a standalone skill installation, run `.local/item-model-runtime/Scripts/python.exe scripts/serve_item_studio.py` after setup (use `bin/python` on Linux). See `../references/local-model-item-workflow.md` for runtime and checkpoint setup.

### Workflow Launcher

- Loads the portable workflow registry from `workflows.json`.
- Generates prompts, CLI commands, and `studio-handoff-v1` JSON jobs.
- Copies or downloads prepared work.
- Saves jobs in the workspace queue for explicit execution by another agent or provider.

Choose **PowerShell 7.3+** or **POSIX sh / Bash / Zsh** before copying a CLI
command. Run it from the installed `spritesheet-expert` skill directory. The
JSON job contains the exact `argv` list, the selected `commandShell`, and the
rendered `command`. Workers should pass `argv` directly to a process API with
shell execution disabled. Provider jobs have `argv: null` and require an
external adapter.

Values stay literal, including spaces, quotes, Unicode and shell syntax.
PowerShell commands require 7.3 or newer and set native argument passing only
inside the command's local scope. Windows PowerShell 5.1 and cmd.exe are not
supported command formats. Required fields and numeric limits must be valid
before copy, download or queue. NUL and carriage returns are rejected; multiline
values use LF. Changing the shell or output tab keeps the prepared job ID.

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
- Persists jobs under `handoffs/`; archiving retains their contents and IDs.
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

Approval is bound separately to pixels, semantics and placement. Changed tags
invalidate semantic approval; a new replacement receives a successor ID and
requires fresh review. Every atlas page and native crop is hash-verified before
the Atlas Lab enables editing. Original runs are never overwritten by review.

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
