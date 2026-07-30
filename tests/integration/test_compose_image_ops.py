from __future__ import annotations

from hashlib import sha256
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw
import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "SKILLS" / "spritesheet-expert" / "scripts"
COMPOSE = SCRIPTS / "compose_sprite_atlas.py"


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_run(
    run_dir: Path,
    *,
    size: tuple[int, int],
    rectangle: tuple[int, int, int, int],
    asset_kind: str = "sprite",
    style_preset: str = "pixel-art",
    output: dict | None = None,
) -> Image.Image:
    width, height = size
    source = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(source).rectangle(rectangle, fill=(220, 80, 40, 255))
    frame_path = run_dir / "frames" / "idle" / "frame-0.png"
    frame_path.parent.mkdir(parents=True, exist_ok=True)
    source.save(frame_path)
    request = {
        "character": {"id": "hero", "base_image": None},
        "chroma_key": {"name": "magenta", "hex": "#FF00FF"},
        "cell": {"width": width, "height": height},
        "states": {"idle": {"frames": 1, "fps": 4, "loop": True}},
        "asset_kind": asset_kind,
        "style_preset": style_preset,
    }
    if output is not None:
        request["output"] = output
    _write_json(run_dir / "sprite-request.json", request)
    _write_json(
        run_dir / "frames" / "frames-manifest.json",
        {"ok": True, "rows": [{"state": "idle", "files": ["frames/idle/frame-0.png"]}]},
    )
    return source


def _write_vfx_run(run_dir: Path) -> dict:
    state = {
        "frames": 4,
        "fps": 12,
        "loop": False,
        "raw_layout": {
            "kind": "strip",
            "columns": 4,
            "rows": 1,
            "order": "left-to-right",
            "delivery": "compose-runtime-row",
        },
        "vfx": {
            "pivot": {"role": "contact", "x": 0.5, "y": 0.75},
            "blend_mode": "additive",
            "phase_sequence": ["buildup", "peak", "decay", "hold"],
            "loop_behavior": "hold-last",
            "compositing_backgrounds": ["#101018", "#F4F1E8"],
        },
    }
    request = {
        "version": 2,
        "kind": "sprite-gen-request",
        "asset_kind": "vfx",
        "frame_semantics": "effects",
        "extraction_mode": "components",
        "raw_layout_policy": "compact-body-grids",
        "character": {"id": "impact-burst", "base_image": None},
        "chroma_key": {"name": "magenta", "hex": "#FF00FF"},
        "cell": {"width": 16, "height": 16},
        "states": {"burst": state},
        "sampling_policy": {
            "filter": "nearest",
            "wrap": "clamp-to-edge",
            "mipmaps": False,
            "pixel_snap": True,
        },
    }
    files = []
    for index in range(4):
        frame_path = run_dir / "frames" / "burst" / f"frame-{index}.png"
        frame_path.parent.mkdir(parents=True, exist_ok=True)
        frame = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
        ImageDraw.Draw(frame).rectangle(
            (5, 5, 10, 10), fill=(220, 80 + index * 20, 40, 255)
        )
        frame.save(frame_path)
        files.append(f"frames/burst/frame-{index}.png")
    _write_json(run_dir / "sprite-request.json", request)
    _write_json(
        run_dir / "frames" / "frames-manifest.json",
        {"ok": True, "rows": [{"state": "burst", "files": files}]},
    )
    return request


def _compose(run_dir: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(COMPOSE), "--run-dir", str(run_dir), *extra],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    ("size", "rectangle"),
    [
        ((8, 8), (3, 3, 4, 4)),
        ((8, 16), (3, 6, 4, 9)),
        ((32, 32), (14, 14, 18, 18)),
    ],
)
def test_compose_uses_scale_aware_validation_for_tiny_frames(
    tmp_path: Path,
    size: tuple[int, int],
    rectangle: tuple[int, int, int, int],
) -> None:
    run_dir = tmp_path / f"run-{size[0]}x{size[1]}"
    _write_run(run_dir, size=size, rectangle=rectangle)

    result = _compose(run_dir)

    assert result.returncode == 0, result.stdout + result.stderr
    with Image.open(run_dir / "sprite-sheet-alpha.png") as atlas:
        assert atlas.size == size
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["frame_layout"]["rows"]["idle"] == [
        {"x": 0, "y": 0, "w": size[0], "h": size[1]}
    ]


