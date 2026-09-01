# Contributing

Thank you for helping improve Spritesheet Expert. Keep public documentation in American English. Keep changes focused, preserve the distinction between generated media and deterministic processing, and never promote a fixture as representative production evidence.

## Development setup

Requirements:

- Node.js 24
- pnpm 11.21
- Python 3.11 or newer

Install the pinned test environment and validate the repository:

```powershell
pnpm install --frozen-lockfile
pnpm run setup:test
pnpm run check
```

Optional generation, background-removal, and video dependencies are capability-scoped. Install only the requirement file needed by the path you are testing.

## Pull requests

- Explain the user-facing or pipeline outcome.
- Include provenance for any generated or imported visual evidence.
- Keep native provider transparency when it is reliable; document any fallback removal lane.
- Add or update the nearest existing test only when behavior changes.
- Run `pnpm run check` and `git diff --check` before requesting review.
- Do not commit secrets, generated caches, or unlicensed source media.

By contributing, you agree that your work is provided under the repository license.

