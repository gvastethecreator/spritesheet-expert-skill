# Agent-first Studio workflow

Read this reference when Spritesheet Expert is driven by a local Studio, another agent, a prompt editor, or an external provider runner.

The Studio is a portable front end for the skill contracts. It must not fork production policy, infer hidden approvals, or bypass deterministic scripts.

## Ownership model

```text
user or coordinating agent
-> selects workflow and inputs
-> Spritesheet Expert skill resolves policy
-> Studio renders/edit portable contract
-> external provider or local worker performs explicit inference
-> source intake verifies returned bytes and provenance
-> deterministic scripts extract, compose, review, and validate
```

The graphical interface can be replaced. The files and contracts must remain sufficient to reproduce the work.

## Workflow registry

Every Studio workflow declares:

- stable `id` and integer `version`;
- human title and description;
- owning skill;
- execution mode;
- typed input fields;
- prompt template;
- CLI template;
- expected artifacts;
- provider requirement;
- explicit-execution requirement when relevant;
- batch policy for generation jobs.

A workflow field referenced by `{{placeholder}}` must exist in the same workflow definition. Unknown placeholders are a validation failure.

## Output modes

The Workflow Launcher renders the same workflow in three forms:

### Prompt

A complete natural-language handoff for another agent. It names the owner skill, exact inputs, deterministic requirements, provider boundary, and completion evidence.

### CLI

A local deterministic command. A CLI string may prepare jobs or process accepted media, but it must not imply that external inference already ran.

### JSON

A `studio-handoff-v1` job containing the prompt, command, structured inputs, expected artifacts, provider boundary, and execution status.

Copying, downloading, or queuing a handoff leaves `status: prepared`. Only an actual provider or worker adapter may advance execution state.

## Provider boundary

A provider handoff must be explicit. The Studio does not:

- store API keys;
- silently spend credits;
- call paid inference when a form changes;
- accept browser state as provenance;
- fabricate output when a provider is blocked;
- mark a job complete merely because a prompt was copied.

A future provider adapter must begin with a dry run or equivalent preview and require current-task acknowledgement before a paid action.

## Regeneration contract

Item and frame replacement is intentionally narrow.

For one item:

```json
{
  "workflowId": "regenerate-single-item",
  "expected": {"count": 1},
  "targetItemId": "item_...",
  "status": "prepared"
}
```

The prompt must mention only the target category and prohibit:

- collages;
- contact sheets;
- grids;
- concept sheets;
- multiple panels;
- alternate object categories;
- reuse of a failed multi-object image as an image-to-image reference.

When the result repeats another category, contains several categories, or otherwise fails semantic validation, discard that result and retry only the pending item. Do not advance the batch counter.

## Local file handling

The bundled Studio uses `scripts/serve_item_studio.py` for the local item workflow.
Read `local-model-item-workflow.md` for execution, pixel-mask review, and export.
The handoff and Atlas Lab views also support browser file pickers.

- Manifest JSON is selected explicitly.
- A run folder is selected to resolve relative crop paths.
- Object URLs are revoked when the run changes or the page closes.
- Replacement files are hashed locally.
- Review exports contain metadata and hashes, not hidden provider credentials.

For an item replacement to be applied, keep the review JSON and replacement image in a known workspace. The deterministic CLI verifies the recorded SHA-256.

## Review semantics

The UI is not an approval authority by itself. It records review decisions that become authoritative only as a portable review file bound to a parent manifest.

Supported item states:

- `pending`: not decided;
- `approved`: visually accepted;
- `rejected`: excluded from successor atlas;
- `replace`: use a supplied reviewed replacement;
- `regenerate`: provider work still required.

Changing source bytes, replacement bytes, crop geometry, registration, pivot, or atlas composition invalidates affected evidence and requires a successor run.

## Immutable lineage

A successor manifest records:

```json
{
  "parentManifestSha256": "...",
  "runId": "parent-run-review-..."
}
```

Never overwrite a reviewed parent manifest merely to keep a familiar path. Immutability allows an agent to prove which review and source bytes produced a delivery.

## Portable queue

The Agent Queue exports JSONL. Each line is independently parseable and contains one job. Queue order is advisory; dependencies must be expressed in job data or the coordinating run contract rather than assumed from browser position alone.

The queue may contain deterministic and provider handoffs, but an executor must route them by `mode` and `providerBoundary`.

## Studio validation

Run:

```powershell
pnpm run validate:studio
```

The validator checks:

- required Studio and contract files;
- valid workflow registry JSON;
- stable unique workflow IDs;
- required workflow fields;
- prompt placeholder ownership;
- one-item regeneration isolation markers;
- explicit provider execution boundaries;
- static bundle entry points;
- absence of remote runtime dependencies.

## Extending the Studio

A new playground should reuse the same principles:

1. Define a versioned file contract first.
2. Identify the skill and deterministic script that owns the operation.
3. Make every mutation produce an inspectable successor artifact.
4. Keep provider inference outside automatic UI state transitions.
5. Export decisions and evidence.
6. Add contract and UI validation.
7. Add a focused integration test before publishing the workflow.

Planned labs include animation curation, mask editing, tile adjacency, runtime placement, delivery reconciliation, and local model workers. They should share the workspace and handoff contracts instead of becoming isolated miniature applications.
