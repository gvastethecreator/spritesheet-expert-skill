from __future__ import annotations

from hashlib import sha256
import json
from copy import deepcopy
from pathlib import Path
import subprocess
import sys
from types import MappingProxyType

import pytest
from jsonschema.exceptions import SchemaError


def valid_asset_pack() -> dict:
    return {
        "schema_version": 1,
        "pack_id": "forest-adventure",
        "owners": [
            {"id": "sprites", "label": "Sprite pipeline"},
            {"id": "backgrounds", "label": "Background pipeline"},
        ],
        "style_bible": {
            "id": "forest-style",
            "summary": "Readable painted fantasy assets with a shared dusk palette.",
            "palette": ["#172033", "#4F6B52", "#D8B26E"],
            "principles": ["clear silhouettes", "upper-left key light"],
            "scale": {"unit": "world-unit", "pixels_per_unit": 64},
            "target_resolution": {"width": 1280, "height": 720},
            "materials": ["painted foliage", "matte cloth"],
            "references": ["references/forest-mood.png"],
            "avoid": ["photoreal textures", "low-contrast silhouettes"],
            "projection": "side-view-orthographic",
            "camera": "fixed-side-view",
            "shading": "two-ramp-painted-cel",
            "lighting": "upper-left-key",
            "line_weight": "medium-dark-outline",
            "identity_tokens": ["hero-face-v1", "forest-shape-language-v1"],
            "typography": ["ui-body-v1"],
        },
        "inventory": {
            "assets": [
                {
                    "id": "forest-bg",
                    "kind": "background",
                    "owner": "backgrounds",
                    "depends_on": [],
                    "required_variants": ["forest-bg-night"],
                    "validation_report": {
                        "path": "validation/forest-bg.json",
                        "sha256": "c" * 64,
                        "input_fingerprint": "sha256:" + "1" * 64,
                        "status": "pass",
                    },
                },
                {
                    "id": "hero",
                    "kind": "sprite",
                    "owner": "sprites",
                    "depends_on": ["forest-bg"],
                    "required_variants": ["hero-default"],
                    "validation_report": {
                        "path": "validation/hero.json",
                        "sha256": "d" * 64,
                        "input_fingerprint": "sha256:" + "2" * 64,
                        "status": "pass",
                    },
                },
            ]
        },
        "variant_matrix": {
            "axes": {
                "time": ["night", "day"],
                "outfit": ["default", "armored"],
            },
            "variants": [
                {
                    "id": "forest-bg-night",
                    "asset_id": "forest-bg",
                    "axes": {"time": "night"},
                },
                {
                    "id": "hero-default",
                    "asset_id": "hero",
                    "axes": {"outfit": "default"},
                },
            ]
        },
        "delivery_manifest": {
            "deliverables": [
                {
                    "id": "forest-bg-night-png",
                    "asset_id": "forest-bg",
                    "variant_id": "forest-bg-night",
                    "owner": "backgrounds",
                    "path": "deliverables/backgrounds/forest-night.png",
                    "sha256": "a" * 64,
                },
                {
                    "id": "hero-default-atlas",
                    "asset_id": "hero",
                    "variant_id": "hero-default",
                    "owner": "sprites",
                    "path": "deliverables/sprites/hero.png",
                    "sha256": "b" * 64,
                },
            ]
        },
    }


