"""Lane selection and typed final-check commands, shared by CLI and Studio."""
from pathlib import Path
import json
import sys
from .contracts import load_sprite_request

SKILL = Path(__file__).resolve().parents[2]


def registry():
    return json.loads((SKILL / "references/workflow-lanes.json").read_text(encoding="utf-8"))


def select_lane(request):
    if request.get("kind") == "deterministic-item-atlas" or request.get("schemaVersion") == "item-atlas-workflow-v1":
        return "static-items"
    if request.get("asset_kind") in {"tileset", "texture"} or request.get("frame_semantics") in {"tiles", "seamless-textures"}:
        return "tileset"
    if request.get("frame_semantics") in {"animation", "effects"}:
        return "animation"
    if request.get("frame_semantics") in {"variants", "still-assets"}:
        return "true-grid"
    raise ValueError("declare frame_semantics or an explicit workflow lane")


def describe_run(root, *, lane=None):
    root = Path(root)
    if (root / "workflow.json").is_file():
        state = json.loads((root / "workflow.json").read_text(encoding="utf-8"))
        if state.get("schemaVersion") != "item-atlas-workflow-v1":
            raise ValueError("unsupported workflow contract")
        if lane is not None and lane != "static-items":
            raise ValueError(f"lane {lane} conflicts with the static-items workflow")
        return "static-items", state
    request = load_sprite_request(root / "sprite-request.json").to_dict()
    inferred = select_lane(request)
    if lane is not None and lane != inferred:
        raise ValueError(f"lane {lane} conflicts with the request's {inferred} semantics")
    lane = inferred
    if lane not in registry()["lanes"] or lane == "static-items":
        raise ValueError("component-row run requires a grid, animation or tileset lane")
    return lane, {"status": "review-required", "processingComplete": (root / "manifest.json").is_file(),
                  "manifest": "manifest.json" if (root / "manifest.json").is_file() else None}


def final_command(lane, run_dir, *, manifest=None, draft=False, allow_imported=False, allow_fixture=False):
    lanes = registry()["lanes"]
    if lane not in lanes:
        raise ValueError("unsupported workflow lane")
    script = SKILL / "scripts" / lanes[lane]["finalGate"]
    if lane == "static-items":
        if manifest is None:
            raise ValueError("static-items requires its active manifest")
        args = ["--manifest", str(Path(manifest).resolve())]
        if draft: args.append("--draft")
    else:
        if draft:
            raise ValueError("row workflows use pending review reports, not the item draft gate")
        args = ["--run-dir", str(Path(run_dir).resolve()), "--stage", "pre-package"]
        if allow_imported: args.append("--allow-imported-source")
        if allow_fixture: args.append("--allow-fixture")
    return [sys.executable, str(script), *args]
