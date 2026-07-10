#!/usr/bin/env python3
import json
import re
import sys
from pathlib import Path


ROW_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
ASSET_LABEL = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
FRAME_SEMANTICS = {
    "animation",
    "effects",
    "variants",
    "tiles",
    "still-assets",
    "seamless-textures",
    "user-defined",
}
TEMPORAL_FRAME_SEMANTICS = {"animation", "effects"}
STATIC_FRAME_SEMANTICS = {
    "variants",
    "tiles",
    "still-assets",
    "seamless-textures",
}
ANIMATION_WORKFLOWS = {
    "idle-breath",
    "fighting-stance-idle",
    "sideview-locomotion",
    "topdown-locomotion",
    "combat-quick-strike",
    "combat-power-strike",
    "topdown-weapon-attack",
    "responsive-jump",
    "hit-reaction-knockdown",
    "run-gun-layered-motion",
    "vfx-buildup-peak-decay",
    "water-loop",
    "wind-ambient-loop",
    "pickup-feedback",
    "tiny-motion",
}
PROP_STRATEGY_CLASSES = {
    "compact_prop",
    "wide_or_long_object",
    "tall_or_large_object",
    "collision_bearing_object",
    "tileset_or_strip_piece",
}
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


def validate_workflows(preset_id, row_id, value):
    if not isinstance(value, list):
        return f"{preset_id}/{row_id}: animation_workflows must be a list"
    unknown = sorted(set(value) - ANIMATION_WORKFLOWS)
    if unknown:
        return (
            f"{preset_id}/{row_id}: unknown animation workflow(s): "
            f"{', '.join(unknown)}"
        )
    if len(value) != len(set(value)):
        return f"{preset_id}/{row_id}: animation_workflows cannot contain duplicates"
    return None


def validate_slot_metadata(preset_id, row_id, row, frames, asset_kind, seen_labels):
    labels = row.get("asset_labels")
    if not isinstance(labels, list) or len(labels) != frames:
        return f"{preset_id}/{row_id}: asset_labels must contain one label per frame"
    for label in labels:
        if not isinstance(label, str) or not ASSET_LABEL.match(label):
            return f"{preset_id}/{row_id}: invalid asset_labels entry {label!r}"
        if label in seen_labels:
            return f"{preset_id}/{row_id}: duplicate asset label {label!r}"
        seen_labels.add(label)
    catalog = row.get("catalog")
    if not isinstance(catalog, dict):
        return f"{preset_id}/{row_id}: catalog metadata must be an object"
    category = catalog.get("category")
    if not isinstance(category, str) or not category.strip():
        return f"{preset_id}/{row_id}: catalog.category must be a non-empty string"
    pivot = catalog.get("pivot")
    if (
        not isinstance(pivot, list)
        or len(pivot) != 2
        or not all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in pivot)
    ):
        return f"{preset_id}/{row_id}: catalog.pivot must be a numeric [x, y] pair"
    if asset_kind == "tileset":
        if not (catalog.get("tile_role") or catalog.get("edge_role")):
            return f"{preset_id}/{row_id}: catalog needs tile_role or edge_role"
        if not isinstance(catalog.get("collision"), str) or not catalog["collision"].strip():
            return f"{preset_id}/{row_id}: catalog.collision must be a non-empty string"
    if asset_kind in {"asset", "prop", "props", "icon", "ui"}:
        strategy = catalog.get("strategy_class")
        if strategy not in PROP_STRATEGY_CLASSES:
            return f"{preset_id}/{row_id}: catalog.strategy_class is missing or unsupported"
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
        frame_semantics = preset.get("frame_semantics")
        if frame_semantics not in FRAME_SEMANTICS:
            return fail(
                f"{preset_id}: frame_semantics must be one of "
                f"{', '.join(sorted(FRAME_SEMANTICS))}"
            )
        output = preset.get("output")
        if not isinstance(output, dict):
            return fail(f"{preset_id}: output policy must be an object")
        if not isinstance(output.get("use"), str) or not output["use"].strip():
            return fail(f"{preset_id}: output.use must be a non-empty string")
        if output.get("frame_semantics") != frame_semantics:
            return fail(
                f"{preset_id}: output.frame_semantics must match frame_semantics"
            )
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

        row_workflows = preset.get("row_workflows", {})
        if not isinstance(row_workflows, dict):
            return fail(f"{preset_id}: row_workflows must be an object")
        row_ids = {row.get("id") for row in rows if isinstance(row, dict)}
        unknown_workflow_rows = sorted(set(row_workflows) - row_ids)
        if unknown_workflow_rows:
            return fail(
                f"{preset_id}: row_workflows references unknown row(s): "
                f"{', '.join(unknown_workflow_rows)}"
            )
        if frame_semantics in TEMPORAL_FRAME_SEMANTICS:
            missing_workflow_rows = sorted(row_ids - set(row_workflows))
            if missing_workflow_rows:
                return fail(
                    f"{preset_id}: temporal rows missing animation_workflows: "
                    f"{', '.join(missing_workflow_rows)}"
                )
        seen_labels = set()

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
            declared_workflows = row.get(
                "animation_workflows", row_workflows.get(row_id, [])
            )
            workflow_error = validate_workflows(
                preset_id, row_id, declared_workflows
            )
            if workflow_error:
                return fail(workflow_error)
            if frame_semantics in STATIC_FRAME_SEMANTICS and declared_workflows:
                return fail(
                    f"{preset_id}/{row_id}: static frame_semantics cannot declare animation workflows"
                )
            if frame_semantics in STATIC_FRAME_SEMANTICS and row.get("loop") is True:
                return fail(
                    f"{preset_id}/{row_id}: static frame_semantics rows cannot loop"
                )
            if extraction_mode == "slots":
                metadata_error = validate_slot_metadata(
                    preset_id,
                    row_id,
                    row,
                    frames,
                    asset_kind,
                    seen_labels,
                )
                if metadata_error:
                    return fail(metadata_error)

    print(f"OK: {len(presets)} presets in {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