def valid_asset_pack_artifacts() -> tuple[dict, dict[str, bytes]]:
    contract = deepcopy(valid_asset_pack())
    artifacts: dict[str, bytes] = {}
    for deliverable in contract["delivery_manifest"]["deliverables"]:
        content = f"deliverable:{deliverable['id']}".encode()
        deliverable["sha256"] = sha256(content).hexdigest()
        artifacts[deliverable["path"]] = content
    for asset in contract["inventory"]["assets"]:
        reference = asset["validation_report"]
        leaf = {
            "id": "asset-validation",
            "applicable": True,
            "checked_items": [asset["id"]],
            "errors": [],
            "warnings": [],
            "evidence": {
                "asset_kind": asset["kind"],
                "production_media": {
                    "representative": True,
                    "provenance_verified": True,
                    "source_types": ["imagegen"],
                },
                "style_tokens": {
                    "palette": contract["style_bible"]["palette"],
                    "projection": contract["style_bible"]["projection"],
                    "pixels_per_unit": contract["style_bible"]["scale"]["pixels_per_unit"],
                    "lighting": contract["style_bible"]["lighting"],
                    "line_weight": contract["style_bible"]["line_weight"],
                    "camera": contract["style_bible"]["camera"],
                    "shading": contract["style_bible"]["shading"],
                    "identity_tokens": contract["style_bible"]["identity_tokens"],
                    "typography": contract["style_bible"]["typography"],
                },
            },
            "input_fingerprint": reference["input_fingerprint"],
            "complete": True,
            "status": reference["status"],
        }
        content = json.dumps(
            leaf, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
        reference["sha256"] = sha256(content).hexdigest()
        artifacts[reference["path"]] = content
    return contract, artifacts


def rewrite_leaf_report(
    contract: dict,
    artifacts: dict[str, bytes],
    asset_id: str,
    updates: dict,
    *,
    expected_status: str | None = None,
) -> None:
    asset = next(
        item for item in contract["inventory"]["assets"] if item["id"] == asset_id
    )
    reference = asset["validation_report"]
    leaf = json.loads(artifacts[reference["path"]])
    leaf.update(updates)
    content = json.dumps(
        leaf, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    artifacts[reference["path"]] = content
    reference["sha256"] = sha256(content).hexdigest()
    if expected_status is not None:
        reference["status"] = expected_status


def test_asset_pack_aggregate_rejects_cross_family_style_drift() -> None:
    from assetpack import aggregate_asset_pack

    contract, artifacts = valid_asset_pack_artifacts()
    hero = next(asset for asset in contract["inventory"]["assets"] if asset["id"] == "hero")
    reference = hero["validation_report"]
    leaf = json.loads(artifacts[reference["path"]])
    leaf["evidence"]["style_tokens"]["lighting"] = "lower-right-key"
    content = json.dumps(
        leaf, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    artifacts[reference["path"]] = content
    reference["sha256"] = sha256(content).hexdigest()

    report, exit_code = aggregate_asset_pack(contract, artifacts)

    assert exit_code == 1
    assert any("hero" in blocker and "lighting" in blocker for blocker in report["blockers"])


def test_asset_pack_aggregate_rejects_non_representative_production_media() -> None:
    from assetpack import aggregate_asset_pack

    contract, artifacts = valid_asset_pack_artifacts()
    rewrite_leaf_report(
        contract,
        artifacts,
        "hero",
        {
            "evidence": {
                **json.loads(artifacts[contract["inventory"]["assets"][1]["validation_report"]["path"]])["evidence"],
                "production_media": {
                    "representative": False,
                    "provenance_verified": True,
                    "source_types": ["imagegen"],
                },
            }
        },
    )

    report, exit_code = aggregate_asset_pack(contract, artifacts)

    assert exit_code == 1
    assert any("hero" in blocker and "not representative" in blocker for blocker in report["blockers"])
def materialize_asset_pack(tmp_path: Path) -> tuple[Path, dict, dict[str, bytes]]:
    contract, artifacts = valid_asset_pack_artifacts()
    for relative_path, content in artifacts.items():
        target = tmp_path / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    pack_path = tmp_path / "asset-pack.json"
    pack_path.write_text(json.dumps(contract, indent=2), encoding="utf-8")
    return pack_path, contract, artifacts


def run_asset_pack_cli(
    pack_path: Path,
    pack_root: Path,
    *,
    report_path: str | None = None,
) -> subprocess.CompletedProcess[str]:
    script = (
        Path(__file__).resolve().parents[2]
        / "SKILLS"
        / "produce-2d-assets"
        / "scripts"
        / "validate_asset_pack.py"
    )
    command = [
        sys.executable,
        str(script),
        "--pack",
        str(pack_path),
        "--pack-root",
        str(pack_root),
    ]
    if report_path is not None:
        command.extend(["--report", report_path])
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )


def valid_presentation() -> dict:
    def content_reference(prefix: str, digest: str) -> dict:
        return {
            "artifact": {"path": f"assets/{prefix}.png", "sha256": digest * 64},
            "manifest": {
                "path": f"assets/{prefix}.manifest.json",
                "sha256": digest * 64,
            },
            "validation_report": {
                "path": f"assets/{prefix}.validation.json",
                "sha256": digest * 64,
            },
        }

    return {
        "schema_version": 1,
        "presentation_id": "forest-gameplay-board",
        "brief": {
            "id": "gameplay-brief",
            "title": "Forest combat gameplay",
            "purpose": "Show validated assets in a believable runtime composition.",
            "audience": "art direction review",
            "approved_copy": [
                {
                    "id": "gameplay-caption",
                    "text": "Forest combat gameplay",
                    "approved": True,
                    "approved_by": "art-director",
                    "approved_at": "2026-07-10T12:00:00Z",
                }
            ],
        },
        "brand_kit": {
            "id": "forest-brand",
            "palette": ["#172033", "#4F6B52", "#D8B26E"],
            "fonts": [
                {
                    "id": "readable-sans",
                    "source": content_reference("readable-sans", "a"),
                    "license_ref": "license-owned",
                }
            ],
        },
        "inventory": {
            "assets": [
                {
                    "id": "hero",
                    "kind": "sprite",
                    "truth_type": "reconstructed",
                    "source": content_reference("hero", "b"),
                    "license_ref": "license-owned",
                    "provenance_ref": "prov-hero",
                },
                {
                    "id": "arena",
                    "kind": "background",
                    "truth_type": "reconstructed",
                    "source": content_reference("arena", "c"),
                    "license_ref": "license-owned",
                    "provenance_ref": "prov-arena",
                },
            ]
        },
        "gameplay_scenes": [
            {
                "id": "forest-combat",
                "asset_ids": ["hero", "arena"],
                "truth_type": "runtime-captured",
                "proof_role": "runtime-proof",
                "capture_evidence": {
                    "artifact_path": "evidence/forest-combat.png",
                    "sha256": "f" * 64,
                    "media_type": "image/png",
                    "width": 1280,
                    "height": 720,
                    "captured_at": "2026-07-10T12:30:00Z",
                    "tool": "browser-ui-verification",
                    "viewport": {"width": 1280, "height": 720},
                },
            }
        ],
        "compositions": [
            {
                "id": "hero-gameplay-shot",
                "scene_id": "forest-combat",
                "output_profile": "gameplay",
                "canvas": {
                    "width": 1280,
                    "height": 720,
                    "aspect_ratio": {"width": 16, "height": 9},
                    "background": "#172033",
                    "alpha_mode": "opaque",
                    "color_space": "srgb",
                    "safe_zone": {"x": 64, "y": 36, "width": 1152, "height": 648},
                },
                "layers": [
                    {
                        "id": "arena-layer",
                        "layer_type": "asset",
                        "asset_id": "arena",
                        "z_index": 0,
                        "geometry": {"x": 0, "y": 0, "width": 1280, "height": 720},
                    },
                    {
                        "id": "hero-layer",
                        "layer_type": "asset",
                        "asset_id": "hero",
                        "z_index": 10,
                        "geometry": {
                            "x": 560,
                            "y": 360,
                            "width": 128,
                            "height": 192,
                            "rotation_degrees": 0,
                            "opacity": 1,
                            "fit": "contain",
                        },
                    },
                ],
                "asset_ids": ["hero", "arena"],
                "license_refs": ["license-owned"],
                "provenance_refs": ["prov-hero", "prov-arena"],
            }
        ],
        "licenses": [
            {
                "id": "license-owned",
                "name": "Project-owned asset",
                "terms": "Internal and commercial use allowed.",
                "status": "closed",
                "evidence": {
                    "path": "licenses/project-owned.txt",
                    "sha256": "9" * 64,
                },
            }
        ],
        "provenance": [
            {
                "id": "prov-hero",
                "asset_id": "hero",
                "truth_type": "reconstructed",
                "source_path": "sources/hero-source.png",
                "sha256": "c" * 64,
            },
            {
                "id": "prov-arena",
                "asset_id": "arena",
                "truth_type": "reconstructed",
                "source_path": "sources/arena-source.png",
                "sha256": "d" * 64,
            },
        ],
        "manifest": {
            "outputs": [
                {
                    "id": "forest-gameplay-png",
                    "composition_id": "hero-gameplay-shot",
                    "path": "output/forest-gameplay.png",
                    "media_type": "image/png",
                }
            ]
        },
    }


def test_asset_pack_accepts_a_complete_valid_contract() -> None:
    from assetpack import validate_asset_pack

    contract = valid_asset_pack()

    assert validate_asset_pack(contract) is contract


def test_asset_pack_aggregate_passes_complete_hashed_leaf_validation() -> None:
    from assetpack import aggregate_asset_pack

    contract, artifacts = valid_asset_pack_artifacts()

    report, exit_code = aggregate_asset_pack(contract, artifacts)

    assert exit_code == 0
    assert report["status"] == "pass"
    assert report["complete"] is True
    assert report["checked_assets"] == ["forest-bg", "hero"]
    assert report["blockers"] == []


def test_asset_pack_aggregate_rejects_skipped_inventory_assets() -> None:
    from assetpack import aggregate_asset_pack

    contract, artifacts = valid_asset_pack_artifacts()
    rewrite_leaf_report(
        contract,
        artifacts,
        "hero",
        {"status": "skipped", "applicable": False},
        expected_status="skipped",
    )

    report, exit_code = aggregate_asset_pack(contract, artifacts)

    assert exit_code == 1
    assert report["status"] == "fail"
    assert any("hero" in blocker and "skipped" in blocker for blocker in report["blockers"])


def test_asset_pack_aggregate_rejects_a_stale_leaf_fingerprint() -> None:
    from assetpack import aggregate_asset_pack

    contract, artifacts = valid_asset_pack_artifacts()
    rewrite_leaf_report(
        contract,
        artifacts,
        "hero",
        {"input_fingerprint": "sha256:" + "f" * 64},
    )

    report, exit_code = aggregate_asset_pack(contract, artifacts)

    assert exit_code == 1
    assert report["status"] == "fail"
    assert any("hero" in blocker and "stale" in blocker for blocker in report["blockers"])


def test_asset_pack_aggregate_rejects_a_malformed_leaf_result() -> None:
    from assetpack import aggregate_asset_pack

    contract, artifacts = valid_asset_pack_artifacts()
    asset = contract["inventory"]["assets"][1]
    reference = asset["validation_report"]
    leaf = json.loads(artifacts[reference["path"]])
    del leaf["errors"]
    content = json.dumps(leaf, sort_keys=True, separators=(",", ":")).encode()
    artifacts[reference["path"]] = content
    reference["sha256"] = sha256(content).hexdigest()

    report, exit_code = aggregate_asset_pack(contract, artifacts)

    assert exit_code == 1
    assert report["status"] == "fail"
    assert any("hero" in blocker and "malformed" in blocker for blocker in report["blockers"])


def test_asset_pack_aggregate_propagates_incomplete_leaf_as_blocked() -> None:
    from assetpack import aggregate_asset_pack

    contract, artifacts = valid_asset_pack_artifacts()
    rewrite_leaf_report(contract, artifacts, "hero", {"complete": False})

    report, exit_code = aggregate_asset_pack(contract, artifacts)

    assert exit_code == 2
    assert report["status"] == "blocked"
    assert report["complete"] is False
    assert any("hero" in blocker and "incomplete" in blocker for blocker in report["blockers"])


@pytest.mark.parametrize(
    ("asset_kind", "leaf_status", "complete", "expected_exit"),
    [
        ("mockup", "fail", True, 1),
        ("mockup", "blocked", False, 2),
        ("presentation", "fail", True, 1),
        ("presentation", "blocked", False, 2),
        ("presentation", "operational-error", False, 3),
    ],
)
def test_asset_pack_aggregate_propagates_mockup_and_presentation_outcomes(
    asset_kind: str,
    leaf_status: str,
    complete: bool,
    expected_exit: int,
) -> None:
    from assetpack import aggregate_asset_pack

    contract, artifacts = valid_asset_pack_artifacts()
    hero = contract["inventory"]["assets"][1]
    hero["kind"] = asset_kind
    rewrite_leaf_report(
        contract,
        artifacts,
        "hero",
        {
            "status": leaf_status,
            "complete": complete,
            "errors": [f"{asset_kind} validation {leaf_status}"],
        },
        expected_status=leaf_status,
    )

    report, exit_code = aggregate_asset_pack(contract, artifacts)

    assert exit_code == expected_exit
    assert report["status"] == leaf_status
    assert any(asset_kind in blocker for blocker in report["blockers"])


def test_validate_asset_pack_cli_emits_a_complete_machine_report(tmp_path: Path) -> None:
    pack_path, _contract, _artifacts = materialize_asset_pack(tmp_path)

    completed = run_asset_pack_cli(pack_path, tmp_path)

    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert report["kind"] == "asset-pack-validation-report"
    assert report["status"] == "pass"
    assert report["checked_assets"] == ["forest-bg", "hero"]
    written = tmp_path / "validation" / "asset-pack-validation-report.json"
    assert json.loads(written.read_text(encoding="utf-8")) == report


def test_validate_asset_pack_cli_rejects_missing_dependency_before_artifacts(
    tmp_path: Path,
) -> None:
    pack_path, contract, _artifacts = materialize_asset_pack(tmp_path)
    contract["inventory"]["assets"][1]["depends_on"] = ["missing-asset"]
    pack_path.write_text(json.dumps(contract, indent=2), encoding="utf-8")

    completed = run_asset_pack_cli(pack_path, tmp_path)

    assert completed.returncode == 1
    report = json.loads(completed.stdout)
    assert report["status"] == "fail"
    assert report["deliverables"] == []
    assert any("depends on unknown asset" in blocker for blocker in report["blockers"])


def test_validate_asset_pack_cli_rejects_a_stale_leaf(tmp_path: Path) -> None:
    pack_path, contract, _artifacts = materialize_asset_pack(tmp_path)
    reference = contract["inventory"]["assets"][1]["validation_report"]
    report_path = tmp_path / reference["path"]
    leaf = json.loads(report_path.read_text(encoding="utf-8"))
    leaf["input_fingerprint"] = "sha256:" + "f" * 64
    content = json.dumps(leaf, sort_keys=True, separators=(",", ":")).encode()
    report_path.write_bytes(content)
    reference["sha256"] = sha256(content).hexdigest()
    pack_path.write_text(json.dumps(contract, indent=2), encoding="utf-8")

    completed = run_asset_pack_cli(pack_path, tmp_path)

    assert completed.returncode == 1
    report = json.loads(completed.stdout)
    assert report["status"] == "fail"
    assert any("stale input_fingerprint" in blocker for blocker in report["blockers"])


def test_validate_asset_pack_cli_rejects_a_missing_leaf_report(tmp_path: Path) -> None:
    pack_path, contract, _artifacts = materialize_asset_pack(tmp_path)
    reference = contract["inventory"]["assets"][1]["validation_report"]
    (tmp_path / reference["path"]).unlink()

    completed = run_asset_pack_cli(pack_path, tmp_path)

    assert completed.returncode == 1
    report = json.loads(completed.stdout)
    assert report["status"] == "fail"
    assert any("missing validation report" in blocker for blocker in report["blockers"])


def test_validate_asset_pack_cli_rejects_an_incomplete_required_variant(
    tmp_path: Path,
) -> None:
    pack_path, contract, _artifacts = materialize_asset_pack(tmp_path)
    contract["delivery_manifest"]["deliverables"] = contract["delivery_manifest"][
        "deliverables"
    ][:1]
    pack_path.write_text(json.dumps(contract, indent=2), encoding="utf-8")

    completed = run_asset_pack_cli(pack_path, tmp_path)

    assert completed.returncode == 1
    report = json.loads(completed.stdout)
    assert report["status"] == "fail"
    assert report["deliverables"] == []
    assert any(
        "required variant 'hero-default'" in blocker
        and "has no deliverable" in blocker
        for blocker in report["blockers"]
    )


@pytest.mark.parametrize(
    ("leaf_status", "complete", "expected_exit"),
    [("fail", True, 1), ("blocked", False, 2)],
)
def test_validate_asset_pack_cli_propagates_presentation_failure_or_block(
    tmp_path: Path,
    leaf_status: str,
    complete: bool,
    expected_exit: int,
) -> None:
    pack_path, contract, _artifacts = materialize_asset_pack(tmp_path)
    asset = contract["inventory"]["assets"][1]
    asset["kind"] = "presentation"
    reference = asset["validation_report"]
    leaf_path = tmp_path / reference["path"]
    leaf = json.loads(leaf_path.read_text(encoding="utf-8"))
    leaf.update(
        {
            "status": leaf_status,
            "complete": complete,
            "errors": [f"presentation validation {leaf_status}"],
        }
    )
    content = json.dumps(leaf, sort_keys=True, separators=(",", ":")).encode()
    leaf_path.write_bytes(content)
    reference["sha256"] = sha256(content).hexdigest()
    reference["status"] = leaf_status
    pack_path.write_text(json.dumps(contract, indent=2), encoding="utf-8")

    completed = run_asset_pack_cli(pack_path, tmp_path)

    assert completed.returncode == expected_exit
    report = json.loads(completed.stdout)
    assert report["status"] == leaf_status
    assert any("presentation" in blocker for blocker in report["blockers"])


def test_validate_asset_pack_cli_rejects_unsafe_report_output_path(
    tmp_path: Path,
) -> None:
    pack_path, _contract, _artifacts = materialize_asset_pack(tmp_path)

    completed = run_asset_pack_cli(
        pack_path,
        tmp_path,
        report_path="validation/CON.json",
    )

    assert completed.returncode == 3
    report = json.loads(completed.stdout)
    assert report["status"] == "operational-error"
    assert any("reserved Windows" in blocker for blocker in report["blockers"])


def test_validate_asset_pack_cli_rejects_artifact_symlink_escape(
    tmp_path: Path,
) -> None:
    pack_root = tmp_path / "pack"
    pack_root.mkdir()
    pack_path, contract, _artifacts = materialize_asset_pack(pack_root)
    reference = contract["inventory"]["assets"][1]["validation_report"]
    leaf_path = pack_root / reference["path"]
    content = leaf_path.read_bytes()
    outside = tmp_path / "outside-leaf.json"
    outside.write_bytes(content)
    leaf_path.unlink()
    try:
        leaf_path.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"file symlinks are unavailable: {exc}")

    completed = run_asset_pack_cli(pack_path, pack_root)

    assert completed.returncode == 3
    report = json.loads(completed.stdout)
    assert report["status"] == "operational-error"
    assert any("escapes pack root" in blocker for blocker in report["blockers"])


def test_validate_asset_pack_cli_rejects_output_symlink_escape(tmp_path: Path) -> None:
    pack_root = tmp_path / "pack"
    pack_root.mkdir()
    pack_path, _contract, _artifacts = materialize_asset_pack(pack_root)
    outside = tmp_path / "outside-reports"
    outside.mkdir()
    reports_link = pack_root / "reports"
    try:
        reports_link.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks are unavailable: {exc}")

    completed = run_asset_pack_cli(
        pack_path,
        pack_root,
        report_path="reports/aggregate.json",
    )

    assert completed.returncode == 3
    report = json.loads(completed.stdout)
    assert report["status"] == "operational-error"
    assert any("escapes pack root" in blocker for blocker in report["blockers"])
    assert not (outside / "aggregate.json").exists()


def test_asset_pack_accepts_leaf_validation_report_references() -> None:
    from assetpack import validate_asset_pack

    contract = valid_asset_pack()
    for index, asset in enumerate(contract["inventory"]["assets"]):
        asset["validation_report"] = {
            "path": f"validation/{asset['id']}.json",
            "sha256": f"{index + 1}" * 64,
            "input_fingerprint": f"sha256:{index + 1}" * 32,
            "status": "pass",
        }

    assert validate_asset_pack(contract) is contract


def test_asset_pack_requires_one_leaf_validation_reference_per_asset() -> None:
    from assetpack import AssetPackContractError, validate_asset_pack

    contract = valid_asset_pack()
    del contract["inventory"]["assets"][0]["validation_report"]

    with pytest.raises(
        AssetPackContractError,
        match=r"inventory\.assets\[0\].*validation_report.*required",
    ):
        validate_asset_pack(contract)


def test_asset_pack_accepts_a_read_only_mapping() -> None:
    from assetpack import validate_asset_pack

    contract = MappingProxyType(valid_asset_pack())

    assert validate_asset_pack(contract) is contract


def test_asset_pack_loader_meta_validates_every_schema(tmp_path, monkeypatch) -> None:
    from assetpack import contracts

    invalid_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://schemas.openai.local/produce-2d-assets/asset-pack.schema.json",
        "type": 42,
    }
    (tmp_path / "asset-pack.schema.json").write_text(
        json.dumps(invalid_schema), encoding="utf-8"
    )
    monkeypatch.setattr(contracts, "_SCHEMA_DIR", tmp_path)

    with pytest.raises(SchemaError):
        contracts._load_validator()


