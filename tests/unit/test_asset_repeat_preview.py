from __future__ import annotations

from pathlib import Path

from PIL import Image

from check_asset_slots import make_tile_adjacency_review, make_tile_repeat_review


def test_repeat_preview_contains_every_self_repeat_sample(tmp_path: Path) -> None:
    records = []
    for index in range(4):
        frame = tmp_path / "frames" / f"frame-{index}.png"
        frame.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGBA", (32, 32), (30 + index, 80, 45, 255)).save(frame)
        records.append(
            {
                "state": "materials",
                "label": f"material-{index}",
                "file": frame.relative_to(tmp_path).as_posix(),
                "repeat_mode": "self",
            }
        )

    relative = make_tile_repeat_review(tmp_path, records, (32, 32))

    assert relative == "qa/tile-repeat-review.png"
    with Image.open(tmp_path / relative) as review:
        assert review.size == (328, 258)
    for index in range(4):
        item = tmp_path / "qa" / "tile-repeat-items" / f"material-{index}.png"
        assert item.is_file()
        with Image.open(item) as review:
            assert review.size == (96, 114)


def test_adjacency_preview_assembles_role_aware_tiles(tmp_path: Path) -> None:
    records = []
    for index, role in enumerate(("ground-center", "ground-top", "ground-left", "ground-right")):
        frame = tmp_path / "frames" / f"frame-{index}.png"
        frame.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGBA", (32, 32), (40 + index * 20, 100, 60, 255)).save(frame)
        records.append(
            {
                "label": role,
                "tile_role": role,
                "file": frame.relative_to(tmp_path).as_posix(),
                "repeat_mode": "adjacency",
            }
        )

    relative = make_tile_adjacency_review(tmp_path, records, (32, 32))

    assert relative == "qa/tile-adjacency-review.png"
    with Image.open(tmp_path / relative) as review:
        assert review.size == (128, 250)


def test_adjacency_preview_keeps_custom_roles_beside_canonical_roles(
    tmp_path: Path,
) -> None:
    records = []
    for index, role in enumerate(("ground-center", "custom-bridge")):
        frame = tmp_path / "frames" / f"frame-{index}.png"
        frame.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGBA", (32, 32), (40 + index * 20, 100, 60, 255)).save(frame)
        records.append(
            {
                "label": role,
                "tile_role": role,
                "file": frame.relative_to(tmp_path).as_posix(),
                "repeat_mode": "adjacency",
            }
        )

    relative = make_tile_adjacency_review(tmp_path, records, (32, 32))

    with Image.open(tmp_path / relative) as review:
        assert review.size == (128, 300)
