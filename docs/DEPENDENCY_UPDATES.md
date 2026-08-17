# Dependency review — 2026-08-15

## Current pins

The Python project was already pinned and was refreshed to current registry releases:

- Pillow 12.3.0
- jsonschema 4.26.0
- pytest 9.1.1 and pytest-cov 7.1.0
- imageio-ffmpeg 0.6.0
- rembg[cpu] 2.0.78 (updated from 2.0.77)

The root package has no JavaScript dependencies; pnpm 11.21.0 is used only for deterministic Node
validator scripts. No Bun runtime was found.

GitHub Actions were pinned to immutable revisions. CI now installs pnpm through its dedicated setup action before invoking the frozen package graph, which fixes the previous Windows runner failure where `pnpm` was unavailable in the gate step.

Changelog sources reviewed: [Pillow](https://pillow.readthedocs.io/en/stable/releasenotes/index.html),
[jsonschema](https://github.com/python-jsonschema/jsonschema/releases),
[pytest](https://docs.pytest.org/en/stable/changelog.html),
[imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg/releases), and
[rembg](https://github.com/danielgatis/rembg/releases).