@pytest.mark.parametrize(
    "unsafe_path",
    [
        "../outside.png",
        "deliverables/../../outside.png",
        "C:outside.png",
        "C:/outside.png",
        r"\\server\share\outside.png",
        r"deliverables\hero.png",
    ],
)
def test_asset_pack_rejects_non_portable_delivery_paths(unsafe_path: str) -> None:
    from assetpack import AssetPackContractError, validate_asset_pack

    contract = deepcopy(valid_asset_pack())
    contract["delivery_manifest"]["deliverables"][0]["path"] = unsafe_path

    with pytest.raises(AssetPackContractError):
        validate_asset_pack(contract)


@pytest.mark.parametrize(
    "unsafe_path",
    [
        "../validation.json",
        "validation/e\u0301.json",
        "validation/hero\u200b.json",
        "validation∕hero.json",
        "validation/CON.json",
    ],
)
def test_asset_pack_rejects_non_portable_leaf_report_paths(
    unsafe_path: str,
) -> None:
    from assetpack import AssetPackContractError, validate_asset_pack

    contract = valid_asset_pack()
    contract["inventory"]["assets"][0]["validation_report"]["path"] = unsafe_path

    with pytest.raises(AssetPackContractError, match="validation report.*portable"):
        validate_asset_pack(contract)


