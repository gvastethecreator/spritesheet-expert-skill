from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
import subprocess
import sys
import pytest

from PIL import Image, ImageDraw


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_ROOT = REPO_ROOT / "SKILLS" / "spritesheet-expert" / "scripts"


def _source(path: Path) -> None:
    image = Image.new("RGBA", (140, 100), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((7, 8, 39, 51), fill=(185, 52, 40, 255))
    draw.rectangle((72, 5, 127, 30), fill=(75, 135, 195, 255))
    draw.ellipse((57, 56, 91, 90), fill=(205, 168, 68, 255))
    image.save(path)


def _run(*arguments: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *arguments],
        cwd=cwd or REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_item_atlas_cli_build_classify_and_review_round_trip(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    run = tmp_path / "run"
    _source(source)

    built = _run(
        str(SCRIPT_ROOT / "build_deterministic_item_atlas.py"),
        str(source),
        "--output-dir",
        str(run),
        "--provenance",
        "fixture",
        "--grid-quantum",
        "16",
        "--padding",
        "8",
        "--max-width",
        "256",
    )
    assert built.returncode == 0, built.stderr or built.stdout
    built_payload = json.loads(built.stdout)
    assert built_payload["status"] == "pass"
    assert built_payload["item_count"] == 3

    manifest_path = run / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert len(manifest["items"]) == 3
    assert manifest["source"]["provenance"] == "fixture"

    taxonomy = (
        REPO_ROOT
        / "SKILLS"
        / "spritesheet-expert"
        / "references"
        / "taxonomies"
        / "generic-props-v1.json"
    )
    jobs = run / "inference" / "jobs.jsonl"
    prepared = _run(
        str(SCRIPT_ROOT / "prepare_item_classification.py"),
        "--manifest",
        str(manifest_path),
        "--taxonomy",
        str(taxonomy),
        "--out",
        str(jobs),
    )
    assert prepared.returncode == 0, prepared.stderr or prepared.stdout
    job_lines = [json.loads(line) for line in jobs.read_text(encoding="utf-8").splitlines()]
    assert len(job_lines) == 3
    assert all(job["expected"]["count"] == 1 for job in job_lines)
    assert all(job["itemId"] for job in job_lines)
    assert all(job["sourceManifest"]["sha256"] for job in job_lines)
    assert all("families" in job["taxonomy"] for job in job_lines)

    results = run / "inference" / "results.jsonl"
    results.write_text(
        "".join(
            json.dumps(
                {
                    "schemaVersion": "item-classification-result-v1",
                    "itemId": job["itemId"],
                    "model": "fixture-classifier",
                    "classification": {
                        "family": "unknown",
                        "canonicalType": "unknown",
                        "subtype": None,
                        "materials": [],
                        "condition": [],
                        "orientation": "unknown",
                        "sizeClass": "unknown",
                        "tags": ["fixture"],
                        "confidence": 0.2,
                        "source": "fixture-classifier",
                        "notes": "low-confidence fixture",
                    },
                }
            )
            + "\n"
            for job in job_lines
        ),
        encoding="utf-8",
    )
    classified_path = run / "manifest.classified.json"
    applied = _run(
        str(SCRIPT_ROOT / "apply_item_classification.py"),
        "--manifest",
        str(manifest_path),
        "--results",
        str(results),
        "--taxonomy",
        str(taxonomy),
        "--minimum-confidence",
        "0.6",
        "--require-complete",
        "--out",
        str(classified_path),
    )
    assert applied.returncode == 0, applied.stderr or applied.stdout
    classified = json.loads(classified_path.read_text(encoding="utf-8"))
    assert classified["parentManifestSha256"]
    assert classified["completion"]["classificationComplete"] is True
    assert all(
        item["classification"]["canonicalType"] == "unknown"
        for item in classified["items"]
    )
    assert all(
        "low_classification_confidence" in item["qaFlags"]
        for item in classified["items"]
    )

    review_workspace = tmp_path / "review-workspace"
    review_workspace.mkdir()
    replacement_item = classified["items"][0]
    replacement = review_workspace / "replacement.png"
    replacement_image = Image.new("RGBA", (44, 31), (0, 0, 0, 0))
    ImageDraw.Draw(replacement_image).rectangle((4, 4, 39, 26), fill=(60, 170, 95, 255))
    replacement_image.save(replacement)

    replacement_sha = sha256(replacement.read_bytes()).hexdigest()
    review_items = []
    for index, item in enumerate(classified["items"]):
        if index == 0:
            review_items.append(
                {
                    "itemId": item["id"],
                    "status": "replace",
                    "notes": "approved replacement fixture",
                    "classification": {
                        "family": "unknown",
                        "canonicalType": "unknown",
                        "tags": ["replacement"],
                    },
                    "replacement": {
                        "path": replacement.name,
                        "sha256": replacement_sha,
                        "provenance": "fixture",
                    },
                }
            )
        else:
            review_items.append(
                {
                    "itemId": item["id"],
                    "status": "approved",
                    "notes": "approved fixture",
                    "classification": item["classification"],
                    "replacement": None,
                }
            )
    review_path = review_workspace / "item-review.json"
    review_path.write_text(
        json.dumps(
            {
                "schemaVersion": "item-review-v1",
                "kind": "deterministic-item-review",
                "reviewId": "fixture-review",
                "runId": classified["runId"],
                "sourceManifest": {
                    "filename": classified_path.name,
                    "sha256": sha256(classified_path.read_bytes()).hexdigest(),
                },
                "createdAt": "2026-09-04T00:00:00Z",
                "items": review_items,
                "summary": {"approved": 2, "replace": 1},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    reviewed_run = tmp_path / "reviewed-run"
    reviewed = _run(
        str(SCRIPT_ROOT / "apply_item_review.py"),
        "--manifest",
        str(classified_path),
        "--review",
        str(review_path),
        "--output-dir",
        str(reviewed_run),
    )
    assert reviewed.returncode == 0, reviewed.stderr or reviewed.stdout
    reviewed_manifest = json.loads((reviewed_run / "manifest.json").read_text(encoding="utf-8"))
    assert reviewed_manifest["parentManifestSha256"]
    assert reviewed_manifest["completion"]["reviewComplete"] is True
    assert reviewed_manifest["reviewApplication"]["replacementCount"] == 1
    assert (reviewed_run / "atlas.png").is_file()
    assert (reviewed_run / "qa/atlas-grid.png").is_file()
    assert (reviewed_run / "qa/source-components.png").is_file()
    assert all(
        (reviewed_run / item["artifacts"]["lightComposite"]).is_file()
        and (reviewed_run / item["artifacts"]["darkComposite"]).is_file()
        for item in reviewed_manifest["items"]
    )
    replaced = next(item for item in reviewed_manifest["items"] if item["id"] == replacement_item["id"])
    assert replaced["geometry"]["originalSize"] == [44, 31]
    assert replaced["geometry"]["scale"] == 1
    assert replaced["geometry"]["rotated"] is False
    assert "replacement_imported" in replaced["qaFlags"]
    assert (reviewed_run / replaced["review"]["replacement"]["sourcePath"]).is_file()


def test_review_cli_rejects_unresolved_regeneration(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    run = tmp_path / "run"
    _source(source)
    built = _run(
        str(SCRIPT_ROOT / "build_deterministic_item_atlas.py"),
        str(source),
        "--output-dir",
        str(run),
        "--provenance",
        "fixture",
    )
    assert built.returncode == 0
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    review = tmp_path / "review.json"
    review.write_text(
        json.dumps(
            {
                "schemaVersion": "item-review-v1",
                "kind": "deterministic-item-review",
                "reviewId": "blocked-review",
                "runId": manifest["runId"],
                "sourceManifest": {
                    "filename": "manifest.json",
                    "sha256": sha256((run / "manifest.json").read_bytes()).hexdigest(),
                },
                "createdAt": "2026-09-04T00:00:00Z",
                "items": [
                    {
                        "itemId": item["id"],
                        "status": "regenerate" if index == 0 else "approved",
                        "notes": "",
                        "classification": item["classification"],
                        "replacement": None,
                    }
                    for index, item in enumerate(manifest["items"])
                ],
                "summary": {"approved": 2, "regenerate": 1},
            }
        ),
        encoding="utf-8",
    )

    blocked = _run(
        str(SCRIPT_ROOT / "apply_item_review.py"),
        "--manifest",
        str(run / "manifest.json"),
        "--review",
        str(review),
        "--output-dir",
        str(tmp_path / "blocked"),
    )

    assert blocked.returncode == 1
    payload = json.loads(blocked.stdout)
    assert payload["status"] == "contract-failure"
    assert "unresolved items" in payload["errors"][0]
    assert not (tmp_path / "blocked").exists()


def test_review_cli_rejects_manifest_hash_mismatch_without_output(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    run = tmp_path / "run"
    _source(source)
    built = _run(
        str(SCRIPT_ROOT / "build_deterministic_item_atlas.py"),
        str(source),
        "--output-dir",
        str(run),
        "--provenance",
        "fixture",
    )
    assert built.returncode == 0, built.stderr or built.stdout
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    review = tmp_path / "mismatched-review.json"
    review.write_text(
        json.dumps(
            {
                "schemaVersion": "item-review-v1",
                "kind": "deterministic-item-review",
                "reviewId": "mismatched-review",
                "runId": manifest["runId"],
                "sourceManifest": {"filename": "manifest.json", "sha256": "0" * 64},
                "createdAt": "2026-09-04T00:00:00Z",
                "items": [
                    {
                        "itemId": item["id"],
                        "status": "approved",
                        "notes": "",
                        "classification": item["classification"],
                        "replacement": None,
                    }
                    for item in manifest["items"]
                ],
                "summary": {"approved": len(manifest["items"])},
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "mismatched-output"

    rejected = _run(
        str(SCRIPT_ROOT / "apply_item_review.py"),
        "--manifest",
        str(run / "manifest.json"),
        "--review",
        str(review),
        "--output-dir",
        str(output),
    )

    assert rejected.returncode == 1
    assert "sourceManifest.sha256 does not match" in rejected.stdout
    assert not output.exists()


def test_workflow_cancel_resume_and_changed_evidence(tmp_path: Path) -> None:
    source, output = tmp_path / "source.png", tmp_path / "workflow"
    _source(source)
    output.mkdir()
    cancel = output / "cancel.request"
    cancel.touch()
    command = (str(SCRIPT_ROOT / "run_item_atlas_workflow.py"), str(source), "--output-dir", str(output), "--models", "none")
    cancelled = _run(*command)
    assert cancelled.returncode == 1
    state = json.loads((output / "workflow.json").read_text())
    assert state["status"] == "cancelled" and not state["processingComplete"]
    cancel.unlink()
    finished = _run(*command)
    assert finished.returncode == 0, finished.stdout + finished.stderr
    state = json.loads((output / "workflow.json").read_text())
    assert state["processingComplete"] and state["manifest"]
    original = (output / state["manifest"]).read_bytes()
    resumed = _run(*command)
    assert resumed.returncode == 0
    assert (output / state["manifest"]).read_bytes() == original
    (output / "alpha/atlas.png").write_bytes(b"tampered")
    rejected = _run(*command)
    assert rejected.returncode == 1 and "evidence changed" in rejected.stdout
    assert not json.loads((output / "workflow.json").read_text())["processingComplete"]


def test_local_studio_review_is_hash_bound_and_export_gates_pending(tmp_path: Path) -> None:
    from serve_item_studio import Studio
    from spritecore.item_sheet import build_item_atlas
    run_id = "a"*32
    studio = Studio(tmp_path / "studio", tmp_path / "missing-runtime.json")
    source = studio.workspace / "imports" / f"{run_id}.png"
    _source(source)
    (source.with_suffix(".json")).write_text(json.dumps({"name":"fixture.png"}))
    root = studio.run_root(run_id)
    manifest = build_item_atlas(source, root / "alpha", provenance="fixture")
    (root / "workflow.json").write_text(json.dumps({"status":"review-required", "processingComplete":True,"manifest":"alpha/manifest.json"}))
    snapshot = studio.snapshot(run_id)
    with pytest.raises(ValueError, match="stale review"):
        studio.review(run_id, {"parentManifestSha256":"0"*64, "operations":[]})
    reviewed = studio.review(run_id, {"parentManifestSha256":snapshot["manifestSha256"], "operations":[
        {"kind":"approve", "itemIds":[item["id"] for item in manifest["items"]]}]})
    assert reviewed["status"] == "ready"
    assert reviewed["document"]["completion"]["reviewComplete"]
