"""Integration with the real builder/ownership API; no model/provider invocation."""
from io import BytesIO
import json
from pathlib import Path
import shutil
import sys
import subprocess
import zipfile

import pytest
from PIL import Image

SCRIPTS = Path(__file__).resolve().parents[2] / "SKILLS/spritesheet-expert/scripts"
sys.path.insert(0, str(SCRIPTS))
from spritecore.item_sheet import build_item_atlas
from spritecore.item_ownership import apply_ownership_review
from spritecore.item_delivery import validate_delivery
from serve_item_studio import Studio
from spritecore.workspace import Workspace
from spritecore.locks import acquire_run_lock, RunLockHeldError
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
    state = {"schemaVersion": "item-atlas-workflow-v1", "status": "reviewed", "processingComplete": True, "manifest": "reviews/current/manifest.json",
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


def test_workspace_copy_relocation_and_saved_delivery(studio_bundle, tmp_path):
    studio, run_id, reviewed, _ = studio_bundle
    original = (studio.run_root(run_id) / "workflow.json").read_bytes()
    store = Workspace.create(tmp_path / "project", "Portable project")
    assert store.adopt_run(studio.run_root(run_id), name="Heraldry", collection="Symbols")["id"] == run_id
    store.handoff({"kind": "add", "job": {"schemaVersion": "studio-handoff-v1", "jobId": "studio-test",
        "prompt": "Review the source with the current client's tools.", "inputs": {"source": "imports/source.png"}}})
    linked = store.import_image((reviewed / "source.png").read_bytes(), "Returned source", job_id="studio-test")["id"]
    store.organize(run_id, {"archived": True})
    saved = Studio(store.root, tmp_path / "absent.json").export(run_id, {}, saved=True)
    old_archive = store.export_file(saved["id"])[0].read_bytes()
    relocated = tmp_path / "another host" / "workspace"
    shutil.copytree(store.root, relocated)
    moved = Studio(relocated, tmp_path / "absent.json")
    assert moved.store.document == store.document
    assert moved.snapshot(run_id)["manifestSha256"] == digest(reviewed / "manifest.json")
    assert moved.store.metadata(linked)["jobId"] == "studio-test"
    assert moved.store.metadata(run_id)["collection"] == "Symbols"
    assert moved.store.metadata(run_id)["archived"] is True
    assert moved.store.handoffs() == store.handoffs()
    assert moved.store.export_file(saved["id"])[0].read_bytes() == old_archive
    assert (studio.run_root(run_id) / "workflow.json").read_bytes() == original
    assert moved.store.catalog()["runs"][0].get("path", "").startswith("runs/")
    moved.store.export_file(saved["id"])[0].write_bytes(b"changed archive")
    with pytest.raises(ValueError, match="export hash mismatch"):
        moved.store.export_file(saved["id"])


def test_workspace_preserves_row_lane_snapshot_after_relocation(tmp_path):
    from unpack_atlas_run import import_pngs
    source, run = tmp_path / "item.png", tmp_path / "static-set"
    Image.new("RGBA", (12, 12), (10, 20, 30, 255)).save(source)
    run.mkdir()
    import_pngs(run, [source], "items", ["token"], source_type="fixture")
    store = Workspace.create(tmp_path / "workspace", "All lanes")
    saved_run = store.adopt_run(run, name="Static set")
    assert store.catalog()["runs"][0]["lane"] == "true-grid"
    assert store.catalog()["runs"][0]["reviewStatus"] == "pending"
    moved_root = tmp_path / "relocated"
    shutil.copytree(store.root, moved_root)
    moved = Workspace(moved_root)
    archived = moved.archive_run(saved_run["id"])
    assert archived["kind"] == "workspace-snapshot" and archived["draft"] is True
    assert str(moved_root) in " ".join(moved.catalog()["runs"][0]["finalCheckArgv"])
    (moved.run_root(saved_run["id"]) / "frames/items/frame-0.png").write_bytes(b"changed")
    with pytest.raises(ValueError, match="hash"):
        moved.archive_run(saved_run["id"])


def test_workspace_handoff_conflict_archive_and_run_copy_failure(studio_bundle, tmp_path):
    studio, run_id, reviewed, _ = studio_bundle
    store = Workspace.create(tmp_path / "destination", "Review queue")
    job = {"schemaVersion": "studio-handoff-v1", "jobId": "prepared-1", "prompt": "Inspect only."}
    store.handoff({"kind": "add", "job": job})
    with pytest.raises(ValueError, match="already exists"):
        store.handoff({"kind": "add", "job": {**job, "prompt": "overwrite"}})
    records = store.handoff({"kind": "archive", "jobIds": [job["jobId"]]})
    assert records[0]["archived"] and records[0]["job"] == job
    with pytest.raises(ValueError, match="invalid job id"):
        store.handoff({"kind": "add", "job": {**job, "jobId": "../escape"}})
    (reviewed / "items/a.png").write_bytes(b"corrupted crop")
    with pytest.raises(ValueError, match="invalid run"):
        store.adopt_run(studio.run_root(run_id), name="Invalid")
    assert store.catalog()["runs"] == [] and not store.run_root(run_id).exists()
    assert not list(store.root.glob(".import-*"))


def test_studio_mutations_respect_the_shared_run_lock(studio_bundle):
    studio, run_id, _, _ = studio_bundle
    state = (studio.run_root(run_id) / "workflow.json").read_bytes()
    with acquire_run_lock(studio.run_root(run_id), "other-writer"):
        with pytest.raises(RunLockHeldError):
            studio.review(run_id, {})
        with pytest.raises(RunLockHeldError):
            studio.export(run_id, {})
    assert (studio.run_root(run_id) / "workflow.json").read_bytes() == state
    assert studio.store.catalog()["exports"] == []


def test_completed_cli_replay_keeps_reviewed_head_without_model_runtime(studio_bundle, tmp_path):
    studio, run_id, reviewed, _ = studio_bundle
    from run_item_atlas_workflow import parser
    source = tmp_path / "original.png"
    shutil.copyfile(reviewed / "source.png", source)
    root = studio.run_root(run_id)
    arguments = [str(source), "--output-dir", str(root), "--runtime-config", str(tmp_path / "missing.json")]
    args = parser().parse_args(arguments)
    path = root / "workflow.json"
    state = json.loads(path.read_text())
    state["config"].update(models="standard", quantum=32, padding=16, maxWidth=0,
                           provenance="imported", taxonomySha256=digest(args.taxonomy))
    state["config"]["budgets"] = {key: getattr(args, key) for key in ("max_height", "max_pages", "max_page_pixels", "max_total_pixels")}
    path.write_text(json.dumps(state))
    original = path.read_bytes()
    replay = subprocess.run([sys.executable, str(SCRIPTS / "run_item_atlas_workflow.py"), *arguments], capture_output=True, text=True)
    assert replay.returncode == 0, replay.stdout + replay.stderr
    assert path.read_bytes() == original
    assert not studio.processes
    (reviewed / "manifest.json").write_text("{}")
    failed = subprocess.run([sys.executable, str(SCRIPTS / "run_item_atlas_workflow.py"), *arguments], capture_output=True, text=True)
    assert failed.returncode == 1 and "current manifest hash mismatch" in failed.stdout
    assert json.loads(path.read_text())["processingComplete"] is False