def test_asset_pack_accepts_declared_variant_axes() -> None:
    from assetpack import validate_asset_pack

    contract = valid_asset_pack()
    contract["variant_matrix"]["axes"] = {
        "time": ["night", "day"],
        "outfit": ["default", "armored"],
    }

    assert validate_asset_pack(contract) is contract


def test_asset_pack_rejects_undeclared_variant_axes() -> None:
    from assetpack import AssetPackContractError, validate_asset_pack

    contract = valid_asset_pack()
    contract["variant_matrix"]["variants"][0]["axes"] = {"theem": "night"}

    with pytest.raises(
        AssetPackContractError,
        match="variant 'forest-bg-night' uses undeclared axis 'theem'",
    ):
        validate_asset_pack(contract)


def test_asset_pack_rejects_disallowed_variant_axis_values() -> None:
    from assetpack import AssetPackContractError, validate_asset_pack

    contract = valid_asset_pack()
    contract["variant_matrix"]["variants"][0]["axes"] = {"time": "sunset"}

    with pytest.raises(
        AssetPackContractError,
        match="variant 'forest-bg-night' uses disallowed value 'sunset' for axis 'time'",
    ):
        validate_asset_pack(contract)


def test_asset_pack_requires_variant_axis_declarations() -> None:
    from assetpack import AssetPackContractError, validate_asset_pack

    contract = valid_asset_pack()
    del contract["variant_matrix"]["axes"]

    with pytest.raises(
        AssetPackContractError,
        match=r"\$\.variant_matrix.*axes.*required",
    ):
        validate_asset_pack(contract)


