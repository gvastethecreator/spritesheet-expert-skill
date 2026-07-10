from __future__ import annotations

import subprocess
import sys
import json
from pathlib import Path

from PIL import Image, ImageDraw


REPO_ROOT = Path(__file__).resolve().parents[2]
UNPACK = REPO_ROOT / "SKILLS" / "spritesheet-expert" / "scripts" / "unpack_atlas_run.py"


def run_unpack(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(UNPACK), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_unpack_validates_source_before_creating_output(tmp_path: Path) -> None:
    out_dir = tmp_path / "run"

    result = run_unpack(
        "--atlas",
        str(tmp_path / "missing.png"),
        "--grid",
        "1x1",
        "--out-dir",
        str(out_dir),
    )

    assert result.returncode != 0
    assert not out_dir.exists()


def test_unpack_writes_a_v2_request_contract(tmp_path: Path) -> None:
    atlas = tmp_path / "one.png"
    _write_atlas(atlas, 1, 1)
    out_dir = tmp_path / "run"

    result = run_unpack(
        "--atlas",
        str(atlas),
        "--grid",
        "1x1",
        "--states",
        "idle",
        "--background-removal",
        "none",
        "--out-dir",
        str(out_dir),
    )

    assert result.returncode == 0, result.stderr
    request = json.loads((out_dir / "sprite-request.json").read_text(encoding="utf-8"))
    assert request["version"] == 2
    assert request["kind"] == "sprite-gen-request"


def _write_atlas(path: Path, columns: int, rows: int) -> None:
    image = Image.new("RGBA", (columns * 16, rows * 16), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    for row in range(rows):
        for column in range(columns):
            index = row * columns + column
            left = column * 16 + 3
            top = row * 16 + 3
            draw.rectangle((left, top, left + 9, top + 10), fill=(40 + index * 80, 120, 220, 255))
    image.save(path)


def test_unpack_force_removes_stale_known_outputs_and_preserves_unknown_files(tmp_path: Path) -> None:
    first_atlas = tmp_path / "two.png"
    second_atlas = tmp_path / "one.png"
    _write_atlas(first_atlas, 1, 2)
    _write_atlas(second_atlas, 1, 1)
    out_dir = tmp_path / "run"

    first = run_unpack(
        "--atlas",
        str(first_atlas),
        "--grid",
        "1x2",
        "--states",
        "idle,run",
        "--background-removal",
        "none",
        "--out-dir",
        str(out_dir),
    )
    assert first.returncode == 0, first.stderr
    assert (out_dir / "frames" / "run").is_dir()
    sentinel = out_dir / "caller-note.txt"
    sentinel.write_text("keep", encoding="utf-8")

    second = run_unpack(
        "--atlas",
        str(second_atlas),
        "--grid",
        "1x1",
        "--states",
        "idle",
        "--background-removal",
        "none",
        "--out-dir",
        str(out_dir),
        "--force",
    )

    assert second.returncode == 0, second.stderr
    assert sentinel.read_text(encoding="utf-8") == "keep"
    assert not (out_dir / "frames" / "run").exists()


def test_unpack_force_refuses_an_unowned_output_directory(tmp_path: Path) -> None:
    atlas = tmp_path / "one.png"
    _write_atlas(atlas, 1, 1)
    out_dir = tmp_path / "run"
    out_dir.mkdir()
    sentinel = out_dir / "caller-note.txt"
    sentinel.write_text("keep", encoding="utf-8")

    result = run_unpack(
        "--atlas",
        str(atlas),
        "--grid",
        "1x1",
        "--states",
        "idle",
        "--background-removal",
        "none",
        "--out-dir",
        str(out_dir),
        "--force",
    )

    assert result.returncode != 0
    assert "marker" in (result.stdout + result.stderr).lower()
    assert sentinel.read_text(encoding="utf-8") == "keep"
