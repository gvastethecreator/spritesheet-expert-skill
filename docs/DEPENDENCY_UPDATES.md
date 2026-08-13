# Dependency review — 2026-08-12

## Current pins

The Python project was already pinned and was refreshed to current registry releases:

- Pillow 12.3.0
- jsonschema 4.26.0
- pytest 9.1.1 and pytest-cov 7.1.0
- imageio-ffmpeg 0.6.0
- rembg[cpu] 2.0.78 (updated from 2.0.77)

The root package has no JavaScript dependencies; pnpm 11.20.0 is used only for deterministic Node
validator scripts. No Bun runtime was found.

Changelog sources reviewed: [Pillow](https://pillow.readthedocs.io/en/stable/releasenotes/index.html),
[jsonschema](https://github.com/python-jsonschema/jsonschema/releases),
[pytest](https://docs.pytest.org/en/stable/changelog.html),
[imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg/releases), and
[rembg](https://github.com/danielgatis/rembg/releases).
