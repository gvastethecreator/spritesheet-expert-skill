from __future__ import annotations

from hashlib import sha256
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image
import pytest

from spritecore.paths import RUN_MARKER_FILENAME, create_run_marker
from spritecore.locks import acquire_run_lock


REPO_ROOT = Path(__file__).resolve().parents[2]
INGEST = (
    REPO_ROOT
    / "SKILLS"
    / "spritesheet-expert"
    / "scripts"
    / "ingest_source.py"
)
PROVENANCE_CHECK = (
    REPO_ROOT
    / "SKILLS"
    / "spritesheet-expert"
    / "scripts"
    / "check_generation_provenance.py"
)


def _fingerprint(document: dict) -> str:
    encoded = json.dumps(
        document, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _write_request(
    run_dir: Path,
    states: tuple[str, ...] = ("idle",),
    *,
    license_ref: str = "generated-art",
    license_status: str = "generated",
) -> dict:
    request = {
        "version": 2,
        "kind": "sprite-gen-request",
        "asset_kind": "sprite",
        "frame_semantics": "animation",
        "extraction_mode": "components",
        "raw_layout_policy": "compact-body-grids",
        "cell": {"width": 16, "height": 16, "safe_margin": 2},
        "states": {
            state: {
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
            for state in states
        },
        "sampling_policy": {
            "filter": "nearest",
            "wrap": "clamp-to-edge",
            "mipmaps": False,
            "pixel_snap": True,
        },
        "licenses": [
            {
                "id": license_ref,
                "status": license_status,
                "reference": "source-intake-test",
            }
        ],
    }
    (run_dir / "sprite-request.json").write_text(
        json.dumps(request, indent=2), encoding="utf-8"
    )
    return request


def _write_candidate(path: Path, *, fmt: str = "PNG") -> tuple[str, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (32, 16), (190, 70, 45))
    image.save(path, format=fmt)
    mime = {
        "PNG": "image/png",
        "WEBP": "image/webp",
        "JPEG": "image/jpeg",
    }[fmt]
    return sha256(path.read_bytes()).hexdigest(), mime


def _intake(
    run_dir: Path,
    request: dict,
    *,
    state: str = "idle",
    source_type: str = "imagegen",
    engine: str = "imagegen",
    source_stage: str = "provider-output",
    candidate_path: str = "handoff/outbox/job-idle.png",
    candidate_hash: str,
    mime: str = "image/png",
    license_ref: str = "generated-art",
    license_status: str = "generated",
) -> dict:
    return {
        "version": 1,
        "kind": "sprite-source-intake",
        "job_id": f"job-{state}",
        "status": "selected",
        "expected": {"state": state, "artifact_kind": "raw-row"},
        "source_type": source_type,
        "engine": engine,
        "source_stage": source_stage,
        "provider": {
            "name": "test-provider",
            "status": "succeeded",
            "job_id": f"job-{state}",
        },
        "candidate": {
            "role": "selected",
            "path": candidate_path,
            "sha256": candidate_hash,
            "mime": mime,
            "width": 32,
            "height": 16,
        },
        "request": {
            "path": "sprite-request.json",
            "fingerprint": _fingerprint(request),
        },
        "license_ref": license_ref,
        "license_status": license_status,
        "processing_policy": {
            "selection": "selected-candidate",
            "normalization": "rgba-png",
            "background_removal": "none",
            "resize": "none",
        },
    }


def _run(run_dir: Path, intake_path: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(INGEST),
            "--run-dir",
            str(run_dir),
            "--intake",
            str(intake_path),
            *extra,
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_ingest_accepts_hash_bound_imagegen_row_and_writes_v2_provenance(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    create_run_marker(run_dir, run_id="source-intake")
    request = _write_request(run_dir)
    candidate = run_dir / "handoff" / "outbox" / "job-idle.png"
    candidate_hash, mime = _write_candidate(candidate)
    intake = _intake(
        run_dir,
        request,
        candidate_hash=candidate_hash,
        mime=mime,
    )
    intake_path = run_dir / "handoff" / "inbox" / "job-idle.json"
    intake_path.parent.mkdir(parents=True)
    intake_path.write_text(json.dumps(intake), encoding="utf-8")

    completed = _run(run_dir, intake_path)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    output = run_dir / "raw" / "idle.png"
    assert output.is_file()
    with Image.open(output) as image:
        assert image.format == "PNG"
        assert image.mode == "RGBA"
        assert image.size == (32, 16)
    provenance = json.loads(
        (run_dir / "source-provenance.json").read_text(encoding="utf-8")
    )
    assert provenance["version"] == 2
    assert provenance["kind"] == "sprite-source-provenance"
    assert provenance["source_type"] == "imagegen"
    assert provenance["verification_status"] == "verified"
    assert provenance["state_coverage"] == ["idle"]
    assert provenance["accepted_sources"] == [
        {
            "path": "raw/idle.png",
            "sha256": sha256(output.read_bytes()).hexdigest(),
            "size_bytes": output.stat().st_size,
            "states": ["idle"],
        }
    ]
    report = json.loads(
        (run_dir / "qa" / "source-intake-report.json").read_text(
            encoding="utf-8"
        )
    )
    assert report["ok"] is True
    assert report["job_id"] == "job-idle"
    assert report["output"]["path"] == "raw/idle.png"


def test_ingest_accepts_provider_canvas_dimensions_independent_of_output_cell(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "provider-sized"
    create_run_marker(run_dir, run_id="provider-sized-source")
    request = _write_request(run_dir)
    candidate = run_dir / "handoff" / "outbox" / "job-idle.png"
    candidate.parent.mkdir(parents=True)
    Image.new("RGB", (1254, 1254), (128, 128, 128)).save(candidate)
    intake = _intake(
        run_dir,
        request,
        candidate_hash=sha256(candidate.read_bytes()).hexdigest(),
    )
    intake["candidate"]["width"] = 1254
    intake["candidate"]["height"] = 1254
    intake_path = run_dir / "handoff" / "inbox" / "job-idle.json"
    intake_path.parent.mkdir(parents=True)
    intake_path.write_text(json.dumps(intake), encoding="utf-8")

    completed = _run(run_dir, intake_path)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    with Image.open(run_dir / "raw" / "idle.png") as image:
        assert image.size == (1254, 1254)


def test_ingest_accepts_hash_bound_grok_imagine_still(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "grok-still"
    create_run_marker(run_dir, run_id="grok-source-intake")
    request = _write_request(run_dir)
    candidate = run_dir / "handoff" / "outbox" / "grok-idle.png"
    candidate_hash, mime = _write_candidate(candidate)
    intake = _intake(
        run_dir,
        request,
        source_type="grok-imagine-image",
        engine="grok-imagine",
        candidate_path="handoff/outbox/grok-idle.png",
        candidate_hash=candidate_hash,
        mime=mime,
    )
    intake["provider"].update(
        {"name": "grok-imagine", "model": "grok-imagine-image"}
    )
    intake_path = run_dir / "grok-intake.json"
    intake_path.write_text(json.dumps(intake), encoding="utf-8")

    completed = _run(run_dir, intake_path)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    provenance = json.loads(
        (run_dir / "source-provenance.json").read_text(encoding="utf-8")
    )
    assert provenance["source_type"] == "grok-imagine-image"
    assert provenance["art_engine"] == "grok-imagine"
    assert provenance["fixture"] is False
    assert provenance["accepted_sources"][0]["source_type"] == "grok-imagine-image"
    assert provenance["accepted_sources"][0]["art_engine"] == "grok-imagine"
    assert provenance["accepted_sources"][0]["upstream_report"] == (
        "qa/source-intake-report.json"
    )


def test_ingest_accepts_imported_and_fixture_sources_with_explicit_policy(
    tmp_path: Path,
) -> None:
    cases = [
        (
            "imported",
            "imported",
            "user-import",
            "WEBP",
            "owned-art",
            "user-owned",
            "--allow-imported-source",
        ),
        (
            "fixture",
            "fixture",
            "fixture",
            "JPEG",
            "fixture-art",
            "fixture",
            "--allow-fixture",
        ),
    ]
    for (
        source_type,
        engine,
        source_stage,
        fmt,
        license_ref,
        license_status,
        allow_flag,
    ) in cases:
        run_dir = tmp_path / source_type
        create_run_marker(run_dir, run_id=f"source-intake-{source_type}")
        request = _write_request(
            run_dir,
            license_ref=license_ref,
            license_status=license_status,
        )
        suffix = {"WEBP": ".webp", "JPEG": ".jpg"}[fmt]
        relative = f"handoff/outbox/job-idle{suffix}"
        candidate = run_dir / relative
        candidate_hash, mime = _write_candidate(candidate, fmt=fmt)
        intake = _intake(
            run_dir,
            request,
            source_type=source_type,
            engine=engine,
            source_stage=source_stage,
            candidate_path=relative,
            candidate_hash=candidate_hash,
            mime=mime,
            license_ref=license_ref,
            license_status=license_status,
        )
        intake_path = run_dir / "intake.json"
        intake_path.write_text(json.dumps(intake), encoding="utf-8")

        completed = _run(run_dir, intake_path)

        assert completed.returncode == 0, completed.stdout + completed.stderr
        gate = subprocess.run(
            [
                sys.executable,
                str(PROVENANCE_CHECK),
                "--run-dir",
                str(run_dir),
                allow_flag,
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert gate.returncode == 0, gate.stdout + gate.stderr


def test_ingest_accumulates_partial_coverage_and_force_replaces_only_one_state(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    create_run_marker(run_dir, run_id="source-intake-accumulation")
    request = _write_request(run_dir, states=("idle", "run"))

    def ingest(state: str, color: tuple[int, int, int], *extra: str):
        relative = f"handoff/outbox/job-{state}.png"
        candidate = run_dir / relative
        candidate.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (32, 16), color).save(candidate)
        candidate_hash = sha256(candidate.read_bytes()).hexdigest()
        intake = _intake(
            run_dir,
            request,
            state=state,
            candidate_path=relative,
            candidate_hash=candidate_hash,
        )
        intake_path = run_dir / f"{state}-intake.json"
        intake_path.write_text(json.dumps(intake), encoding="utf-8")
        return _run(run_dir, intake_path, *extra)

    first = ingest("idle", (180, 60, 45))

    assert first.returncode == 0, first.stdout + first.stderr
    idle_before = (run_dir / "raw" / "idle.png").read_bytes()
    partial = json.loads(
        (run_dir / "source-provenance.json").read_text(encoding="utf-8")
    )
    assert partial["state_coverage"] == ["idle"]

    second = ingest("run", (45, 90, 190))

    assert second.returncode == 0, second.stdout + second.stderr
    run_before = (run_dir / "raw" / "run.png").read_bytes()
    complete = json.loads(
        (run_dir / "source-provenance.json").read_text(encoding="utf-8")
    )
    assert complete["state_coverage"] == ["idle", "run"]
    assert (run_dir / "raw" / "idle.png").read_bytes() == idle_before
    gate = subprocess.run(
        [sys.executable, str(PROVENANCE_CHECK), "--run-dir", str(run_dir)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert gate.returncode == 0, gate.stdout + gate.stderr

    refused = ingest("run", (80, 200, 90))

    assert refused.returncode != 0
    assert "--force" in refused.stdout
    assert (run_dir / "raw" / "idle.png").read_bytes() == idle_before
    assert (run_dir / "raw" / "run.png").read_bytes() == run_before

    replaced = ingest("run", (80, 200, 90), "--force")

    assert replaced.returncode == 0, replaced.stdout + replaced.stderr
    assert (run_dir / "raw" / "idle.png").read_bytes() == idle_before
    assert (run_dir / "raw" / "run.png").read_bytes() != run_before
    updated = json.loads(
        (run_dir / "source-provenance.json").read_text(encoding="utf-8")
    )
    entries = {entry["states"][0]: entry for entry in updated["accepted_sources"]}
    assert entries["idle"]["sha256"] == sha256(idle_before).hexdigest()
    assert entries["run"]["sha256"] == sha256(
        (run_dir / "raw" / "run.png").read_bytes()
    ).hexdigest()


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("comparison-role", "candidate role"),
        ("contact-role", "candidate role"),
        ("preview-role", "candidate role"),
        ("wrong-state", "not in the current sprite request"),
        ("wrong-kind", "artifact_kind"),
        ("wrong-mime", "MIME"),
        ("wrong-dimensions", "dimensions"),
        ("wrong-hash", "sha256"),
        ("stale-request", "fingerprint is stale"),
        ("source-engine-mismatch", "does not match source_type"),
        ("unknown-license", "unknown license_ref"),
        ("license-status-mismatch", "license_status"),
        ("wrong-policy", "processing_policy.background_removal"),
        ("unsafe-path", "unsafe"),
        ("provider-failure", "provider status"),
        ("missing-output", "provider output is missing"),
        ("unowned-run", "unowned"),
    ],
)
def test_ingest_rejects_untrusted_or_stale_inputs_before_mutation(
    tmp_path: Path, case: str, expected: str
) -> None:
    run_dir = tmp_path / case
    create_run_marker(run_dir, run_id=f"source-intake-{case}")
    request = _write_request(run_dir)
    candidate = run_dir / "handoff" / "outbox" / "job-idle.png"
    candidate_hash, mime = _write_candidate(candidate)
    intake = _intake(
        run_dir,
        request,
        candidate_hash=candidate_hash,
        mime=mime,
    )

    if case.endswith("-role"):
        intake["candidate"]["role"] = case.removesuffix("-role")
    elif case == "wrong-state":
        intake["expected"]["state"] = "missing-state"
    elif case == "wrong-kind":
        intake["expected"]["artifact_kind"] = "preview"
    elif case == "wrong-mime":
        intake["candidate"]["mime"] = "image/jpeg"
    elif case == "wrong-dimensions":
        intake["candidate"]["width"] = 31
    elif case == "wrong-hash":
        intake["candidate"]["sha256"] = "0" * 64
    elif case == "stale-request":
        intake["request"]["fingerprint"] = "0" * 64
    elif case == "source-engine-mismatch":
        intake["engine"] = "imported"
    elif case == "unknown-license":
        intake["license_ref"] = "unknown-license"
    elif case == "license-status-mismatch":
        intake["license_status"] = "licensed"
    elif case == "wrong-policy":
        intake["processing_policy"]["background_removal"] = "auto"
    elif case == "unsafe-path":
        intake["candidate"]["path"] = "../outside.png"
    elif case == "provider-failure":
        intake["provider"]["status"] = "failed"
        intake["status"] = "provider-failed"
    elif case == "missing-output":
        candidate.unlink()
    elif case == "unowned-run":
        (run_dir / RUN_MARKER_FILENAME).unlink()

    intake_path = run_dir / "intake.json"
    intake_path.write_text(json.dumps(intake), encoding="utf-8")
    before = {
        path.relative_to(run_dir).as_posix(): path.read_bytes()
        for path in run_dir.rglob("*")
        if path.is_file()
    }

    completed = _run(run_dir, intake_path)

    assert completed.returncode != 0
    report = json.loads(completed.stdout)
    assert report["ok"] is False
    assert report["mutated"] is False
    assert expected.lower() in " ".join(report["errors"]).lower()
    assert not (run_dir / "raw" / "idle.png").exists()
    assert not (run_dir / "source-provenance.json").exists()
    assert not (run_dir / "qa" / "source-intake-report.json").exists()
    after = {
        path.relative_to(run_dir).as_posix(): path.read_bytes()
        for path in run_dir.rglob("*")
        if path.is_file()
    }
    assert after == before


def test_ingest_missing_contract_returns_structured_nonzero_without_placeholder(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    create_run_marker(run_dir, run_id="missing-intake")
    _write_request(run_dir)

    completed = _run(run_dir, run_dir / "missing-intake.json")

    assert completed.returncode != 0
    report = json.loads(completed.stdout)
    assert report["ok"] is False
    assert report["mutated"] is False
    assert "could not be loaded" in " ".join(report["errors"])
    assert not (run_dir / "raw").exists()
    assert not (run_dir / "source-provenance.json").exists()


def test_ingest_binds_declared_style_and_identity_anchor_in_report(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    create_run_marker(run_dir, run_id="bound-references")
    style_path = run_dir / "references" / "style-reference.png"
    anchor_path = run_dir / "references" / "identity-anchor.png"
    style_hash, _mime = _write_candidate(style_path)
    anchor_hash, _mime = _write_candidate(anchor_path)
    request = _write_request(run_dir)
    request["style_reference"] = {
        "path": "references/style-reference.png",
        "sha256": style_hash,
    }
    request["identity_anchor"] = {
        "path": "references/identity-anchor.png",
        "sha256": anchor_hash,
    }
    (run_dir / "sprite-request.json").write_text(
        json.dumps(request), encoding="utf-8"
    )
    candidate = run_dir / "handoff" / "outbox" / "job-idle.png"
    candidate_hash, mime = _write_candidate(candidate)
    intake = _intake(
        run_dir,
        request,
        candidate_hash=candidate_hash,
        mime=mime,
    )
    intake["style_reference"] = request["style_reference"]
    intake["identity_anchor"] = request["identity_anchor"]
    intake_path = run_dir / "intake.json"
    intake_path.write_text(json.dumps(intake), encoding="utf-8")

    completed = _run(run_dir, intake_path)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    report = json.loads(completed.stdout)
    assert report["style_reference"] == request["style_reference"]
    assert report["identity_anchor"] == request["identity_anchor"]


@pytest.mark.parametrize("stale_binding", ["style_reference", "identity_anchor"])
def test_ingest_rejects_stale_declared_reference_before_mutation(
    tmp_path: Path, stale_binding: str
) -> None:
    run_dir = tmp_path / stale_binding
    create_run_marker(run_dir, run_id=f"stale-{stale_binding}")
    style_path = run_dir / "references" / "style-reference.png"
    anchor_path = run_dir / "references" / "identity-anchor.png"
    style_hash, _mime = _write_candidate(style_path)
    anchor_hash, _mime = _write_candidate(anchor_path)
    request = _write_request(run_dir)
    request["style_reference"] = {
        "path": "references/style-reference.png",
        "sha256": style_hash,
    }
    request["identity_anchor"] = {
        "path": "references/identity-anchor.png",
        "sha256": anchor_hash,
    }
    (run_dir / "sprite-request.json").write_text(
        json.dumps(request), encoding="utf-8"
    )
    candidate = run_dir / "handoff" / "outbox" / "job-idle.png"
    candidate_hash, mime = _write_candidate(candidate)
    intake = _intake(
        run_dir,
        request,
        candidate_hash=candidate_hash,
        mime=mime,
    )
    intake["style_reference"] = request["style_reference"]
    intake["identity_anchor"] = request["identity_anchor"]
    stale_path = style_path if stale_binding == "style_reference" else anchor_path
    Image.new("RGB", (32, 16), (5, 220, 90)).save(stale_path)
    intake_path = run_dir / "intake.json"
    intake_path.write_text(json.dumps(intake), encoding="utf-8")

    completed = _run(run_dir, intake_path)

    assert completed.returncode != 0
    report = json.loads(completed.stdout)
    assert f"{stale_binding} sha256 is stale" in report["errors"]
    assert not (run_dir / "raw" / "idle.png").exists()
    assert not (run_dir / "source-provenance.json").exists()


@pytest.mark.parametrize("missing_binding", ["style_reference", "identity_anchor"])
def test_ingest_requires_every_reference_declared_by_current_request(
    tmp_path: Path, missing_binding: str
) -> None:
    run_dir = tmp_path / missing_binding
    create_run_marker(run_dir, run_id=f"missing-{missing_binding}")
    reference = run_dir / "references" / f"{missing_binding}.png"
    reference_hash, _mime = _write_candidate(reference)
    request = _write_request(run_dir)
    request[missing_binding] = {
        "path": f"references/{missing_binding}.png",
        "sha256": reference_hash,
    }
    (run_dir / "sprite-request.json").write_text(
        json.dumps(request), encoding="utf-8"
    )
    candidate = run_dir / "handoff" / "outbox" / "job-idle.png"
    candidate_hash, mime = _write_candidate(candidate)
    intake = _intake(
        run_dir,
        request,
        candidate_hash=candidate_hash,
        mime=mime,
    )
    intake_path = run_dir / "intake.json"
    intake_path.write_text(json.dumps(intake), encoding="utf-8")

    completed = _run(run_dir, intake_path)

    assert completed.returncode != 0
    report = json.loads(completed.stdout)
    assert any(
        f"{missing_binding} binding is required" in error
        for error in report["errors"]
    )
    assert not (run_dir / "raw" / "idle.png").exists()


def test_ingest_rejects_stale_existing_provenance_during_accumulation(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    create_run_marker(run_dir, run_id="stale-provenance")
    request = _write_request(run_dir, states=("idle", "run"))

    idle_candidate = run_dir / "handoff" / "outbox" / "job-idle.png"
    idle_hash, mime = _write_candidate(idle_candidate)
    idle_intake = _intake(
        run_dir, request, candidate_hash=idle_hash, mime=mime
    )
    idle_path = run_dir / "idle-intake.json"
    idle_path.write_text(json.dumps(idle_intake), encoding="utf-8")
    accepted = _run(run_dir, idle_path)
    assert accepted.returncode == 0, accepted.stdout + accepted.stderr

    idle_output = run_dir / "raw" / "idle.png"
    idle_output.write_bytes(b"tampered")
    run_candidate = run_dir / "handoff" / "outbox" / "job-run.png"
    run_hash, mime = _write_candidate(run_candidate)
    run_intake = _intake(
        run_dir,
        request,
        state="run",
        candidate_path="handoff/outbox/job-run.png",
        candidate_hash=run_hash,
        mime=mime,
    )
    run_path = run_dir / "run-intake.json"
    run_path.write_text(json.dumps(run_intake), encoding="utf-8")
    provenance_before = (run_dir / "source-provenance.json").read_bytes()

    completed = _run(run_dir, run_path)

    assert completed.returncode != 0
    report = json.loads(completed.stdout)
    assert any("existing accepted source sha256 is stale" in error for error in report["errors"])
    assert not (run_dir / "raw" / "run.png").exists()
    assert (run_dir / "source-provenance.json").read_bytes() == provenance_before


def test_ingest_respects_the_single_writer_run_lock(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    create_run_marker(run_dir, run_id="locked-source-intake")
    request = _write_request(run_dir)
    candidate = run_dir / "handoff" / "outbox" / "job-idle.png"
    candidate_hash, mime = _write_candidate(candidate)
    intake = _intake(
        run_dir,
        request,
        candidate_hash=candidate_hash,
        mime=mime,
    )
    intake_path = run_dir / "intake.json"
    intake_path.write_text(json.dumps(intake), encoding="utf-8")

    with acquire_run_lock(run_dir, "test-holder"):
        completed = _run(run_dir, intake_path)

    assert completed.returncode == 3
    report = json.loads(completed.stdout)
    assert report["status"] == "operational-error"
    assert "locked" in " ".join(report["errors"])
    assert not (run_dir / "raw" / "idle.png").exists()
    assert not (run_dir / "source-provenance.json").exists()
