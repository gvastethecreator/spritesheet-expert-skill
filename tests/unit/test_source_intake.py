from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from PIL import Image

from spritecore.paths import create_run_marker
from spritecore.source_intake import document_fingerprint, validate_source_intake


def test_source_intake_validation_is_read_only_and_returns_execution_plan(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    create_run_marker(run_dir, run_id="pure-source-intake")
    request = {
        "version": 2,
        "kind": "sprite-gen-request",
        "asset_kind": "sprite",
        "frame_semantics": "animation",
        "extraction_mode": "components",
        "raw_layout_policy": "compact-body-grids",
        "cell": {"width": 8, "height": 8},
        "states": {
            "idle": {
                "frames": 2,
                "fps": 4,
                "loop": True,
                "raw_layout": {
                    "kind": "strip",
                    "columns": 2,
                    "rows": 1,
                    "order": "left-to-right",
                    "delivery": "compose-runtime-row",
                },
            }
        },
        "sampling_policy": {
            "filter": "nearest",
            "wrap": "clamp-to-edge",
            "mipmaps": False,
            "pixel_snap": True,
        },
        "licenses": [{"id": "generated-art", "status": "generated"}],
    }
    (run_dir / "sprite-request.json").write_text(
        json.dumps(request, indent=2), encoding="utf-8"
    )
    candidate = run_dir / "handoff" / "outbox" / "job-idle.png"
    candidate.parent.mkdir(parents=True)
    Image.new("RGB", (16, 8), (120, 80, 40)).save(candidate)
    intake = {
        "version": 1,
        "kind": "sprite-source-intake",
        "job_id": "job-idle",
        "status": "selected",
        "expected": {"state": "idle", "artifact_kind": "raw-row"},
        "source_type": "imagegen",
        "engine": "imagegen",
        "source_stage": "provider-output",
        "provider": {
            "name": "test-provider",
            "status": "succeeded",
            "job_id": "job-idle",
        },
        "candidate": {
            "role": "selected",
            "path": "handoff/outbox/job-idle.png",
            "sha256": sha256(candidate.read_bytes()).hexdigest(),
            "mime": "image/png",
            "width": 16,
            "height": 8,
        },
        "request": {
            "path": "sprite-request.json",
            "fingerprint": document_fingerprint(request),
        },
        "license_ref": "generated-art",
        "license_status": "generated",
        "processing_policy": {
            "selection": "selected-candidate",
            "normalization": "rgba-png",
            "background_removal": "none",
            "resize": "none",
        },
    }
    before = sorted(
        path.relative_to(run_dir).as_posix() for path in run_dir.rglob("*")
    )

    plan = validate_source_intake(intake, run_dir=run_dir)

    after = sorted(
        path.relative_to(run_dir).as_posix() for path in run_dir.rglob("*")
    )
    assert after == before
    assert plan.job_id == "job-idle"
    assert plan.state == "idle"
    assert plan.candidate_path == candidate.resolve()
    assert plan.output_path == (run_dir / "raw" / "idle.png").resolve()
