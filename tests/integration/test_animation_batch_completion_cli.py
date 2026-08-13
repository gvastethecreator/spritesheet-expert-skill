from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (
    REPO_ROOT
    / "SKILLS"
    / "spritesheet-expert"
    / "scripts"
    / "check_animation_batch_completion.py"
)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _request() -> dict[str, Any]:
    states: dict[str, Any] = {}
    for state, loop in (("idle-step", True), ("attack", False)):
        states[state] = {
            "frames": 4,
            "fps": 8,
            "loop": loop,
            "raw_layout": {
                "kind": "compact-grid",
                "columns": 2,
                "rows": 2,
                "order": "row-major",
                "delivery": "compose-runtime-row",
            },
        }
    return {
        "version": 2,
        "kind": "sprite-gen-request",
        "asset_kind": "sprite",
        "frame_semantics": "animation",
        "extraction_mode": "components",
        "raw_layout_policy": "compact-body-grids",
        "cell": {"width": 32, "height": 32},
        "states": states,
        "sampling_policy": {
            "filter": "nearest",
            "wrap": "clamp-to-edge",
            "mipmaps": False,
            "pixel_snap": True,
        },
    }


def _write_video_state(run_dir: Path, state: str, raw_path: Path) -> Path:
    provider_dir = run_dir / "provider" / "grok-imagine" / state
    provider_dir.mkdir(parents=True, exist_ok=True)
    video = provider_dir / "source.mp4"
    video.write_bytes(f"quota-video-{state}".encode())
    output_path = raw_path
    report = {
        "version": 1,
        "kind": "sprite-grok-video-source",
        "status": "pass",
        "provider": "grok-imagine",
        "state": state,
        "video": {
            "path": video.relative_to(run_dir).as_posix(),
            "sha256": _digest(video),
            "size_bytes": video.stat().st_size,
        },
        "decoded": {"frame_count": 12, "fps": 24.0},
        "sampled_video_indices": [0, 3, 6, 9],
        "output": {
            "path": output_path.relative_to(run_dir).as_posix(),
            "sha256": _digest(output_path),
            "size_bytes": output_path.stat().st_size,
        },
    }
    report_path = provider_dir / "video-source.json"
    _write_json(report_path, report)

    selector_dir = run_dir / "qa" / f"{state}-video-frame-selector"
    selector_dir.mkdir(parents=True)
    html = selector_dir / "index.html"
    html.write_text(f"<html>{state} selector</html>", encoding="utf-8")
    page = selector_dir / "timeline-page-01.png"
    page.write_bytes(f"timeline-{state}".encode())
    timeline_manifest = selector_dir / "timeline-pages.json"
    _write_json(timeline_manifest, {"pages": [page.name]})
    selector = {
        "version": 1,
        "kind": "sprite-video-frame-selector-evidence",
        "status": "pass",
        "state": state,
        "source_report": {
            "path": report_path.relative_to(run_dir).as_posix(),
            "sha256": _digest(report_path),
        },
        "video": {
            "path": video.relative_to(run_dir).as_posix(),
            "sha256": _digest(video),
        },
        "selected_indices": [0, 3, 6, 9],
        "candidate_count": 2,
        "html": {
            "path": html.relative_to(run_dir).as_posix(),
            "sha256": _digest(html),
        },
        "timeline": {
            "manifest": timeline_manifest.name,
            "manifest_sha256": _digest(timeline_manifest),
            "pages": [
                {
                    "path": page.name,
                    "first": 0,
                    "last": 11,
                    "sha256": _digest(page),
                }
            ],
        },
    }
    _write_json(selector_dir / "selector.evidence.json", selector)
    return report_path


