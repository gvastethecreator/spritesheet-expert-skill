from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "SKILLS" / "spritesheet-expert" / "scripts"


def run_script(script: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / script), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def write_tiny_asset_run(run_dir: Path, size: tuple[int, int]) -> None:
    width, height = size
    safe_margin = 1 if min(size) <= 16 else 2
    request = {
        "version": 2,
        "kind": "sprite-gen-request",
        "asset_kind": "asset",
        "frame_semantics": "still-assets",
        "extraction_mode": "slots",
        "raw_layout_policy": "off",
        "cell": {
            "shape": "square" if width == height else "rect",
            "width": width,
            "height": height,
            "safe_margin": safe_margin,
        },
        "states": {
            "props": {
                "frames": 1,
                "fps": 1,
                "loop": False,
                "asset_labels": ["tiny-prop"],
            }
        },
        "sampling_policy": {
            "filter": "nearest",
            "wrap": "clamp-to-edge",
            "mipmaps": False,
            "pixel_snap": True,
        },
        "chroma_key": {"name": "magenta", "hex": "#FF00FF", "rgb": [255, 0, 255]},
        "background_removal": {"method": "none"},
        "asset_catalog": {
            "items": {
                "tiny-prop": {
                    "category": "prop",
                    "pivot": [width // 2, height - safe_margin],
                    "strategy_class": "compact_prop",
                }
            }
        },
    }
    run_dir.mkdir(parents=True)
    (run_dir / "sprite-request.json").write_text(
        json.dumps(request), encoding="utf-8"
    )
    raw = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(raw)
    draw.rectangle(
        (1, 1, width - 1, height - 1),
        fill=(32, 96, 224, 255),
    )
    draw.rectangle(
        (max(1, width // 2), 1, width - 1, height - 1),
        fill=(240, 192, 48, 255),
    )
    raw_path = run_dir / "raw" / "props.png"
    raw_path.parent.mkdir()
    raw.save(raw_path)


def write_slot_check_frame(run_dir: Path, frame: Image.Image) -> None:
    write_tiny_asset_run(run_dir, frame.size)
    frame_path = run_dir / "frames" / "props" / "frame-0.png"
    frame_path.parent.mkdir(parents=True)
    frame.save(frame_path)
    manifest = {
        "ok": True,
        "rows": [
            {
                "state": "props",
                "frames": 1,
                "files": ["frames/props/frame-0.png"],
            }
        ],
    }
    (run_dir / "frames" / "frames-manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )


def write_registration_run(
    run_dir: Path, source: Image.Image, *, sampling_filter: str
) -> None:
    request = {
        "asset_kind": "asset",
        "cell": {"width": 8, "height": 8, "safe_margin": 1},
        "states": {"props": {"frames": 1, "fps": 1, "loop": False}},
        "sampling_policy": {
            "filter": sampling_filter,
            "wrap": "clamp-to-edge",
            "mipmaps": False,
            "pixel_snap": sampling_filter == "nearest",
        },
    }
    run_dir.mkdir(parents=True)
    (run_dir / "sprite-request.json").write_text(
        json.dumps(request), encoding="utf-8"
    )
    frame_path = run_dir / "frames" / "props" / "frame-0.png"
    frame_path.parent.mkdir(parents=True)
    source.save(frame_path)
    manifest = {
        "ok": True,
        "rows": [
            {
                "state": "props",
                "frames": 1,
                "files": ["frames/props/frame-0.png"],
            }
        ],
    }
    (run_dir / "frames" / "frames-manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )


@pytest.mark.parametrize("size", [(8, 8), (8, 16), (32, 32)])
def test_default_tiny_pixel_pipeline_accepts_scale_aware_assets(
    tmp_path: Path, size: tuple[int, int]
) -> None:
    label = f"tiny-{size[0]}x{size[1]}"
    run_dir = tmp_path / label
    registered_dir = tmp_path / f"{label}-registered"
    write_tiny_asset_run(run_dir, size)

    extracted = run_script(
        "extract_sprite_row_frames.py",
        "--run-dir",
        str(run_dir),
        "--background-removal",
        "none",
        "--edge-refine",
        "off",
    )
    assert extracted.returncode == 0, extracted.stdout + extracted.stderr

    registered = run_script(
        "register_sprite_frames.py",
        "--run-dir",
        str(run_dir),
        "--out-dir",
        str(registered_dir),
    )
    assert registered.returncode == 0, registered.stdout + registered.stderr

    checked = run_script(
        "check_asset_slots.py",
        "--run-dir",
        str(registered_dir),
    )
    assert checked.returncode == 0, checked.stdout + checked.stderr

    frame = Image.open(registered_dir / "frames" / "props" / "frame-0.png").convert(
        "RGBA"
    )
    assert frame.size == size
    assert set(frame.getchannel("A").get_flattened_data()) <= {0, 255}
    assert set(frame.get_flattened_data()) <= {
        (0, 0, 0, 0),
        (32, 96, 224, 255),
        (240, 192, 48, 255),
    }


def test_pixel_slot_qa_rejects_bilinear_fractional_alpha(tmp_path: Path) -> None:
    run_dir = tmp_path / "bilinear-corruption"
    source = Image.new("RGBA", (4, 4), (0, 0, 0, 0))
    source.putpixel((1, 1), (32, 96, 224, 255))
    source.putpixel((2, 1), (240, 192, 48, 255))
    source.putpixel((1, 2), (32, 96, 224, 255))
    source.putpixel((2, 2), (240, 192, 48, 255))
    corrupted = source.resize((8, 8), Image.Resampling.BILINEAR)
    write_slot_check_frame(run_dir, corrupted)

    checked = run_script(
        "check_asset_slots.py",
        "--run-dir",
        str(run_dir),
    )

    assert checked.returncode == 1, checked.stdout + checked.stderr
    report = json.loads(
        (run_dir / "qa" / "asset-slot-review.json").read_text(encoding="utf-8")
    )
    assert any("alpha invariant" in error for error in report["errors"])


@pytest.mark.parametrize(
    ("kind", "expected_message"),
    [
        ("blank", "blank frame"),
        ("clipped", "edge escape"),
        ("extreme", "extreme opaque occupancy"),
    ],
)
def test_slot_qa_rejects_blank_clipped_and_extreme_tiny_frames(
    tmp_path: Path, kind: str, expected_message: str
) -> None:
    frame = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    if kind == "clipped":
        ImageDraw.Draw(frame).rectangle((0, 2, 3, 5), fill=(32, 96, 224, 255))
    elif kind == "extreme":
        frame.putpixel((4, 4), (32, 96, 224, 255))
    run_dir = tmp_path / kind
    write_slot_check_frame(run_dir, frame)

    checked = run_script("check_asset_slots.py", "--run-dir", str(run_dir))

    assert checked.returncode == 1, checked.stdout + checked.stderr
    report = json.loads(
        (run_dir / "qa" / "asset-slot-review.json").read_text(encoding="utf-8")
    )
    assert any(expected_message in error for error in report["errors"])


@pytest.mark.parametrize(
    ("kind", "expected_message"),
    [
        ("blank", "blank frame"),
        ("extreme", "extreme opaque occupancy"),
        ("bilinear", "alpha invariant"),
    ],
)
def test_extraction_rejects_invalid_tiny_content_before_downstream_stages(
    tmp_path: Path, kind: str, expected_message: str
) -> None:
    run_dir = tmp_path / f"extract-{kind}"
    write_tiny_asset_run(run_dir, (8, 8))
    raw_path = run_dir / "raw" / "props.png"
    if kind == "blank":
        invalid = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    elif kind == "extreme":
        invalid = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
        invalid.putpixel((4, 4), (32, 96, 224, 255))
    else:
        tiny = Image.new("RGBA", (4, 4), (0, 0, 0, 0))
        ImageDraw.Draw(tiny).rectangle((1, 1, 2, 2), fill=(32, 96, 224, 255))
        invalid = tiny.resize((8, 8), Image.Resampling.BILINEAR)
    invalid.save(raw_path)

    extracted = run_script(
        "extract_sprite_row_frames.py",
        "--run-dir",
        str(run_dir),
        "--background-removal",
        "none",
        "--edge-refine",
        "off",
    )

    assert extracted.returncode == 1, extracted.stdout + extracted.stderr
    manifest = json.loads(
        (run_dir / "frames" / "frames-manifest.json").read_text(encoding="utf-8")
    )
    assert any(expected_message in error for error in manifest["errors"])


def test_full_cell_texture_may_intentionally_fill_and_touch_edges(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "full-cell-texture"
    frame = Image.new("RGBA", (8, 8), (24, 88, 160, 255))
    write_slot_check_frame(run_dir, frame)
    request_path = run_dir / "sprite-request.json"
    request = json.loads(request_path.read_text(encoding="utf-8"))
    request["asset_kind"] = "texture"
    request["sampling_policy"]["wrap"] = "repeat"
    request["asset_catalog"]["items"]["tiny-prop"]["repeat_mode"] = "self"
    request_path.write_text(json.dumps(request), encoding="utf-8")

    checked = run_script("check_asset_slots.py", "--run-dir", str(run_dir))

    assert checked.returncode == 0, checked.stdout + checked.stderr
    report = json.loads(
        (run_dir / "qa" / "asset-slot-review.json").read_text(encoding="utf-8")
    )
    assert report["records"][0]["occupancy"] == 1.0
    assert report["records"][0]["edge_touch"] is True
    assert report["repeat_validation"]["ok"] is True


def test_full_cell_texture_edges_survive_extract_register_and_slot_qa(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "texture-run"
    registered_dir = tmp_path / "texture-registered"
    write_tiny_asset_run(run_dir, (8, 8))
    request_path = run_dir / "sprite-request.json"
    request = json.loads(request_path.read_text(encoding="utf-8"))
    request["asset_kind"] = "texture"
    request["cell"]["safe_margin"] = 0
    request["sampling_policy"]["wrap"] = "repeat"
    request["asset_catalog"]["items"]["tiny-prop"]["pivot"] = [4, 8]
    request["asset_catalog"]["items"]["tiny-prop"]["repeat_mode"] = "self"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    Image.new("RGBA", (8, 8), (24, 88, 160, 255)).save(
        run_dir / "raw" / "props.png"
    )

    extracted = run_script(
        "extract_sprite_row_frames.py",
        "--run-dir",
        str(run_dir),
        "--background-removal",
        "none",
        "--edge-refine",
        "off",
    )
    assert extracted.returncode == 0, extracted.stdout + extracted.stderr
    registered = run_script(
        "register_sprite_frames.py",
        "--run-dir",
        str(run_dir),
        "--out-dir",
        str(registered_dir),
    )
    assert registered.returncode == 0, registered.stdout + registered.stderr
    checked = run_script(
        "check_asset_slots.py", "--run-dir", str(registered_dir)
    )
    assert checked.returncode == 0, checked.stdout + checked.stderr

    output = Image.open(
        registered_dir / "frames" / "props" / "frame-0.png"
    ).convert("RGBA")
    assert output.getbbox() == (0, 0, 8, 8)


@pytest.mark.parametrize("sampling_filter", ["nearest", "linear"])
def test_registration_resampling_follows_canonical_sampling_policy(
    tmp_path: Path, sampling_filter: str
) -> None:
    source = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    draw = ImageDraw.Draw(source)
    draw.rectangle((1, 1, 7, 14), fill=(32, 96, 224, 255))
    draw.rectangle((8, 1, 14, 14), fill=(240, 192, 48, 255))
    run_dir = tmp_path / f"register-{sampling_filter}"
    out_dir = tmp_path / f"register-{sampling_filter}-out"
    write_registration_run(run_dir, source, sampling_filter=sampling_filter)

    registered = run_script(
        "register_sprite_frames.py",
        "--run-dir",
        str(run_dir),
        "--out-dir",
        str(out_dir),
    )

    assert registered.returncode == 0, registered.stdout + registered.stderr
    output = Image.open(out_dir / "frames" / "props" / "frame-0.png").convert("RGBA")
    source_palette = {
        (0, 0, 0, 0),
        (32, 96, 224, 255),
        (240, 192, 48, 255),
    }
    if sampling_filter == "nearest":
        assert set(output.get_flattened_data()) <= source_palette
        assert set(output.getchannel("A").get_flattened_data()) <= {0, 255}
    else:
        assert set(output.get_flattened_data()) - source_palette


def test_sprite_registration_keeps_edge_escape_as_a_hard_failure(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "clipped-sprite"
    out_dir = tmp_path / "clipped-sprite-out"
    source = Image.new("RGBA", (8, 8), (32, 96, 224, 255))
    write_registration_run(run_dir, source, sampling_filter="nearest")
    request_path = run_dir / "sprite-request.json"
    request = json.loads(request_path.read_text(encoding="utf-8"))
    request["asset_kind"] = "sprite"
    request["cell"]["safe_margin"] = 0
    request_path.write_text(json.dumps(request), encoding="utf-8")

    registered = run_script(
        "register_sprite_frames.py",
        "--run-dir",
        str(run_dir),
        "--out-dir",
        str(out_dir),
    )

    assert registered.returncode == 1, registered.stdout + registered.stderr
    report = json.loads(
        (out_dir / "qa" / "registration-report.json").read_text(encoding="utf-8")
    )
    assert any("edge escape" in error for error in report["errors"])


def test_explicit_absolute_min_used_pixel_overrides_remain_authoritative(
    tmp_path: Path,
) -> None:
    extraction_run = tmp_path / "extract-override"
    write_tiny_asset_run(extraction_run, (8, 8))
    extracted = run_script(
        "extract_sprite_row_frames.py",
        "--run-dir",
        str(extraction_run),
        "--background-removal",
        "none",
        "--edge-refine",
        "off",
        "--min-used-pixels",
        "400",
    )
    assert extracted.returncode == 1
    assert "too sparse" in extracted.stdout

    source = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    ImageDraw.Draw(source).rectangle((2, 2, 5, 5), fill=(32, 96, 224, 255))
    registration_run = tmp_path / "register-override"
    registration_out = tmp_path / "register-override-out"
    write_registration_run(registration_run, source, sampling_filter="nearest")
    registered = run_script(
        "register_sprite_frames.py",
        "--run-dir",
        str(registration_run),
        "--out-dir",
        str(registration_out),
        "--min-used-pixels",
        "80",
    )
    assert registered.returncode == 1
    assert "too sparse" in registered.stdout

    slot_run = tmp_path / "slot-override"
    write_slot_check_frame(slot_run, source)
    checked = run_script(
        "check_asset_slots.py",
        "--run-dir",
        str(slot_run),
        "--min-used-pixels",
        "120",
    )
    assert checked.returncode == 1
    assert "too sparse" in checked.stdout
