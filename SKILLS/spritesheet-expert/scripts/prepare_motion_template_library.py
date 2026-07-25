#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Write canonical Image Gen prompts for every motion-template catalog entry."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from prepare_sprite_run import motion_reference_prompt


STATE_BY_VIEW = {
    ("side", "right"): "walk-right",
    ("side", "left"): "walk-left",
    ("front", "center"): "frontwalk",
    ("back", "center"): "backwalk",
    ("three-quarter-front", "right"): "walk-front-right",
    ("three-quarter-front", "left"): "walk-front-left",
    ("three-quarter-back", "right"): "walk-back-right",
    ("three-quarter-back", "left"): "walk-back-left",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template-root", required=True, type=Path)
    args = parser.parse_args()
    root = args.template_root.expanduser().resolve()
    manifest_path = root / "manifest.json"
    manifest: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
    templates = manifest.get("templates")
    if not isinstance(templates, dict) or not templates:
        raise SystemExit(f"template catalog has no templates: {manifest_path}")

    written: list[str] = []
    for template_id, template in templates.items():
        if not isinstance(template, dict):
            raise SystemExit(f"template must be an object: {template_id}")
        signature = (str(template.get("view")), str(template.get("facing")))
        state = STATE_BY_VIEW.get(signature)
        if state is None:
            raise SystemExit(f"unsupported template view/facing for {template_id}: {signature}")
        frames = int(template.get("frames", 0))
        if frames != 8:
            raise SystemExit(f"canonical template must contain 8 frames: {template_id}")
        grid = template.get("grid")
        if not isinstance(grid, dict) or (int(grid.get("columns", 0)), int(grid.get("rows", 0))) != (4, 2):
            raise SystemExit(f"canonical template must use a 4x2 grid: {template_id}")
        entry = {
            "frames": frames,
            "fps": 10,
            "loop": True,
            "action": state,
            "raw_layout": {
                "kind": "compact-grid",
                "columns": 4,
                "rows": 2,
                "order": "row-major",
                "delivery": "compose-runtime-row",
            },
        }
        request = {"motion_phase_guides": True}
        prompt = motion_reference_prompt(request, state, entry)
        if prompt is None:
            raise SystemExit(f"failed to build prompt for {template_id}")
        prompt_path = root / str(template["prompt"])
        prompt_path.write_text(prompt.rstrip() + "\n", encoding="utf-8")
        written.append(prompt_path.name)

    print(json.dumps({"ok": True, "template_root": str(root), "prompts": written}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
