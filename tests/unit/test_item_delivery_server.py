"""Integration with the real builder/ownership API; no model/provider invocation."""
from io import BytesIO
import json
from pathlib import Path
import shutil
import sys
import zipfile

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "SKILLS/spritesheet-expert/scripts"
sys.path.insert(0, str(SCRIPTS))
from spritecore.item_sheet import build_item_atlas
from spritecore.item_ownership import apply_ownership_review
from spritecore.item_delivery import validate_delivery
from serve_item_studio import Studio
from test_item_delivery import bundle, digest


@pytest.fixture
def studio_bundle(bundle, tmp_path):
    source_root, manifest = bundle
    studio = Studio(tmp_path / "workspace", tmp_path / "no-model-runtime.json")
    run_id = "1" * 32
    root = studio.run_root(run_id)
    reviewed = root / "reviews/current"
    shutil.copytree(source_root, reviewed)
    (root / "input").mkdir()
    shutil.copyfile(source_root / "source.png", root / "input/source.png")
    (studio.workspace / "imports" / f"{run_id}.json").write_text(json.dumps({"name": "synthetic QA fixture"}), encoding="utf-8")
    state = {"status": "reviewed", "processingComplete": True, "manifest": "reviews/current/manifest.json",
        "manifestSha256": digest(reviewed / "manifest.json"),
        "config": {"sourceSha256": digest(root / "input/source.png")}}
    (root / "workflow.json").write_text(json.dumps(state), encoding="utf-8")
    return studio, run_id, reviewed, manifest


def update_manifest(studio, run_id, reviewed, manifest):
    (reviewed / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    path = studio.run_root(run_id) / "workflow.json"
    state = json.loads(path.read_text(encoding="utf-8"))
    state["manifestSha256"] = digest(reviewed / "manifest.json")
    path.write_text(json.dumps(state), encoding="utf-8")


def test_studio_counts_unflagged_pending_reviews(studio_bundle):
    studio, run_id, reviewed, manifest = studio_bundle
    manifest["items"][0]["review"]["status"] = "pending"
    update_manifest(studio, run_id, reviewed, manifest)
    assert studio.snapshot(run_id)["reviewCount"] == 1
    with pytest.raises(ValueError, match="explicit approval"):
        studio.export(run_id, {})
    with zipfile.ZipFile(BytesIO(studio.export(run_id, {"draft": True}))) as archive:
        assert json.loads(archive.read("delivery.json"))["draft"] is True
        assert json.loads(archive.read("qa/delivery-check.json"))["reviewBlockers"]


def test_studio_archive_has_current_evidence(studio_bundle):
    studio, run_id, reviewed, _ = studio_bundle
    with zipfile.ZipFile(BytesIO(studio.export(run_id, {}))) as archive:
        assert archive.read("atlas.png") == (reviewed / "atlas.png").read_bytes()
        assert "workflow-evidence/workflow.json" in archive.namelist()
        assert len(archive.namelist()) == len(set(archive.namelist()))
        receipt = json.loads(archive.read("qa/delivery-check.json"))
        assert receipt["status"] == "pass"
        assert receipt["manifestSha256"] == digest(reviewed / "manifest.json")


def test_studio_draft_does_not_bypass_hash_validation(studio_bundle):
    studio, run_id, reviewed, _ = studio_bundle
    (reviewed / "items/a.png").write_bytes(b"altered")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        studio.export(run_id, {"draft": True})


def test_start_completed_run_preserves_review_head(studio_bundle):
    studio, run_id, _, _ = studio_bundle
    path = studio.run_root(run_id) / "workflow.json"
    original = path.read_bytes()
    assert studio.start(run_id, {})["status"] == "already-complete"
    assert path.read_bytes() == original
    assert not studio.processes


def test_draft_flag_is_not_truthy_text(studio_bundle):
    studio, run_id, _, _ = studio_bundle
    with pytest.raises(ValueError, match="boolean"):
        studio.export(run_id, {"draft": "false"})


def test_studio_rejects_extra_symlink(studio_bundle):
    studio, run_id, reviewed, _ = studio_bundle
    try:
        (reviewed / "extra.png").symlink_to(reviewed / "atlas.png")
    except OSError:
        pytest.skip("symlink creation unavailable")
    with pytest.raises(ValueError, match="symlink"):
        studio.export(run_id, {})


def test_real_builder_to_ownership_review_to_delivery(bundle, tmp_path):
    root, _ = bundle
    built, reviewed = tmp_path / "compiled", tmp_path / "reviewed"
    build_item_atlas(root / "source.png", built, provenance="imported")
    path = built / "manifest.json"
    assert validate_delivery(path)["status"] == "review-required"
    document = json.loads(path.read_text(encoding="utf-8"))
    apply_ownership_review(path, {"parentManifestSha256": digest(path),
        "operations": [{"kind": "approve", "itemIds": [i["id"] for i in document["items"]]}]}, reviewed)
    result = validate_delivery(reviewed / "manifest.json")
    assert result["status"] == "pass", result