def _write_batch(repo_root: Path) -> tuple[Path, Path, Path]:
    identity_source = repo_root / "sources" / "forest" / "creature.png"
    identity_source.parent.mkdir(parents=True)
    identity_source.write_bytes(b"approved-identity")
    run_dir = repo_root / "runs" / "forest" / "creature"
    (run_dir / "raw").mkdir(parents=True)
    _write_json(run_dir / "sprite-request.json", _request())
    idle_raw = run_dir / "raw" / "idle-step.png"
    attack_raw = run_dir / "raw" / "attack.png"
    idle_raw.write_bytes(b"accepted-idle-grid")
    attack_raw.write_bytes(b"imagegen-repaired-attack-grid")
    old_attack_grid = run_dir / "provider" / "grok-imagine" / "attack" / "video-grid.png"
    old_attack_grid.parent.mkdir(parents=True)
    old_attack_grid.write_bytes(b"original-video-attack-grid")

    idle_report = _write_video_state(run_dir, "idle-step", idle_raw)
    _write_video_state(run_dir, "attack", old_attack_grid)
    archived = run_dir / "provider" / "video" / "idle-step" / "video-source.json"
    _write_json(archived, {"kind": "sprite-video-source", "state": "idle-step"})

    repair_plan = {
        "version": 1,
        "quota_sealed": True,
        "video_generation_frozen": True,
        "status": "completed",
        "repairs": [
            {
                "state": "attack",
                "method": "imagegen-2x2-sheet-edit",
                "status": "completed",
                "result": "raw/attack.png",
            }
        ],
    }
    _write_json(run_dir / "qa" / "quota-sealed-repair-plan.json", repair_plan)
    provenance = {
        "version": 2,
        "kind": "sprite-source-provenance",
        "source_type": "mixed",
        "art_engine": "mixed",
        "fixture": False,
        "verification_status": "verified",
        "accepted_sources": [
            {
                "path": "raw/idle-step.png",
                "sha256": _digest(idle_raw),
                "size_bytes": idle_raw.stat().st_size,
                "states": ["idle-step"],
                "source_type": "grok-imagine-video",
                "art_engine": "grok-imagine",
                "upstream_report": idle_report.relative_to(run_dir).as_posix(),
            },
            {
                "path": "raw/attack.png",
                "sha256": _digest(attack_raw),
                "size_bytes": attack_raw.stat().st_size,
                "states": ["attack"],
                "source_type": "imagegen",
                "art_engine": "imagegen",
                "upstream_report": "qa/quota-sealed-repair-plan.json",
            },
        ],
        "state_coverage": ["idle-step", "attack"],
        "license": "mixed-provider-terms",
    }
    _write_json(run_dir / "source-provenance.json", provenance)
    _write_json(
        run_dir / "frames" / "frames-manifest.json",
        {
            "ok": True,
            "rows": [
                {
                    "state": state,
                    "files": [f"frames/{state}/frame-{index}.png" for index in range(4)],
                }
                for state in ("idle-step", "attack")
            ],
        },
    )
    atlas = run_dir / "sprite-sheet-alpha.png"
    atlas.write_bytes(b"current-source-atlas")
    _write_json(run_dir / "manifest.json", {"frame_layout": {"rows": {}}})
    workbench = run_dir / "qa" / "preview-workbench" / "index.html"
    workbench.parent.mkdir(parents=True)
    workbench.write_text("<html>review both states</html>", encoding="utf-8")
    _write_json(
        workbench.parent / "workbench.evidence.json",
        {
            "version": 1,
            "kind": "sprite-preview-workbench",
            "artifact": {
                "path": workbench.relative_to(run_dir).as_posix(),
                "sha256": _digest(workbench),
                "size_bytes": workbench.stat().st_size,
            },
            "states": ["idle-step", "attack"],
            "self_contained": True,
        },
    )
    validation_fingerprint = "a" * 64
    validation_path = run_dir / "qa" / "run-validation-report.json"
    _write_json(
        validation_path,
        {
            "version": 1,
            "kind": "sprite-run-validation",
            "ok": True,
            "status": "pass",
            "stage": "pre-package",
            "input_fingerprint": validation_fingerprint,
        },
    )

    candidate_dir = repo_root / "candidates" / "forest" / "creature"
    candidate_dir.mkdir(parents=True)
    candidate_png = candidate_dir / "sprite-sheet-runtime.png"
    candidate_png.write_bytes(b"runtime-candidate")
    _write_json(
        candidate_dir / "manifest.json",
        {
            "version": 1,
            "source_atlas": {"path": str(atlas), "sha256": _digest(atlas)},
            "source_validation": {
                "path": str(validation_path),
                "input_fingerprint": validation_fingerprint,
            },
            "outputs": {
                "png": {
                    "path": candidate_png.name,
                    "sha256": _digest(candidate_png),
                }
            },
        },
    )
    batch = {
        "version": 1,
        "kind": "sprite-animation-batch",
        "generation_policy": {
            "quota_sealed": True,
            "identity_fields": ["biome", "enemy"],
            "states_per_identity": ["idle-step", "attack"],
            "expected_identities": 1,
            "max_provider_videos_per_identity": 2,
        },
        "entries": [
            {
                "biome": "forest",
                "enemy": "creature",
                "source": identity_source.relative_to(repo_root).as_posix(),
                "source_sha256": _digest(identity_source),
                "run": run_dir.relative_to(repo_root).as_posix(),
                "states": {"idle-step": "reviewed", "attack": "reviewed"},
                "review": {
                    "status": "pass",
                    "selected_indices": {"idle-step": [0, 3, 6, 9]},
                    "state_sources": {
                        "idle-step": {
                            "source_type": "grok-imagine-video",
                            "path": "raw/idle-step.png",
                            "sha256": _digest(idle_raw),
                        },
                        "attack": {
                            "source_type": "imagegen",
                            "path": "raw/attack.png",
                            "sha256": _digest(attack_raw),
                        },
                    },
                    "validation": validation_path.relative_to(repo_root).as_posix(),
                    "validation_fingerprint": validation_fingerprint,
                    "candidate": candidate_dir.relative_to(repo_root).as_posix(),
                    "candidate_sha256": _digest(candidate_png),
                },
            }
        ],
    }
    batch_path = repo_root / "batch-manifest.json"
    _write_json(batch_path, batch)
    return batch_path, run_dir, candidate_png


