from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

from PIL import Image
import pytest


HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64
PREPARE_CLI = (
    Path(__file__).resolve().parents[2]
    / "SKILLS"
    / "compose-asset-mockups"
    / "scripts"
    / "prepare_presentation.py"
)


def content_reference(path: str, sha256: str = HASH_A) -> dict:
    return {
        "artifact": {"path": path, "sha256": sha256},
        "manifest": {
            "path": "upstream/asset-manifest.json",
            "sha256": HASH_B,
        },
        "validation_report": {
            "path": "upstream/validation-report.json",
            "sha256": HASH_C,
        },
    }


def phase4_presentation() -> dict:
    return {
        "schema_version": 1,
        "presentation_id": "forest-presentation",
        "brief": {
            "id": "forest-brief",
            "title": "Forest launch set",
            "purpose": "Present approved game assets without overstating runtime truth.",
            "audience": "store and art-direction review",
            "approved_copy": [
                {
                    "id": "headline",
                    "text": "FOREST GUARDIANS",
                    "approved": True,
                    "approved_by": "creative-director",
                    "approved_at": "2026-07-10T12:00:00Z",
                }
            ],
        },
        "brand_kit": {
            "id": "forest-brand",
            "palette": ["#172033", "#D8B26E"],
            "fonts": [
                {
                    "id": "display-font",
                    "source": content_reference("upstream/display.ttf", HASH_D),
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
                    "source": content_reference("upstream/hero.png"),
                    "license_ref": "license-owned",
                    "provenance_ref": "prov-hero",
                }
            ]
        },
        "gameplay_scenes": [
            {
                "id": "forest-scene",
                "asset_ids": ["hero"],
                "truth_type": "reconstructed",
                "proof_role": "illustrative",
            }
        ],
        "compositions": [
            {
                "id": "hero-contact-sheet",
                "scene_id": "forest-scene",
                "output_profile": "contact-sheet",
                "canvas": {
                    "width": 640,
                    "height": 360,
                    "aspect_ratio": {"width": 16, "height": 9},
                    "background": "#172033",
                    "alpha_mode": "opaque",
                    "color_space": "srgb",
                    "safe_zone": {"x": 20, "y": 20, "width": 600, "height": 320},
                },
                "layers": [
                    {
                        "id": "hero-layer",
                        "layer_type": "asset",
                        "asset_id": "hero",
                        "z_index": 0,
                        "geometry": {
                            "x": 220,
                            "y": 80,
                            "width": 200,
                            "height": 200,
                            "fit": "contain",
                            "resampling": "nearest",
                        },
                    },
                    {
                        "id": "headline-layer",
                        "layer_type": "text",
                        "copy_id": "headline",
                        "font_id": "display-font",
                        "font_size": 28,
                        "color": "#D8B26E",
                        "z_index": 10,
                        "geometry": {"x": 40, "y": 24, "width": 560, "height": 40},
                    },
                ],
                "asset_ids": ["hero"],
                "license_refs": ["license-owned"],
                "provenance_refs": ["prov-hero"],
            }
        ],
        "licenses": [
            {
                "id": "license-owned",
                "name": "Project-owned asset license",
                "terms": "Commercial presentation use approved.",
                "status": "closed",
                "evidence": {
                    "path": "licenses/project-owned.txt",
                    "sha256": HASH_D,
                },
            }
        ],
        "provenance": [
            {
                "id": "prov-hero",
                "asset_id": "hero",
                "truth_type": "reconstructed",
                "source_path": "upstream/hero.png",
                "sha256": HASH_A,
            }
        ],
        "manifest": {
            "outputs": [
                {
                    "id": "hero-contact-sheet-png",
                    "composition_id": "hero-contact-sheet",
                    "path": "presentation/outputs/hero-contact-sheet.png",
                    "media_type": "image/png",
                }
            ]
        },
    }


def _write_bytes(root: Path, relative_path: str, content: bytes) -> str:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return sha256(content).hexdigest()


