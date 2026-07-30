#!/usr/bin/env python3
"""Tiny end-to-end smoke for spritesheet-expert scripts."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

from prepare_sprite_run import row_prompt, state_motion_phases, state_pose_geometry, wants_motion_phase_guides


NEUTRAL_GRAY_RGBA = (128, 128, 128, 255)


def make_strip(path: Path, frames: int, cell: int, color: tuple[int, int, int]) -> None:
    image = Image.new("RGBA", (frames * cell, cell), NEUTRAL_GRAY_RGBA)
    draw = ImageDraw.Draw(image)
    for index in range(frames):
        left = index * cell + 10 + index
        top = 12 + (index % 2) * 4
        draw.rounded_rectangle((left, top, left + 22, top + 24), radius=3, fill=color + (255,))
    image.save(path)


def make_full_cell_strip(path: Path, frames: int, cell: int) -> None:
    image = Image.new("RGBA", (frames * cell, cell), NEUTRAL_GRAY_RGBA)
    draw = ImageDraw.Draw(image)
    for index in range(frames):
        left = index * cell
        draw.rectangle((left, 0, left + cell - 1, cell - 1), fill=(50 + index * 70, 90, 150, 255))
    image.save(path)


def make_blue_background_strip(path: Path, frames: int, cell: int) -> None:
    image = Image.new("RGBA", (frames * cell, cell), (20, 80, 210, 255))
    draw = ImageDraw.Draw(image)
    for index in range(frames):
        left = index * cell + 12
        draw.ellipse((left, 10, left + 24, 36), fill=(240, 80, 60, 255))
        draw.rectangle((left + 8, 28, left + 16, 50), fill=(240, 80, 60, 255))
    image.save(path)


def make_internal_chroma_patch_strip(path: Path, cell: int) -> None:
    image = Image.new("RGBA", (cell, cell), (255, 0, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((12, 10, 35, 38), fill=(240, 120, 40, 255))
    draw.rectangle((20, 20, 26, 26), fill=(255, 0, 255, 255))
    image.save(path)


def make_pose_strip(path: Path, frames: int, cell: int, height: int, width: int, bottom: int) -> None:
    image = Image.new("RGBA", (frames * cell, cell), NEUTRAL_GRAY_RGBA)
    draw = ImageDraw.Draw(image)
    for index in range(frames):
        center_x = index * cell + cell // 2
        left = center_x - width // 2
        top = bottom - height
        draw.rectangle((left, top, left + width, bottom), fill=(40, 120, 240, 255))
        draw.ellipse((center_x - 6, top - 10, center_x + 6, top + 2), fill=(240, 190, 120, 255))
    image.save(path)


def make_pose_sequence_strip(path: Path, cell: int, heights: list[int], widths: list[int], bottom: int) -> None:
    image = Image.new("RGBA", (len(heights) * cell, cell), NEUTRAL_GRAY_RGBA)
    draw = ImageDraw.Draw(image)
    for index, (height, width) in enumerate(zip(heights, widths)):
        center_x = index * cell + cell // 2
        left = center_x - width // 2
        top = bottom - height
        draw.rectangle((left, top, left + width, bottom), fill=(40, 120, 240, 255))
        draw.ellipse((center_x - 6, top - 10, center_x + 6, top + 2), fill=(240, 190, 120, 255))
    image.save(path)


def make_motion_frame(path: Path, phase: int, frozen: bool = False) -> None:
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    phase = 0 if frozen else phase % 4
    body_y = 17 + (phase % 2)
    draw.rectangle((27, body_y, 37, body_y + 22), fill=(40, 120, 240, 255))
    draw.ellipse((26, body_y - 10, 38, body_y + 2), fill=(240, 190, 120, 255))
    if phase == 0:
        legs = [((30, body_y + 22), (20, 57)), ((35, body_y + 22), (43, 54))]
        arms = [((27, body_y + 7), (19, body_y + 23)), ((37, body_y + 7), (45, body_y + 18))]
    elif phase == 1:
        legs = [((30, body_y + 22), (29, 57)), ((35, body_y + 22), (36, 54))]
        arms = [((27, body_y + 7), (24, body_y + 23)), ((37, body_y + 7), (41, body_y + 18))]
    elif phase == 2:
        legs = [((30, body_y + 22), (43, 57)), ((35, body_y + 22), (21, 54))]
        arms = [((27, body_y + 7), (45, body_y + 23)), ((37, body_y + 7), (19, body_y + 18))]
    else:
        legs = [((30, body_y + 22), (34, 57)), ((35, body_y + 22), (30, 54))]
        arms = [((27, body_y + 7), (41, body_y + 23)), ((37, body_y + 7), (24, body_y + 18))]
    for start, end in legs:
        draw.line((start, end), fill=(20, 60, 150, 255), width=4)
    for start, end in arms:
        draw.line((start, end), fill=(240, 190, 120, 255), width=3)
    image.save(path)


def run(script: str, *args: str, env: dict[str, str] | None = None) -> None:
    scripts = Path(__file__).resolve().parent
    subprocess.check_call([sys.executable, str(scripts / script), *args], env=env)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="sprite-atlas-smoke-") as tmp:
        run_dir = Path(tmp) / "run"
        (run_dir / "raw").mkdir(parents=True)
        request = {
            "version": 1,
            "kind": "sprite-gen-request",
            "engine": "component-row",
            "character": {"id": "smoke", "description": "synthetic", "base_image": None},
            "cell": {"shape": "square", "width": 48, "height": 48, "safe_margin_x": 4, "safe_margin_y": 4, "size": 48, "safe_margin": 4},
            "chroma_key": {"name": "legacy-magenta", "hex": "#FF00FF", "rgb": [255, 0, 255]},
            "generation_background": {"family": "neutral", "name": "gray", "hex": "#808080", "rgb": [128, 128, 128]},
            "background_removal": {"method": "auto", "model": "birefnet-general", "source_family": "neutral", "alpha_matting": True, "post_rembg_chroma_cleanup": False},
            "states": {
                "idle": {"frames": 3, "fps": 4, "loop": True, "action": "synthetic idle"},
                "attack": {"frames": 2, "fps": 8, "loop": False, "action": "synthetic attack"},
            },
            "style": "synthetic",
            "style_preset": "pixel-art",
            "motion_phase_guides": False,
            "art_direction": {"mode": "pixel-art", "profiles": ["auto"]},
        }
        (run_dir / "sprite-request.json").write_text(json.dumps(request, indent=2) + "\n", encoding="utf-8")
        make_strip(run_dir / "raw" / "idle.png", 3, 48, (40, 120, 240))
        make_strip(run_dir / "raw" / "attack.png", 2, 48, (240, 120, 40))

        run("extract_sprite_row_frames.py", "--run-dir", str(run_dir))
        run("promote_identity_anchor.py", "--run-dir", str(run_dir), "--state", "idle", "--frame", "0")
        assert (run_dir / "references" / "identity-anchor.png").is_file()
        anchor_meta = json.loads((run_dir / "references" / "identity-anchor.json").read_text(encoding="utf-8"))
        assert anchor_meta["state"] == "idle"
        run("compose_sprite_atlas.py", "--run-dir", str(run_dir), "--min-used-pixels", "100")
        run("build_preview_workbench.py", "--run-dir", str(run_dir))
        assert (run_dir / "qa" / "preview-workbench" / "index.html").is_file()
        assert (run_dir / "qa" / "preview-workbench" / "workbench.evidence.json").is_file()

        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["frame_layout"]["sheetWidth"] == 144
        assert manifest["frame_layout"]["sheetHeight"] == 96
        assert len(manifest["frame_layout"]["rows"]["idle"]) == 3
        assert len(manifest["frame_layout"]["rows"]["attack"]) == 2
        assert state_motion_phases("walk-down", 8)
        assert state_motion_phases("walk-forward", 8)
        assert not state_motion_phases("idle-down", 4)
        assert wants_motion_phase_guides({}, {"walk-down": {"frames": 8}}, False)
        assert not wants_motion_phase_guides({"motion_phase_guides": False}, {"walk-down": {"frames": 8}}, True)
        prompt = row_prompt(
            request
            | {
                "motion_phase_guides": True,
                "animation_workflows": ["auto"],
            },
            "walk-down",
            {"frames": 8, "fps": 6, "loop": True, "action": "walk"},
        )
        assert "full-body locomotion row" in prompt
        assert "Never keep both feet leaning the same way" in prompt
        assert "clear silhouette and line of action" in prompt
        assert "center of mass" in prompt
        assert "Pixel-art direction profiles" in prompt
        assert "pixel-motion" in prompt
        assert "Energy beats smoothness" in prompt
        assert "Animation workflow requirements" in prompt
        assert "topdown-locomotion" in prompt
        assert "direction strategy" in prompt
        jump_prompt = row_prompt(request, "jump", {"frames": 4, "fps": 8, "loop": False, "action": "jump arc"})
        assert "must not become larger than idle" in jump_prompt
        assert "orange baseline and arc pose boxes" in jump_prompt
        assert "responsive-jump" in jump_prompt
        assert "avoid long anticipation" in jump_prompt
        fighter_prompt = row_prompt(
            request | {"preset": {"id": "fighting-game-character", "camera": "side"}},
            "punch",
            {"frames": 6, "fps": 10, "loop": False, "action": "standing punch"},
        )
        assert "guard/startup, fist extension/contact" in fighter_prompt
        assert "fighting/combat state" in fighter_prompt
        assert "pixel-combat" in fighter_prompt
        assert "visual range should match the intended hitbox" in fighter_prompt
        assert "combat-quick-strike" in fighter_prompt
        assert "little or no windup" in fighter_prompt
        knockdown_geometry = state_pose_geometry(
            "knockdown",
            {"frames": 10, "fps": 10, "loop": False, "action": "reaction: force direction, balance loss, fall/contact, final down pose"},
        )
        assert knockdown_geometry and knockdown_geometry["kind"] == "knockdown"

        asset_run = Path(tmp) / "asset-run"
        (asset_run / "raw").mkdir(parents=True)
        asset_request = {
            "version": 1,
            "kind": "sprite-gen-request",
            "engine": "component-row",
            "asset_kind": "texture",
            "extraction_mode": "slots",
            "character": {"id": "materials", "description": "synthetic materials", "base_image": None},
            "cell": {"shape": "square", "width": 32, "height": 32, "safe_margin_x": 0, "safe_margin_y": 0, "size": 32, "safe_margin": 0},
            "chroma_key": {"name": "legacy-magenta", "hex": "#FF00FF", "rgb": [255, 0, 255]},
            "generation_background": {"family": "neutral", "name": "gray", "hex": "#808080", "rgb": [128, 128, 128]},
            "background_removal": {"method": "none", "model": "birefnet-general", "source_family": "neutral", "alpha_matting": False, "post_rembg_chroma_cleanup": False},
            "states": {"stone": {"frames": 2, "fps": 1, "loop": False, "action": "stone material samples"}},
            "style": "synthetic texture",
            "style_preset": "custom",
            "motion_phase_guides": False,
            "art_direction": {"mode": "pixel-art", "profiles": ["auto"]},
        }
        (asset_run / "sprite-request.json").write_text(json.dumps(asset_request, indent=2) + "\n", encoding="utf-8")
        make_full_cell_strip(asset_run / "raw" / "stone.png", 2, 32)
        run("extract_sprite_row_frames.py", "--run-dir", str(asset_run), "--min-used-pixels", "100")
        asset_manifest = json.loads((asset_run / "frames" / "frames-manifest.json").read_text(encoding="utf-8"))
        assert asset_manifest["rows"][0]["method"] == "slots-explicit"
        run("compose_sprite_atlas.py", "--run-dir", str(asset_run), "--min-used-pixels", "100")
        asset_output = json.loads((asset_run / "manifest.json").read_text(encoding="utf-8"))
        assert asset_output["asset_kind"] == "texture"
        asset_prompt = row_prompt(asset_request, "stone", asset_request["states"]["stone"])
        assert "full-body" not in asset_prompt
        assert "Asset kind: texture" in asset_prompt
        assert "consistent texel density" in asset_prompt
        assert "flat orthographic material sample" in asset_prompt
        assert "pixel-texture" in asset_prompt
        assert "3x3 review" in asset_prompt

        fake_rembg_dir = Path(tmp) / "fake-rembg"
        fake_rembg_dir.mkdir()
        (fake_rembg_dir / "rembg.py").write_text(
            """
