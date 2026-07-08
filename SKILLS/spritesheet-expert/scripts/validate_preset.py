#!/usr/bin/env python3
import json
import re
import sys
from pathlib import Path


ROW_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
RATIO_KEYS = {
    "guide_height_ratio",
    "start_height_vs_reference",
    "target_height_vs_reference",
    "min_height_vs_reference",
    "min_width_vs_reference",
    "min_head_width_vs_reference",
    "min_upper_width_vs_reference",
    "max_height_vs_reference",
    "max_height_vs_idle",
    "arc_peak_ratio",
    "airborne_bottom_ratio",
}
BACKGROUND_REMOVAL_METHODS = {"none", "chroma", "rembg", "ben2", "auto"}
ART_DIRECTION_MODES = {"none", "pixel-art"}
ART_PROFILES = {
    "auto",
    "pixel-core",
    "pixel-character",
    "pixel-motion",
    "pixel-sideview",
    "pixel-topdown",
    "pixel-isometric",
    "pixel-texture",
    "pixel-combat",
    "pixel-items-ui",
    "pixel-vfx",
    "pixel-shmup",
    "pixel-tiny",
    "pixel-environment",
}


def fail(message):
    print(f"ERROR: {message}", file=sys.stderr)
    return 1


def validate_pose_geometry(preset_id, row_id, value):
    if value in (False, "none", None):
        return None
    if not isinstance(value, dict):
        return f"{preset_id}/{row_id}: pose_geometry must be an object, false, or 'none'"
    kind = value.get("kind")
    if kind is not None and (not isinstance(kind, str) or not ROW_ID.match(kind)):
        return f"{preset_id}/{row_id}: pose_geometry.kind must be a slug string"
    grounded = value.get("grounded")
    if grounded is not None and not isinstance(grounded, bool):
        return f"{preset_id}/{row_id}: pose_geometry.grounded must be boolean"
    for key in RATIO_KEYS:
        if key in value and (isinstance(value[key], bool) or not isinstance(value[key], (int, float)) or value[key] <= 0):
            return f"{preset_id}/{row_id}: pose_geometry.{key} must be positive number"
    return None


def validate_background_removal(preset_id, value):
    if value in (None, False):
        return None
    if not isinstance(value, dict):
        return f"{preset_id}: background_removal must be an object"
    method = value.get("method")
    if method not in BACKGROUND_REMOVAL_METHODS:
        return f"{preset_id}: background_removal.method must be none, chroma, rembg, ben2, or auto"
    model = value.get("model")
    if model is not None and (not isinstance(model, str) or not model.strip()):
        return f"{preset_id}: background_removal.model must be a non-empty string"
    device = value.get("device")
    if device is not None and (not isinstance(device, str) or not device.strip()):
        return f"{preset_id}: background_removal.device must be a non-empty string"
    alpha_matting = value.get("alpha_matting")
    if alpha_matting is not None and not isinstance(alpha_matting, bool):
        return f"{preset_id}: background_removal.alpha_matting must be boolean"
    return None


def validate_art_direction(preset_id, preset):
    mode = preset.get("art_direction")
    if mode is not None and mode not in ART_DIRECTION_MODES:
        return f"{preset_id}: art_direction must be none or pixel-art"
    profiles = preset.get("art_profiles")
    if profiles is None:
        return None
    if not isinstance(profiles, list) or not profiles:
        return f"{preset_id}: art_profiles must be a non-empty list"
    for profile in profiles:
        if profile not in ART_PROFILES:
            return f"{preset_id}: unknown art profile {profile!r}"
    return None


def main(argv):
    path = Path(argv[1] if len(argv) > 1 else Path(__file__).parents[1] / "references" / "presets.json")
    data = json.loads(path.read_text(encoding="utf-8-sig"))

    if data.get("version") != 1:
        return fail("version must be 1")
    presets = data.get("presets")
    if not isinstance(presets, dict) or not presets:
        return fail("presets must be a non-empty object")

    for preset_id, preset in presets.items():
        if not ROW_ID.match(preset_id):
            return fail(f"{preset_id}: invalid preset id")
        asset_kind = preset.get("asset_kind", "sprite")
        if not isinstance(asset_kind, str) or not ROW_ID.match(asset_kind):
            return fail(f"{preset_id}: asset_kind must be a slug string")
        extraction_mode = preset.get("extraction_mode")
        if extraction_mode is not None and extraction_mode not in ["components", "slots"]:
            return fail(f"{preset_id}: extraction_mode must be components or slots")
        background_error = validate_background_removal(preset_id, preset.get("background_removal"))
        if background_error:
            return fail(background_error)
        art_error = validate_art_direction(preset_id, preset)
        if art_error:
            return fail(art_error)
        cell = preset.get("cell") or {}
        width = cell.get("width")
        height = cell.get("height")
        columns = preset.get("columns")
        rows = preset.get("rows")
        if not all(isinstance(value, int) and value > 0 for value in [width, height, columns]):
            return fail(f"{preset_id}: cell width/height and columns must be positive ints")
        if not isinstance(rows, list):
            return fail(f"{preset_id}: rows must be a list")
        if not rows and not preset.get("requires_user_rows"):
            return fail(f"{preset_id}: rows cannot be empty")

        seen = set()
        for row in rows:
            row_id = row.get("id")
            frames = row.get("frames")
            durations = row.get("durations_ms")
            if not isinstance(row_id, str) or not ROW_ID.match(row_id):
                return fail(f"{preset_id}: invalid row id {row_id!r}")
            if row_id in seen:
                return fail(f"{preset_id}: duplicate row id {row_id}")
            seen.add(row_id)
            if not isinstance(frames, int) or frames < 1:
                return fail(f"{preset_id}/{row_id}: frames must be positive int")
            if frames > columns:
                return fail(f"{preset_id}/{row_id}: frames exceed columns")
            if durations is not None:
                if not isinstance(durations, list) or len(durations) != frames:
                    return fail(f"{preset_id}/{row_id}: durations_ms length must equal frames")
                if not all(isinstance(ms, int) and ms > 0 for ms in durations):
                    return fail(f"{preset_id}/{row_id}: durations_ms must contain positive ints")
            pose_error = validate_pose_geometry(preset_id, row_id, row.get("pose_geometry"))
            if pose_error:
                return fail(pose_error)

    print(f"OK: {len(presets)} presets in {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