def test_asset_pack_accepts_a_production_style_bible() -> None:
    from assetpack import validate_asset_pack

    contract = valid_asset_pack()
    contract["style_bible"].update(
        {
            "scale": {"unit": "world-unit", "pixels_per_unit": 64},
            "target_resolution": {"width": 1280, "height": 720},
            "materials": ["painted foliage", "matte cloth"],
            "references": ["references/forest-mood.png"],
            "avoid": ["photoreal textures", "low-contrast silhouettes"],
        }
    )

    assert validate_asset_pack(contract) is contract


def test_asset_pack_requires_production_style_bible_fields() -> None:
    from assetpack import AssetPackContractError, validate_asset_pack

    contract = valid_asset_pack()
    del contract["style_bible"]["target_resolution"]

    with pytest.raises(
        AssetPackContractError,
        match=r"\$\.style_bible.*target_resolution.*required",
    ):
        validate_asset_pack(contract)


def test_asset_pack_rejects_non_portable_style_reference_paths() -> None:
    from assetpack import AssetPackContractError, validate_asset_pack

    contract = valid_asset_pack()
    contract["style_bible"]["references"] = ["../outside.png"]

    with pytest.raises(AssetPackContractError, match="style reference path"):
        validate_asset_pack(contract)


def test_asset_pack_rejects_duplicate_asset_ids() -> None:
    from assetpack import AssetPackContractError, validate_asset_pack

    contract = deepcopy(valid_asset_pack())
    contract["inventory"]["assets"][1]["id"] = "forest-bg"

    with pytest.raises(AssetPackContractError, match="duplicate inventory asset id 'forest-bg'"):
        validate_asset_pack(contract)