import io
from PIL import Image

def new_session(model_name=None):
    return {"model_name": model_name}

def remove(data, session=None, alpha_matting=False, force_return_bytes=False, **_kwargs):
    image = Image.open(io.BytesIO(data)).convert("RGBA")
    pixels = image.load()
    for y in range(image.height):
        for x in range(image.width):
            red, green, blue, alpha = pixels[x, y]
            if blue > 120 and red < 100:
                pixels[x, y] = (0, 0, 0, 0)
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()
""".lstrip(),
            encoding="utf-8",
        )
        rembg_run = Path(tmp) / "rembg-run"
        (rembg_run / "raw").mkdir(parents=True)
        rembg_request = {
            "version": 1,
            "kind": "sprite-gen-request",
            "engine": "component-row",
            "asset_kind": "sprite",
            "extraction_mode": "components",
            "background_removal": {"method": "rembg", "model": "birefnet-general-lite", "alpha_matting": True},
            "character": {"id": "cutout", "description": "synthetic non-chroma background", "base_image": None},
            "cell": {"shape": "square", "width": 48, "height": 48, "safe_margin_x": 4, "safe_margin_y": 4},
            "chroma_key": {"name": "magenta", "hex": "#FF00FF", "rgb": [255, 0, 255]},
            "states": {"idle": {"frames": 2, "fps": 4, "loop": True, "action": "standing idle reference"}},
            "style": "synthetic",
            "style_preset": "custom",
            "motion_phase_guides": False,
        }
        (rembg_run / "sprite-request.json").write_text(json.dumps(rembg_request, indent=2) + "\n", encoding="utf-8")
        make_blue_background_strip(rembg_run / "raw" / "idle.png", 2, 48)
        rembg_env = dict(os.environ)
        rembg_env["PYTHONPATH"] = str(fake_rembg_dir) + os.pathsep + rembg_env.get("PYTHONPATH", "")
        run("extract_sprite_row_frames.py", "--run-dir", str(rembg_run), "--min-used-pixels", "100", env=rembg_env)
        rembg_manifest = json.loads((rembg_run / "frames" / "frames-manifest.json").read_text(encoding="utf-8"))
        assert rembg_manifest["background_removal"]["method"] == "rembg"
        assert rembg_manifest["rows"][0]["background_method"] == "rembg"

        irregular_import = Path(tmp) / "irregular-import"
        run(
            "unpack_atlas_run.py",
            "--atlas",
            str(rembg_run / "raw" / "idle.png"),
            "--out-dir",
            str(irregular_import),
            "--background-removal",
            "rembg",
            "--states",
            "idle",
            "--diagnostic",
            env=rembg_env,
        )
        unpack_source = json.loads((irregular_import / "unpack-source.json").read_text(encoding="utf-8"))
        assert unpack_source["layout_source"] == "auto-detect"
        assert unpack_source["background_method"] == "rembg"
        assert (irregular_import / "qa" / "preprocessed-atlas-alpha.png").is_file()
        assert (irregular_import / "qa" / "segmentation-overlay.png").is_file()
        segmentation_report = json.loads((irregular_import / "qa" / "segmentation-report.json").read_text(encoding="utf-8"))
        assert segmentation_report["background_method"] == "rembg"
        assert segmentation_report["rows"][0]["state"] == "idle"
        assert segmentation_report["rows"][0]["frames"] == 2

        states_file = Path(tmp) / "states-bom.json"
        states_file.write_bytes(
            b"\xef\xbb\xbf"
            + json.dumps(
                {
                    "terrain": {
                        "frames": 4,
                        "fps": 1,
                        "loop": False,
                        "action": "custom modular terrain tiles",
                        "asset_labels": [
                            "grass-fill",
                            "dirt-fill",
                            "grass-edge",
                            "grass-corner",
                        ],
                        "catalog": {
                            "role": "terrain-tile",
                            "collision_role": "solid",
                        },
                    }
                }
            ).encode("utf-8")
        )
        custom_request_path = Path(tmp) / "custom-asset-request.json"
        run("preset_to_request.py", "custom-asset-atlas", "--out", str(custom_request_path), "--states-file", str(states_file))
        custom_request = json.loads(custom_request_path.read_text(encoding="utf-8"))
        assert custom_request["asset_kind"] == "asset"
        assert custom_request["extraction_mode"] == "slots"
        assert custom_request["art_direction"]["profiles"] == ["auto"]
        assert list(custom_request["states"]) == ["terrain"]

        custom_style_states = Path(tmp) / "custom-style-states.json"
        custom_style_states.write_text(json.dumps({"punch": {"frames": 4, "fps": 8, "loop": False, "action": "arcade punch"}}), encoding="utf-8")
        custom_style_request_path = Path(tmp) / "custom-style-request.json"
        run(
            "preset_to_request.py", "custom-atlas",
            "--style-preset", "custom",
            "--style", "inked chunky pixel fighter",
            "--art-profile", "pixel-combat",
            "--out", str(custom_style_request_path),
            "--states-file", str(custom_style_states),
        )
        custom_style_request = json.loads(custom_style_request_path.read_text(encoding="utf-8"))
        assert custom_style_request["art_direction"]["mode"] == "pixel-art"
        assert custom_style_request["art_direction"]["profiles"] == ["auto", "pixel-combat"]

        illustration_request_path = Path(tmp) / "platformer-illustration-request.json"
        run("preset_to_request.py", "platformer-character", "--style-preset", "illustration", "--out", str(illustration_request_path))
        illustration_request = json.loads(illustration_request_path.read_text(encoding="utf-8"))
        assert illustration_request["art_direction"]["mode"] == "none"

        micro_request_path = Path(tmp) / "platformer-micro-request.json"
        run("preset_to_request.py", "platformer-character", "--out", str(micro_request_path), "--frame-budget", "micro")
        micro_request = json.loads(micro_request_path.read_text(encoding="utf-8"))
        assert micro_request["frame_budget"] == "micro"
        assert micro_request["art_direction"]["profiles"] == ["pixel-core", "pixel-character", "pixel-motion", "pixel-sideview"]
        assert micro_request["states"]["idle"]["frames"] == 2
        assert micro_request["states"]["run"]["frames"] == 4
        assert micro_request["states"]["attack"]["frames"] == 3
        assert micro_request["states"]["death"]["frames"] == 4
        prepared_run = Path(tmp) / "prepared-platformer"
        run("prepare_sprite_run.py", "--out-dir", str(prepared_run), "--character-id", "hero", "--request", str(micro_request_path), "--force")
        prepared_request = json.loads((prepared_run / "sprite-request.json").read_text(encoding="utf-8"))
        assert prepared_request["states"]["jump"]["pose_geometry"]["kind"] == "jump"
        assert "orange baseline and arc pose boxes" in (prepared_run / "prompts" / "jump.txt").read_text(encoding="utf-8")
        prepared_art_direction = json.loads((prepared_run / "references" / "art-direction.json").read_text(encoding="utf-8"))
        assert prepared_art_direction["workflow_reference"] == "references/pixel-animation-workflows.md"
        assert prepared_art_direction["rows"]["run"]["profiles"] == ["pixel-core", "pixel-character", "pixel-motion", "pixel-sideview"]
        assert prepared_art_direction["rows"]["run"]["animation_workflows"] == ["sideview-locomotion"]
        assert prepared_art_direction["rows"]["jump"]["animation_workflows"] == ["responsive-jump"]
        assert "pixel-sideview" in (prepared_run / "prompts" / "run.txt").read_text(encoding="utf-8")

        asset_budget_path = Path(tmp) / "texture-micro-request.json"
        run("preset_to_request.py", "texture-pack", "--out", str(asset_budget_path), "--frame-budget", "micro")
        asset_budget = json.loads(asset_budget_path.read_text(encoding="utf-8"))
        assert "frame_budget" not in asset_budget
        assert asset_budget["states"]["stone"]["frames"] == 6

        chroma_run = Path(tmp) / "chroma-run"
        (chroma_run / "raw").mkdir(parents=True)
        chroma_request = {
            "version": 1,
            "kind": "sprite-gen-request",
            "engine": "component-row",
            "asset_kind": "sprite",
            "extraction_mode": "components",
            "character": {"id": "patch", "description": "internal chroma preservation", "base_image": None},
            "cell": {"shape": "square", "width": 48, "height": 48, "safe_margin_x": 4, "safe_margin_y": 4},
            "chroma_key": {"name": "magenta", "hex": "#FF00FF", "rgb": [255, 0, 255]},
            "states": {"idle": {"frames": 1, "fps": 1, "loop": False, "action": "single sprite"}},
            "style": "synthetic",
            "style_preset": "custom",
        }
        (chroma_run / "sprite-request.json").write_text(json.dumps(chroma_request, indent=2) + "\n", encoding="utf-8")
        make_internal_chroma_patch_strip(chroma_run / "raw" / "idle.png", 48)
        run("extract_sprite_row_frames.py", "--run-dir", str(chroma_run), "--min-used-pixels", "100")
        with Image.open(chroma_run / "frames" / "idle" / "frame-0.png") as opened:
            patched = opened.convert("RGBA")
        bbox = patched.getbbox()
        assert bbox
        alpha_inside = patched.getchannel("A").crop(bbox).histogram()[0]
        assert alpha_inside == 0

        pose_run = Path(tmp) / "pose-run"
        (pose_run / "raw").mkdir(parents=True)
        pose_request = {
            "version": 1,
            "kind": "sprite-gen-request",
            "engine": "component-row",
            "asset_kind": "sprite",
            "extraction_mode": "components",
            "preset": {"id": "synthetic-fighter", "camera": "side"},
            "character": {"id": "jumper", "description": "pose scale check", "base_image": None},
            "cell": {"shape": "square", "width": 64, "height": 64, "safe_margin_x": 4, "safe_margin_y": 4},
            "chroma_key": {"name": "legacy-magenta", "hex": "#FF00FF", "rgb": [255, 0, 255]},
            "generation_background": {"family": "neutral", "name": "gray", "hex": "#808080", "rgb": [128, 128, 128]},
            "background_removal": {"method": "auto", "model": "birefnet-general", "source_family": "neutral", "alpha_matting": True, "post_rembg_chroma_cleanup": False},
            "states": {
                "idle": {"frames": 3, "fps": 4, "loop": True, "action": "standing idle reference"},
                "run": {"frames": 4, "fps": 8, "loop": True, "action": "side run full-body locomotion cycle"},
                "crouch": {"frames": 3, "fps": 6, "loop": False, "action": "crouch lower while feet stay planted"},
                "jump": {"frames": 3, "fps": 8, "loop": False, "action": "jump arc through body position only"},
            },
            "style": "synthetic",
            "style_preset": "custom",
            "motion_phase_guides": False,
        }
        (pose_run / "sprite-request.json").write_text(json.dumps(pose_request, indent=2) + "\n", encoding="utf-8")
        make_pose_strip(pose_run / "raw" / "idle.png", 3, 64, height=36, width=16, bottom=56)
        make_pose_strip(pose_run / "raw" / "run.png", 4, 64, height=44, width=20, bottom=58)
        make_pose_sequence_strip(pose_run / "raw" / "crouch.png", 64, heights=[36, 28, 23], widths=[16, 19, 20], bottom=56)
        make_pose_strip(pose_run / "raw" / "jump.png", 3, 64, height=36, width=18, bottom=56)
        run("extract_sprite_row_frames.py", "--run-dir", str(pose_run), "--min-used-pixels", "100")
        pose_manifest = json.loads((pose_run / "frames" / "frames-manifest.json").read_text(encoding="utf-8"))
        reference_height = pose_manifest["sprite_registration"]["reference_height"]
        reference_width = pose_manifest["sprite_registration"]["reference_width"]
        reference_head = pose_manifest["sprite_registration"]["reference_head_width"]
        assert 44 <= reference_height <= 50
        assert 15 <= reference_width <= 20
        assert reference_head > 0
        rows = {row["state"]: row for row in pose_manifest["rows"]}
        assert rows["run"]["pose_geometry"]["kind"] == "grounded-locomotion"
        assert all(record["bottom_y"] == 60 for record in rows["run"]["frame_records"])
        crouch_records = rows["crouch"]["frame_records"]
        crouch_heights = [record["bbox"][3] - record["bbox"][1] for record in crouch_records]
        crouch_widths = [record["bbox"][2] - record["bbox"][0] for record in crouch_records]
        crouch_ratios = [record["height_vs_reference"] for record in crouch_records]
        crouch_width_ratios = [record["width_vs_reference"] for record in crouch_records]
        crouch_head_ratios = [record["head_width_vs_reference"] for record in crouch_records]
        crouch_expected = [record["expected_height_vs_reference"] for record in crouch_records]
        jump_records = rows["jump"]["frame_records"]
        jump_heights = [record["bbox"][3] - record["bbox"][1] for record in jump_records]
        jump_bottoms = [record["bottom_y"] for record in jump_records]
        jump_head_ratios = [record["head_width_vs_reference"] for record in jump_records]
        assert crouch_ratios[0] > crouch_ratios[-1]
        assert crouch_expected[0] > crouch_expected[-1]
        assert crouch_heights[-1] <= round(reference_height * 0.78) + 1
        assert crouch_width_ratios[-1] >= 0.78
        assert crouch_head_ratios[-1] >= 0.84
        assert crouch_widths[-1] >= round(reference_width * 0.78)
        assert all(record["bottom_y"] == 60 for record in rows["crouch"]["frame_records"])
        assert min(jump_head_ratios) >= 0.86
        assert max(jump_heights) <= round(reference_height * 1.12) + 1
        assert max(jump_bottoms) - min(jump_bottoms) >= 8
        run("preview_animation.py", "--run-dir", str(pose_run))
        with Image.open(pose_run / "qa" / "jump-contact.png") as opened:
            preview = opened.convert("RGB")
        preview_bytes = preview.tobytes()
        orange = bytes((245, 158, 11))
        assert any(preview_bytes[index : index + 3] == orange for index in range(0, len(preview_bytes), 3))

        motion_run = Path(tmp) / "motion-run"
        motion_state = motion_run / "frames" / "run"
        motion_state.mkdir(parents=True)
        motion_files = []
        for index in range(4):
            frame_path = motion_state / f"frame-{index}.png"
            make_motion_frame(frame_path, index)
            motion_files.append(str(frame_path.relative_to(motion_run)))
        motion_request = {
            "version": 1,
            "kind": "sprite-gen-request",
            "engine": "component-row",
            "asset_kind": "sprite",
            "character": {"id": "runner", "description": "motion check", "base_image": None},
            "cell": {"shape": "square", "width": 64, "height": 64, "safe_margin_x": 4, "safe_margin_y": 4},
            "chroma_key": {"name": "magenta", "hex": "#FF00FF", "rgb": [255, 0, 255]},
            "states": {"run": {"frames": 4, "fps": 8, "loop": True, "action": "side run full-body locomotion cycle"}},
        }
        (motion_run / "sprite-request.json").write_text(json.dumps(motion_request, indent=2) + "\n", encoding="utf-8")
        (motion_run / "frames" / "frames-manifest.json").write_text(
            json.dumps({
                "ok": True,
                "engine": "component-row",
                "run_dir": str(motion_run),
                "cell": motion_request["cell"],
                "rows": [{"state": "run", "frames": 4, "method": "synthetic", "files": motion_files, "ok": True}],
                "errors": [],
                "warnings": [],
            }, indent=2) + "\n",
            encoding="utf-8",
        )
        run("check_motion_variation.py", "--run-dir", str(motion_run))

        frozen_run = Path(tmp) / "frozen-motion-run"
        frozen_state = frozen_run / "frames" / "run"
        frozen_state.mkdir(parents=True)
        frozen_files = []
        for index in range(4):
            frame_path = frozen_state / f"frame-{index}.png"
            make_motion_frame(frame_path, index, frozen=True)
            frozen_files.append(str(frame_path.relative_to(frozen_run)))
        (frozen_run / "sprite-request.json").write_text(json.dumps(motion_request | {"character": {"id": "frozen"}}, indent=2) + "\n", encoding="utf-8")
        (frozen_run / "frames" / "frames-manifest.json").write_text(
            json.dumps({
                "ok": True,
                "engine": "component-row",
                "run_dir": str(frozen_run),
                "cell": motion_request["cell"],
                "rows": [{"state": "run", "frames": 4, "method": "synthetic", "files": frozen_files, "ok": True}],
                "errors": [],
                "warnings": [],
            }, indent=2) + "\n",
            encoding="utf-8",
        )
        scripts = Path(__file__).resolve().parent
        frozen = subprocess.run([sys.executable, str(scripts / "check_motion_variation.py"), "--run-dir", str(frozen_run)])
        assert frozen.returncode != 0
        print(f"OK: smoke pipeline {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
