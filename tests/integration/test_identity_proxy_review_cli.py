from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from PIL import Image


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "SKILLS" / "spritesheet-expert" / "scripts"


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_image(path: Path, color: tuple[int, int, int, int] = (80, 40, 120, 255)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (16, 16), color).save(path)


def run_script(name: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / name), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_hash_bound_identity_proxy_review_accepts_only_current_visual_evidence(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    write_json(
        run_dir / "sprite-request.json",
        {"states": {"idle-step": {"frames": 1, "fps": 8, "loop": True}}},
    )
    write_json(
        run_dir / "frames" / "frames-manifest.json",
        {
            "ok": True,
            "rows": [
                {
                    "state": "idle-step",
                    "frame_records": [
                        {
                            "head_width_vs_reference": 1.5,
                            "upper_width_vs_reference": 1.0,
                            "body_mass_width_80_vs_reference": 1.0,
                            "opaque_area_vs_reference": 1.0,
                        }
                    ],
                }
            ],
        },
    )
    for relative in (
        "sprite-sheet-alpha.png",
        "qa/background-matte-review.png",
        "qa/idle-step-contact.png",
        "qa/idle-step-onion.png",
    ):
        write_image(run_dir / relative)

    initial = run_script("check_identity_consistency.py", "--run-dir", str(run_dir))
    assert initial.returncode == 1, initial.stdout + initial.stderr
    recorded = run_script(
        "record_identity_proxy_review.py",
        "--run-dir",
        str(run_dir),
        "--reason",
        "The narrow top-band proxy measures the reviewed appendage pose, while the identity remains exact.",
    )
    assert recorded.returncode == 0, recorded.stdout + recorded.stderr

    accepted = run_script("check_identity_consistency.py", "--run-dir", str(run_dir))
    assert accepted.returncode == 0, accepted.stdout + accepted.stderr
    accepted_report = json.loads(
        (run_dir / "qa" / "identity-consistency-report.json").read_text(encoding="utf-8")
    )
    assert accepted_report["ok"] is True
    assert accepted_report["identity_proxy_review"]["covered_errors"]

    write_image(run_dir / "qa" / "idle-step-contact.png", (200, 10, 10, 255))
    stale = run_script("check_identity_consistency.py", "--run-dir", str(run_dir))
    assert stale.returncode == 1, stale.stdout + stale.stderr
    stale_report = json.loads(
        (run_dir / "qa" / "identity-consistency-report.json").read_text(encoding="utf-8")
    )
    assert any("artifact changed" in error for error in stale_report["errors"])