def test_asset_pack_rejects_unknown_owners() -> None:
    from assetpack import AssetPackContractError, validate_asset_pack

    contract = deepcopy(valid_asset_pack())
    contract["inventory"]["assets"][1]["owner"] = "missing-pipeline"

    with pytest.raises(AssetPackContractError, match="asset 'hero' has unknown owner 'missing-pipeline'"):
        validate_asset_pack(contract)


def test_asset_pack_requires_deliverable_owner_to_match_asset_owner() -> None:
    from assetpack import AssetPackContractError, validate_asset_pack

    contract = deepcopy(valid_asset_pack())
    contract["delivery_manifest"]["deliverables"][0]["owner"] = "sprites"

    with pytest.raises(
        AssetPackContractError,
        match=(
            "deliverable 'forest-bg-night-png' owner 'sprites' does not match "
            "asset 'forest-bg' owner 'backgrounds'"
        ),
    ):
        validate_asset_pack(contract)


def test_asset_pack_errors_expose_structured_issues() -> None:
    from assetpack import AssetPackContractError, validate_asset_pack

    contract = valid_asset_pack()
    contract["delivery_manifest"]["deliverables"][0]["owner"] = "sprites"

    with pytest.raises(AssetPackContractError) as caught:
        validate_asset_pack(contract)

    issue = caught.value.issues[0]
    assert issue.code == "owner_mismatch"
    assert issue.path == "$.delivery_manifest.deliverables[0].owner"
    assert "does not match" in issue.message
    assert "does not match" in str(caught.value)


