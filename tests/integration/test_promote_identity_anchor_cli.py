from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "SKILLS/spritesheet-expert/scripts/promote_identity_anchor.py"


def test_anchor_outputs_preserve_inputs_and_stay_inside_the_run(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    raw = run_dir / "raw/idle.png"
    raw.parent.mkdir(parents=True)
    image = Image.new("RGBA", (64, 32), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    for x in (3, 35):
        draw.rectangle((x, 3, x + 12, 27), fill=(180, 80, 40, 255))
    image.save(raw)
    request_path = run_dir / "sprite-request.json"
    request_path.write_text(json.dumps({
        "cell": {"width": 32, "height": 32},
        "states": {"idle": {"frames": 2, "fps": 8, "loop": True}},
        "chroma_key": {"rgb": [255, 0, 255]},
        "background_removal": {"method": "none"},
    }), encoding="utf-8")
    original_raw, original_request = raw.read_bytes(), request_path.read_bytes()
    command = [sys.executable, str(SCRIPT), "--run-dir", str(run_dir)]
    outside = tmp_path / "outside.png"
    for output in (Path("raw/idle.png"), Path("sprite-request.png"), outside):
        result = subprocess.run([*command, "--out", str(output)], capture_output=True, text=True)
        assert result.returncode != 0, result.stdout
        assert raw.read_bytes() == original_raw
        assert request_path.read_bytes() == original_request
    assert not outside.exists()
    assert not (run_dir / "sprite-request.png").exists()

    for output in ("references/approved.png", str(run_dir / "references/approved.png")):
        result = subprocess.run([*command, "--out", output], capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr
        assert json.loads(result.stdout)["output"] == "references/approved.png"
    assert (run_dir / "references/approved.png").is_file()
    sidecar = json.loads((run_dir / "references/approved.json").read_text())
    assert sidecar["source"] == "raw/idle.png"
    assert raw.read_bytes() == original_raw
    assert request_path.read_bytes() == original_request
