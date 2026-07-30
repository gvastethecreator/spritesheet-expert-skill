from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

from PIL import Image


REPO_ROOT = Path(__file__).resolve().parents[2]
REPAIR = (
    REPO_ROOT
    / "SKILLS"
    / "spritesheet-expert"
    / "scripts"
    / "repair_repeat_edges.py"
)


def test_repeat_repair_rejects_manifest_path_escape_before_mutation(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    (run_dir / "frames").mkdir(parents=True)
    (run_dir / "raw").mkdir()
    outside = tmp_path / "outside.png"
    Image.new("RGBA", (32, 32), (70, 120, 45, 255)).save(outside)
    before = sha256(outside.read_bytes()).hexdigest()
    source = run_dir / "raw" / "accepted.png"
    Image.new("RGBA", (32, 32), (70, 120, 45, 255)).save(source)
    request = {
        "version": 2,
        "kind": "sprite-gen-request",
        "asset_kind": "texture",
        "frame_semantics": "seamless-textures",
        "extraction_mode": "slots",
        "raw_layout_policy": "compact-body-grids",
        "cell": {"width": 32, "height": 32, "safe_margin": 0},
        "states": {
            "materials": {
                "frames": 1,
                "fps": 1,
                "asset_labels": ["moss"],
                "raw_layout": {
                    "kind": "strip",
                    "columns": 1,
                    "rows": 1,
                    "order": "left-to-right",
                    "delivery": "compose-runtime-row",
                },
            }
        },
        "sampling_policy": {
            "filter": "linear",
            "wrap": "repeat",
            "mipmaps": False,
            "pixel_snap": False,
        },
        "asset_catalog": {
            "items": {
                "moss": {
                    "category": "materials",
                    "pivot": [16, 16],
                    "repeat_mode": "self",
                }
            }
        },
    }
    provenance = {
        "version": 2,
        "kind": "sprite-source-provenance",
        "source_type": "imagegen",
        "art_engine": "imagegen",
        "fixture": False,
        "verification_status": "verified",
        "accepted_sources": [
            {
                "path": "raw/accepted.png",
                "sha256": sha256(source.read_bytes()).hexdigest(),
                "size_bytes": source.stat().st_size,
                "states": ["materials"],
            }
        ],
        "state_coverage": ["materials"],
    }
    (run_dir / "sprite-request.json").write_text(
        json.dumps(request), encoding="utf-8"
    )
    (run_dir / "source-provenance.json").write_text(
        json.dumps(provenance), encoding="utf-8"
    )
    (run_dir / "frames" / "frames-manifest.json").write_text(
        json.dumps(
            {
                "ok": True,
                "rows": [
                    {"state": "materials", "files": ["../outside.png"]}
                ],
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(REPAIR), "--run-dir", str(run_dir), "--labels", "moss"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "path traversal" in result.stderr
    assert sha256(outside.read_bytes()).hexdigest() == before
    assert not (run_dir / "provider").exists()