def test_compose_preserves_explicit_sampling_policy_in_runtime_manifest(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "illustrated-run"
    _write_run(
        run_dir,
        size=(32, 32),
        rectangle=(8, 5, 23, 28),
        style_preset="illustrated",
    )
    request_path = run_dir / "sprite-request.json"
    request = json.loads(request_path.read_text(encoding="utf-8"))
    request["sampling_policy"] = {
        "filter": "linear",
        "wrap": "clamp-to-edge",
        "mipmaps": False,
        "pixel_snap": False,
    }
    _write_json(request_path, request)

    result = _compose(run_dir)

    assert result.returncode == 0, result.stdout + result.stderr
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["sampling_policy"] == request["sampling_policy"]


def test_explicit_min_used_pixels_remains_a_compatibility_override(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "legacy-minimum"
    _write_run(run_dir, size=(8, 8), rectangle=(3, 3, 4, 4))

    result = _compose(run_dir, "--min-used-pixels", "5")

    assert result.returncode != 0
    report = json.loads(
        (run_dir / "sprite-sheet-alpha.report.json").read_text(encoding="utf-8")
    )
    assert any("too sparse (4)" in error for error in report["errors"])


def test_pixel_curation_preserves_palette_and_alpha_invariants(tmp_path: Path) -> None:
    run_dir = tmp_path / "pixel-curation"
    source = _write_run(run_dir, size=(8, 8), rectangle=(2, 2, 5, 5))
    source.putpixel((3, 3), (30, 90, 220, 255))
    source.save(run_dir / "frames" / "idle" / "frame-0.png")
    _write_json(
        run_dir / "curation.json",
        {
            "version": 1,
            "kind": "sprite-gen-curation",
            "states": {
                "idle": {
                    "selected": [0],
                    "transforms": {"0": {"rotate": 17, "scale": 1.0}},
                }
            },
        },
    )

    result = _compose(run_dir)

    assert result.returncode == 0, result.stdout + result.stderr
    source_rgba = source.convert("RGBA")
    source_opaque_colors = {
        pixel[:3]
        for pixel in source_rgba.get_flattened_data()
        if pixel[3] == 255
    }
    source_alpha = {pixel[3] for pixel in source_rgba.get_flattened_data()}
    with Image.open(run_dir / "sprite-sheet-alpha.png") as opened:
        atlas = opened.convert("RGBA")
        atlas_opaque_colors = {
            pixel[:3]
            for pixel in atlas.get_flattened_data()
            if pixel[3] == 255
        }
        atlas_alpha = {pixel[3] for pixel in atlas.get_flattened_data()}
    assert atlas_opaque_colors <= source_opaque_colors
    assert atlas_alpha <= source_alpha


@pytest.mark.parametrize("asset_kind", ["tileset", "texture", "ui"])
def test_full_cell_asset_profiles_allow_edge_contact_and_complete_occupancy(
    tmp_path: Path,
    asset_kind: str,
) -> None:
    run_dir = tmp_path / asset_kind
    _write_run(
        run_dir,
        size=(32, 32),
        rectangle=(0, 0, 31, 31),
        asset_kind=asset_kind,
    )

    result = _compose(run_dir)

    assert result.returncode == 0, result.stdout + result.stderr


def test_sprite_profile_still_rejects_edge_contact_and_complete_occupancy(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "sprite"
    _write_run(run_dir, size=(32, 32), rectangle=(0, 0, 31, 31))

    result = _compose(run_dir)

    assert result.returncode != 0
    report = json.loads(
        (run_dir / "sprite-sheet-alpha.report.json").read_text(encoding="utf-8")
    )
    assert any("edge escape" in error for error in report["errors"])


def test_illustrated_curation_keeps_high_quality_resampling(tmp_path: Path) -> None:
    run_dir = tmp_path / "illustrated-curation"
    _write_run(
        run_dir,
        size=(32, 32),
        rectangle=(10, 10, 21, 21),
        style_preset="illustration",
    )
    _write_json(
        run_dir / "curation.json",
        {
            "version": 1,
            "kind": "sprite-gen-curation",
            "states": {
                "idle": {
                    "selected": [0],
                    "transforms": {"0": {"rotate": 17, "scale": 1.0}},
                }
            },
        },
    )

    result = _compose(run_dir)

    assert result.returncode == 0, result.stdout + result.stderr
    with Image.open(run_dir / "sprite-sheet-alpha.png") as opened:
        alpha_values = {
            pixel[3] for pixel in opened.convert("RGBA").get_flattened_data()
        }
    assert any(0 < alpha < 255 for alpha in alpha_values)


def test_output_formats_write_png_and_lossless_webp_with_manifest_hashes(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "formats"
    _write_run(
        run_dir,
        size=(8, 8),
        rectangle=(2, 2, 5, 5),
        output={"formats": ["png", "webp"]},
    )

    result = _compose(run_dir)

    assert result.returncode == 0, result.stdout + result.stderr
    png_path = run_dir / "sprite-sheet-alpha.png"
    webp_path = run_dir / "sprite-sheet-alpha.webp"
    assert png_path.is_file()
    assert webp_path.is_file()
    with Image.open(png_path) as png, Image.open(webp_path) as webp:
        assert webp.convert("RGBA").tobytes() == png.convert("RGBA").tobytes()
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["atlas_outputs"] == {
        "png": {
            "path": "sprite-sheet-alpha.png",
            "sha256": sha256(png_path.read_bytes()).hexdigest(),
            "size_bytes": png_path.stat().st_size,
            "lossless": True,
        },
        "webp": {
            "path": "sprite-sheet-alpha.webp",
            "sha256": sha256(webp_path.read_bytes()).hexdigest(),
            "size_bytes": webp_path.stat().st_size,
            "lossless": True,
        },
    }


def test_atlas_gutter_and_extrusion_keep_runtime_rects_on_cell_interiors(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "packing"
    _write_run(
        run_dir,
        size=(8, 8),
        rectangle=(0, 0, 7, 7),
        asset_kind="texture",
        output={
            "formats": ["png"],
            "atlas_gutter": 1,
            "atlas_extrusion": 2,
        },
    )

    result = _compose(run_dir)

    assert result.returncode == 0, result.stdout + result.stderr
    with Image.open(run_dir / "sprite-sheet-alpha.png") as opened:
        atlas = opened.convert("RGBA")
        assert atlas.size == (14, 14)
        assert atlas.getpixel((0, 7))[3] == 0
        assert atlas.getpixel((1, 7)) == atlas.getpixel((3, 7))
        assert atlas.getpixel((12, 7)) == atlas.getpixel((10, 7))
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["frame_layout"]["rows"]["idle"] == [
        {"x": 3, "y": 3, "w": 8, "h": 8}
    ]
    assert manifest["frame_layout"]["packing"] == {
        "atlas_gutter": 1,
        "atlas_extrusion": 2,
        "slotWidth": 14,
        "slotHeight": 14,
        "runtimeRects": "interior-cells",
        "extrusionMode": "edge-duplicate",
    }


def test_explicit_zero_padding_preserves_atlas_bytes_and_runtime_rects(
    tmp_path: Path,
) -> None:
    default_run = tmp_path / "default-packing"
    zero_run = tmp_path / "zero-packing"
    _write_run(default_run, size=(8, 8), rectangle=(2, 2, 5, 5))
    _write_run(
        zero_run,
        size=(8, 8),
        rectangle=(2, 2, 5, 5),
        output={
            "formats": ["png"],
            "atlas_gutter": 0,
            "atlas_extrusion": 0,
        },
    )

    default_result = _compose(default_run)
    zero_result = _compose(zero_run)

    assert default_result.returncode == 0, default_result.stdout + default_result.stderr
    assert zero_result.returncode == 0, zero_result.stdout + zero_result.stderr
    assert (default_run / "sprite-sheet-alpha.png").read_bytes() == (
        zero_run / "sprite-sheet-alpha.png"
    ).read_bytes()
    default_layout = json.loads(
        (default_run / "manifest.json").read_text(encoding="utf-8")
    )["frame_layout"]
    zero_layout = json.loads(
        (zero_run / "manifest.json").read_text(encoding="utf-8")
    )["frame_layout"]
    assert zero_layout == default_layout
    assert "packing" not in zero_layout


def test_vfx_metadata_propagates_to_curated_runtime_animation_row(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "vfx-runtime-metadata"
    request = _write_vfx_run(run_dir)
    _write_json(
        run_dir / "curation.json",
        {
            "version": 1,
            "kind": "sprite-gen-curation",
            "states": {"burst": {"selected": [2, 0, 3]}},
        },
    )

    result = _compose(run_dir)

    assert result.returncode == 0, result.stdout + result.stderr
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    expected_vfx = request["states"]["burst"]["vfx"] | {
        "phase_sequence": ["decay", "buildup", "hold"]
    }
    assert manifest["animation"]["rows"]["burst"] == {
        "row": 0,
        "frames": 3,
        "fps": 12,
        "loop": False,
        "vfx": expected_vfx,
    }