def materialize_phase4_sources(root: Path, document: dict) -> dict[str, bytes]:
    hero_path = root / "upstream" / "hero.png"
    hero_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (24, 24), (40, 180, 90, 255)).save(hero_path)
    hero_bytes = hero_path.read_bytes()

    font_bytes = b"fixture-font-binary\n"
    _write_bytes(root, "upstream/display.ttf", font_bytes)

    artifacts = {
        "upstream/hero.png": hero_bytes,
        "upstream/display.ttf": font_bytes,
    }
    manifest = {
        "schema_version": 1,
        "outputs": [
            {"path": path, "sha256": sha256(content).hexdigest()}
            for path, content in artifacts.items()
        ],
    }
    manifest_bytes = json.dumps(
        manifest, sort_keys=True, separators=(",", ":")
    ).encode()
    report_bytes = json.dumps(
        {
            "status": "pass",
            "checked_outputs": sorted(artifacts),
            "evidence": {
                "production_media": {
                    "representative": True,
                    "provenance_verified": True,
                    "source_types": ["imagegen"],
                }
            },
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    _write_bytes(root, "upstream/asset-manifest.json", manifest_bytes)
    _write_bytes(root, "upstream/validation-report.json", report_bytes)
    license_bytes = b"Project-owned commercial presentation license.\n"
    _write_bytes(root, "licenses/project-owned.txt", license_bytes)

    source_by_path = {
        item["source"]["artifact"]["path"]: item["source"]
        for item in [
            *document["inventory"]["assets"],
            *document["brand_kit"]["fonts"],
        ]
    }
    for path, source in source_by_path.items():
        source["artifact"]["sha256"] = sha256(artifacts[path]).hexdigest()
        source["manifest"]["sha256"] = sha256(manifest_bytes).hexdigest()
        source["validation_report"]["sha256"] = sha256(report_bytes).hexdigest()
    document["licenses"][0]["evidence"]["sha256"] = sha256(license_bytes).hexdigest()
    document["provenance"][0]["sha256"] = sha256(hero_bytes).hexdigest()
    return artifacts


def test_prepare_presentation_is_a_deterministic_public_contract_boundary() -> None:
    from presentation_pipeline import prepare_presentation

    source = phase4_presentation()
    reordered = deepcopy(source)
    reordered["brief"] = dict(reversed(list(reordered["brief"].items())))

    prepared = prepare_presentation(source)
    prepared_again = prepare_presentation(reordered)

    assert prepared["kind"] == "prepared-presentation"
    assert prepared["schema_version"] == 1
    assert prepared["presentation"] == source
    assert prepared["presentation_sha256"].startswith("sha256:")
    assert prepared["presentation_sha256"] == prepared_again["presentation_sha256"]


def test_resolve_presentation_copies_verified_imports_to_content_addressed_store(
    tmp_path: Path,
) -> None:
    from presentation_pipeline import prepare_presentation, resolve_presentation

    source = phase4_presentation()
    original_bytes = materialize_phase4_sources(tmp_path, source)
    prepared = prepare_presentation(source)

    resolved = resolve_presentation(prepared, tmp_path)

    assert resolved["kind"] == "resolved-presentation"
    assert [item["id"] for item in resolved["imports"]] == [
        "asset:hero",
        "font:display-font",
    ]
    assert resolved["imports"][0]["production_media"]["representative"] is True
    for item in resolved["imports"]:
        content_path = item["content_path"]
        assert content_path.startswith("presentation/content-addressed/")
        assert not {"raw", "frames", "atlas"} & set(Path(content_path).parts)
        assert (tmp_path / content_path).read_bytes() == original_bytes[item["source_path"]]
        assert sha256((tmp_path / item["source_path"]).read_bytes()).hexdigest() == item["sha256"]


def test_resolve_presentation_rejects_non_representative_upstream_asset(
    tmp_path: Path,
) -> None:
    from presentation_pipeline import prepare_presentation, resolve_presentation

    source = phase4_presentation()
    materialize_phase4_sources(tmp_path, source)
    report_path = tmp_path / "upstream" / "validation-report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["evidence"]["production_media"]["representative"] = False
    report_path.write_text(
        json.dumps(report, sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )
    report_hash = sha256(report_path.read_bytes()).hexdigest()
    for item in [*source["inventory"]["assets"], *source["brand_kit"]["fonts"]]:
        item["source"]["validation_report"]["sha256"] = report_hash

    with pytest.raises(ValueError, match="not representative production media"):
        resolve_presentation(prepare_presentation(source), tmp_path)


def test_resolve_presentation_rejects_fixture_source_labeled_representative(
    tmp_path: Path,
) -> None:
    from presentation_pipeline import prepare_presentation, resolve_presentation

    source = phase4_presentation()
    materialize_phase4_sources(tmp_path, source)
    report_path = tmp_path / "upstream" / "validation-report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["evidence"]["production_media"]["source_types"] = ["fixture"]
    report_path.write_text(
        json.dumps(report, sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )
    report_hash = sha256(report_path.read_bytes()).hexdigest()
    for item in [*source["inventory"]["assets"], *source["brand_kit"]["fonts"]]:
        item["source"]["validation_report"]["sha256"] = report_hash

    with pytest.raises(ValueError, match="invalid production source_types"):
        resolve_presentation(prepare_presentation(source), tmp_path)


def test_prepare_presentation_cli_writes_portable_atomic_outputs(tmp_path: Path) -> None:
    document = phase4_presentation()
    materialize_phase4_sources(tmp_path, document)
    presentation_path = tmp_path / "presentation.json"
    presentation_path.write_text(json.dumps(document), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(PREPARE_CLI),
            "--presentation",
            str(presentation_path),
            "--root",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    summary = json.loads(result.stdout)
    assert summary["ok"] is True
    assert summary["import_count"] == 2
    prepared_path = tmp_path / summary["prepared_path"]
    resolved_path = tmp_path / summary["resolved_path"]
    assert prepared_path.is_file()
    assert resolved_path.is_file()
    assert not list((tmp_path / "presentation").glob(".*.tmp"))
    resolved = json.loads(resolved_path.read_text(encoding="utf-8"))
    assert all(not Path(item["content_path"]).is_absolute() for item in resolved["imports"])


def test_prepare_presentation_cli_help_needs_no_site_packages() -> None:
    result = subprocess.run(
        [sys.executable, "-S", str(PREPARE_CLI), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "--presentation" in result.stdout


def test_prepare_presentation_cli_rejects_output_escape(tmp_path: Path) -> None:
    document = phase4_presentation()
    presentation_path = tmp_path / "presentation.json"
    presentation_path.write_text(json.dumps(document), encoding="utf-8")
    escaped = tmp_path.parent / "escaped-prepared.json"
    escaped.unlink(missing_ok=True)

    result = subprocess.run(
        [
            sys.executable,
            str(PREPARE_CLI),
            "--presentation",
            str(presentation_path),
            "--root",
            str(tmp_path),
            "--prepared",
            "../escaped-prepared.json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert not escaped.exists()