def test_asset_pack_rejects_inventory_dependency_cycles() -> None:
    from assetpack import AssetPackContractError, validate_asset_pack

    contract = deepcopy(valid_asset_pack())
    contract["inventory"]["assets"][0]["depends_on"] = ["hero"]

    with pytest.raises(AssetPackContractError, match=r"inventory dependency cycle: forest-bg -> hero -> forest-bg"):
        validate_asset_pack(contract)


def test_asset_pack_rejects_unresolved_required_variants() -> None:
    from assetpack import AssetPackContractError, validate_asset_pack

    contract = deepcopy(valid_asset_pack())
    contract["variant_matrix"]["variants"] = contract["variant_matrix"]["variants"][:1]

    with pytest.raises(AssetPackContractError, match="asset 'hero' requires unresolved variant 'hero-default'"):
        validate_asset_pack(contract)


def test_presentation_accepts_a_complete_valid_contract() -> None:
    from presentation_pipeline import validate_presentation

    contract = valid_presentation()

    assert validate_presentation(contract) is contract


def test_presentation_accepts_a_read_only_mapping() -> None:
    from presentation_pipeline import validate_presentation

    contract = MappingProxyType(valid_presentation())

    assert validate_presentation(contract) is contract


def test_presentation_loader_meta_validates_every_schema(tmp_path, monkeypatch) -> None:
    from presentation_pipeline import contracts

    invalid_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": (
            "https://schemas.openai.local/compose-asset-mockups/"
            "presentation.schema.json"
        ),
        "type": 42,
    }
    (tmp_path / "presentation.schema.json").write_text(
        json.dumps(invalid_schema), encoding="utf-8"
    )
    monkeypatch.setattr(contracts, "_SCHEMA_DIR", tmp_path)

    with pytest.raises(SchemaError):
        contracts._load_validator()


def test_presentation_accepts_explicit_canvas_layers_and_geometry() -> None:
    from presentation_pipeline import validate_presentation

    contract = valid_presentation()
    contract["compositions"][0].update(
        {
            "canvas": {
                "width": 1280,
                "height": 720,
                "aspect_ratio": {"width": 16, "height": 9},
                "background": "#172033",
                "alpha_mode": "opaque",
                "color_space": "srgb",
                "safe_zone": {"x": 64, "y": 36, "width": 1152, "height": 648},
            },
            "layers": [
                {
                    "id": "arena-layer",
                    "layer_type": "asset",
                    "asset_id": "arena",
                    "z_index": 0,
                    "geometry": {"x": 0, "y": 0, "width": 1280, "height": 720},
                },
                {
                    "id": "hero-layer",
                    "layer_type": "asset",
                    "asset_id": "hero",
                    "z_index": 10,
                    "geometry": {
                        "x": 560,
                        "y": 360,
                        "width": 128,
                        "height": 192,
                        "rotation_degrees": 0,
                        "opacity": 1,
                        "fit": "contain",
                    },
                },
            ],
        }
    )

    assert validate_presentation(contract) is contract


def test_presentation_requires_composition_layers() -> None:
    from presentation_pipeline import PresentationContractError, validate_presentation

    contract = valid_presentation()
    del contract["compositions"][0]["layers"]

    with pytest.raises(
        PresentationContractError,
        match=r"\$\.compositions\[0\].*layers.*required",
    ):
        validate_presentation(contract)


def test_presentation_rejects_composition_assets_outside_its_scene() -> None:
    from presentation_pipeline import PresentationContractError, validate_presentation

    contract = valid_presentation()
    contract["gameplay_scenes"][0]["asset_ids"] = ["arena"]

    with pytest.raises(
        PresentationContractError,
        match="composition 'hero-gameplay-shot' uses asset 'hero' outside scene 'forest-combat'",
    ):
        validate_presentation(contract)


