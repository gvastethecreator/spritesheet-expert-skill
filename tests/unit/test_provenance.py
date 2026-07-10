from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from spritecore.provenance import validate_provenance


def _request(states: tuple[str, ...] = ("idle",)) -> dict:
    return {
        "version": 2,
        "kind": "sprite-gen-request",
        "asset_kind": "sprite",
        "frame_semantics": "animation",
        "extraction_mode": "components",
        "raw_layout_policy": "compact-body-grids",
        "cell": {"width": 32, "height": 32},
        "states": {
            state: {
                "frames": 1,
                "fps": 1,
                "loop": True,
                "raw_layout": {
                    "kind": "strip",
                    "columns": 1,
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
    }


def _write_run(
    root: Path,
    *,
    states: tuple[str, ...] = ("idle",),
    covered_states: tuple[str, ...] | None = None,
    source_type: str = "imagegen",
    art_engine: str = "imagegen",
    fixture: bool = False,
) -> tuple[Path, Path]:
    root.mkdir()
    (root / "raw").mkdir()
    source = root / "raw" / "accepted.bin"
    source.write_bytes(b"accepted source bytes")
    covered = covered_states if covered_states is not None else states
    (root / "sprite-request.json").write_text(
        json.dumps(_request(states)), encoding="utf-8"
    )
    provenance = {
        "version": 2,
        "kind": "sprite-source-provenance",
        "source_type": source_type,
        "art_engine": art_engine,
        "fixture": fixture,
        "verification_status": "verified",
        "accepted_sources": [
            {
                "path": "raw/accepted.bin",
                "sha256": sha256(source.read_bytes()).hexdigest(),
                "size_bytes": source.stat().st_size,
                "states": list(covered),
            }
        ],
        "state_coverage": list(covered),
    }
    (root / "source-provenance.json").write_text(
        json.dumps(provenance), encoding="utf-8"
    )
    return root, source


def test_exact_provenance_accepts_current_hash_bound_complete_coverage(tmp_path: Path) -> None:
    run_dir, source = _write_run(tmp_path / "run")

    result = validate_provenance(run_dir)

    assert result.status == "pass"
    assert result.exit_code == 0
    assert result.checked_items == ("idle",)
    assert result.evidence["sources"][0]["path"] == str(source.resolve())


def test_not_imagegen_cannot_pass_by_containing_the_word_imagegen(tmp_path: Path) -> None:
    run_dir, _ = _write_run(tmp_path / "run", art_engine="not-imagegen")

    result = validate_provenance(run_dir)

    assert result.status == "fail"
    assert result.exit_code == 1
    assert any("art_engine" in error for error in result.errors)


def test_provenance_rejects_nonexistent_accepted_source(tmp_path: Path) -> None:
    run_dir, source = _write_run(tmp_path / "run")
    source.unlink()

    result = validate_provenance(run_dir)

    assert result.exit_code == 1
    assert any("does not exist" in error for error in result.errors)


def test_provenance_rejects_partial_state_coverage(tmp_path: Path) -> None:
    run_dir, _ = _write_run(
        tmp_path / "run", states=("idle", "run"), covered_states=("idle",)
    )

    result = validate_provenance(run_dir)

    assert result.exit_code == 1
    assert any("run" in error and "coverage" in error for error in result.errors)


def test_provenance_rejects_changed_source_bytes(tmp_path: Path) -> None:
    run_dir, source = _write_run(tmp_path / "run")
    source.write_bytes(b"changed after acceptance")

    result = validate_provenance(run_dir)

    assert result.exit_code == 1
    assert any("sha256" in error or "size" in error for error in result.errors)


def test_fixture_requires_explicit_fixture_flag_and_policy_opt_in(tmp_path: Path) -> None:
    run_dir, _ = _write_run(
        tmp_path / "run", source_type="fixture", art_engine="fixture", fixture=True
    )

    production_result = validate_provenance(run_dir)
    fixture_result = validate_provenance(run_dir, allow_fixture=True)

    assert production_result.exit_code == 1
    assert fixture_result.exit_code == 0


def test_imported_source_requires_policy_opt_in(tmp_path: Path) -> None:
    run_dir, _ = _write_run(
        tmp_path / "run", source_type="imported", art_engine="imported"
    )

    production_result = validate_provenance(run_dir)
    imported_result = validate_provenance(run_dir, allow_imported=True)

    assert production_result.exit_code == 1
    assert imported_result.exit_code == 0


def test_provenance_source_type_must_match_the_request_fact(tmp_path: Path) -> None:
    run_dir, _ = _write_run(
        tmp_path / "run", source_type="imported", art_engine="imported"
    )
    request_path = run_dir / "sprite-request.json"
    request = json.loads(request_path.read_text(encoding="utf-8"))
    request["source_type"] = "imagegen"
    request_path.write_text(json.dumps(request), encoding="utf-8")

    result = validate_provenance(run_dir, allow_imported=True)

    assert result.exit_code == 1
    assert any("source_type" in error and "request" in error for error in result.errors)


def test_provenance_rejects_path_traversal_without_reading_outside_run(tmp_path: Path) -> None:
    run_dir, _ = _write_run(tmp_path / "run")
    provenance_path = run_dir / "source-provenance.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    provenance["accepted_sources"][0]["path"] = "../outside.bin"
    provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
    (tmp_path / "outside.bin").write_bytes(b"accepted source bytes")

    result = validate_provenance(run_dir)

    assert result.exit_code == 1
    assert any("path" in error.lower() for error in result.errors)