def _run(batch_path: Path, repo_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--repo-root",
            str(repo_root),
            "--batch-manifest",
            str(batch_path),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_audits_quota_sources_repairs_and_archived_reports_separately(
    tmp_path: Path,
) -> None:
    batch_path, _run_dir, _candidate = _write_batch(tmp_path)

    completed = _run(batch_path, tmp_path)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    report = json.loads(
        (tmp_path / "batch-completion-report.json").read_text(encoding="utf-8")
    )
    assert report["status"] == "pass"
    assert report["counts"] == {
        "entries": 1,
        "passing_entries": 1,
        "failing_entries": 0,
        "quota_video_records": 2,
        "unique_quota_videos": 2,
        "completed_repairs": 1,
        "archived_video_reports": 1,
        "accepted_source_types": {"grok-imagine-video": 1, "imagegen": 1},
    }
    assert report["entries"][0]["completed_repairs"] == ["attack"]
    assert report["entries"][0]["quota_videos"][1]["state"] == "attack"
    assert report["entries"][0]["archived_video_reports"]


def test_fails_when_quota_video_bytes_drift(tmp_path: Path) -> None:
    batch_path, run_dir, _candidate = _write_batch(tmp_path)
    video = run_dir / "provider" / "grok-imagine" / "attack" / "source.mp4"
    video.write_bytes(b"changed-after-quota-was-sealed")

    completed = _run(batch_path, tmp_path)

    assert completed.returncode == 1
    report = json.loads(
        (tmp_path / "batch-completion-report.json").read_text(encoding="utf-8")
    )
    assert any("quota video for attack SHA-256 drift" in error for error in report["errors"])


def test_fails_when_packaged_candidate_bytes_drift(tmp_path: Path) -> None:
    batch_path, _run_dir, candidate = _write_batch(tmp_path)
    candidate.write_bytes(b"stale-or-replaced-runtime-candidate")

    completed = _run(batch_path, tmp_path)

    assert completed.returncode == 1
    report = json.loads(
        (tmp_path / "batch-completion-report.json").read_text(encoding="utf-8")
    )
    assert any("candidate PNG SHA-256 drift" in error for error in report["errors"])
    assert any("batch candidate hash drift" in error for error in report["errors"])