def test_presentation_errors_expose_structured_issues() -> None:
    from presentation_pipeline import PresentationContractError, validate_presentation

    contract = valid_presentation()
    contract["gameplay_scenes"][0]["asset_ids"] = ["arena"]

    with pytest.raises(PresentationContractError) as caught:
        validate_presentation(contract)

    issue = caught.value.issues[0]
    assert issue.code == "composition_asset_outside_scene"
    assert issue.path == "$.compositions[0].asset_ids[0]"
    assert "outside scene" in issue.message
    assert "outside scene" in str(caught.value)


def test_presentation_rejects_layers_for_unlisted_composition_assets() -> None:
    from presentation_pipeline import PresentationContractError, validate_presentation

    contract = valid_presentation()
    contract["compositions"][0]["asset_ids"] = ["arena"]
    contract["compositions"][0]["provenance_refs"] = ["prov-arena"]

    with pytest.raises(
        PresentationContractError,
        match="composition 'hero-gameplay-shot' layer 'hero-layer' uses unlisted asset 'hero'",
    ):
        validate_presentation(contract)


def test_presentation_accepts_hash_backed_capture_evidence() -> None:
    from presentation_pipeline import validate_presentation

    contract = valid_presentation()
    contract["gameplay_scenes"][0]["capture_evidence"].update(
        {
            "sha256": "f" * 64,
            "media_type": "image/png",
            "width": 1280,
            "height": 720,
        }
    )

    assert validate_presentation(contract) is contract


def test_presentation_requires_hash_backed_capture_evidence() -> None:
    from presentation_pipeline import PresentationContractError, validate_presentation

    contract = valid_presentation()
    del contract["gameplay_scenes"][0]["capture_evidence"]["sha256"]

    with pytest.raises(
        PresentationContractError,
        match=r"\$\.gameplay_scenes\[0\].capture_evidence.*sha256.*required",
    ):
        validate_presentation(contract)


@pytest.mark.parametrize(
    "unsafe_path",
    [
        "../outside.png",
        "output/../../outside.png",
        "C:outside.png",
        "C:/outside.png",
        r"\\server\share\outside.png",
        r"output\board.png",
    ],
)
def test_presentation_rejects_non_portable_output_paths(unsafe_path: str) -> None:
    from presentation_pipeline import PresentationContractError, validate_presentation

    contract = deepcopy(valid_presentation())
    contract["manifest"]["outputs"][0]["path"] = unsafe_path

    with pytest.raises(PresentationContractError):
        validate_presentation(contract)


def test_presentation_rejects_missing_license_references() -> None:
    from presentation_pipeline import PresentationContractError, validate_presentation

    contract = deepcopy(valid_presentation())
    contract["inventory"]["assets"][0]["license_ref"] = "license-missing"

    with pytest.raises(
        PresentationContractError,
        match="asset 'hero' references missing license 'license-missing'",
    ):
        validate_presentation(contract)


def test_presentation_distinguishes_mismatched_provenance_ownership() -> None:
    from presentation_pipeline import PresentationContractError, validate_presentation

    contract = deepcopy(valid_presentation())
    contract["inventory"]["assets"][0]["provenance_ref"] = "prov-arena"

    with pytest.raises(
        PresentationContractError,
        match=(
            "asset 'hero' references provenance 'prov-arena' belonging to asset 'arena'"
        ),
    ):
        validate_presentation(contract)


def test_presentation_rejects_runtime_provenance_without_capture_evidence() -> None:
    from presentation_pipeline import PresentationContractError, validate_presentation

    contract = deepcopy(valid_presentation())
    contract["provenance"][0]["truth_type"] = "runtime-captured"

    with pytest.raises(
        PresentationContractError,
        match=r"\$\.provenance\[0\].*capture_evidence.*required",
    ):
        validate_presentation(contract)


def test_presentation_rejects_runtime_scene_without_capture_evidence() -> None:
    from presentation_pipeline import PresentationContractError, validate_presentation

    contract = deepcopy(valid_presentation())
    del contract["gameplay_scenes"][0]["capture_evidence"]

    with pytest.raises(
        PresentationContractError,
        match=r"\$\.gameplay_scenes\[0\].*capture_evidence.*required",
    ):
        validate_presentation(contract)


def test_presentation_rejects_duplicate_registry_ids() -> None:
    from presentation_pipeline import PresentationContractError, validate_presentation

    contract = deepcopy(valid_presentation())
    contract["licenses"].append(deepcopy(contract["licenses"][0]))

    with pytest.raises(
        PresentationContractError,
        match="duplicate license id 'license-owned'",
    ):
        validate_presentation(contract)


def test_presentation_rejects_compositions_with_unresolved_asset_licenses() -> None:
    from presentation_pipeline import PresentationContractError, validate_presentation

    contract = deepcopy(valid_presentation())
    contract["licenses"].append(
        {
            "id": "license-third-party",
            "name": "Third-party asset license",
            "terms": "Presentation use only.",
            "status": "closed",
            "evidence": {
                "path": "licenses/third-party.txt",
                "sha256": "8" * 64,
            },
        }
    )
    contract["inventory"]["assets"][0]["license_ref"] = "license-third-party"

    with pytest.raises(
        PresentationContractError,
        match="composition 'hero-gameplay-shot' omits license 'license-third-party' for asset 'hero'",
    ):
        validate_presentation(contract)
