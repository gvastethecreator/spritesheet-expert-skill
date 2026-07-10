from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from smoke_presets_from_reference import write_raw_rows


def test_smoke_raw_fixture_follows_declared_compact_grid(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "sprite-request.json").write_text(
        json.dumps(
            {
                "cell": {"width": 16, "height": 20, "safe_margin": 2},
                "states": {
                    "run": {
                        "frames": 4,
                        "raw_layout": {
                            "kind": "compact-grid",
                            "columns": 2,
                            "rows": 2,
                            "order": "row-major",
                            "delivery": "compose-runtime-row",
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    sprite = Image.new("RGBA", (6, 8), (230, 50, 70, 255))

    write_raw_rows(run_dir, [sprite])

    with Image.open(run_dir / "raw" / "run.png") as raw:
        assert raw.size == (32, 40)
        assert raw.getpixel((8, 12)) != (0, 255, 0, 255)
        assert raw.getpixel((24, 32)) != (0, 255, 0, 255)


def test_smoke_full_cell_fixture_has_no_chroma_padding(tmp_path: Path) -> None:
    run_dir = tmp_path / "tiles"
    run_dir.mkdir()
    (run_dir / "sprite-request.json").write_text(
        json.dumps(
            {
                "asset_kind": "tileset",
                "cell": {"width": 16, "height": 16, "safe_margin": 0},
                "states": {
                    "terrain": {
                        "frames": 1,
                        "raw_layout": {
                            "kind": "strip",
                            "columns": 1,
                            "rows": 1,
                            "order": "left-to-right",
                            "delivery": "compose-runtime-row",
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    tall_sprite = Image.new("RGBA", (8, 12), (210, 70, 50, 255))

    write_raw_rows(run_dir, [tall_sprite])

    with Image.open(run_dir / "raw" / "terrain.png") as raw:
        assert all(
            raw.getpixel((x, y)) != (0, 255, 0, 255)
            for y in range(raw.height)
            for x in range(raw.width)
        )
