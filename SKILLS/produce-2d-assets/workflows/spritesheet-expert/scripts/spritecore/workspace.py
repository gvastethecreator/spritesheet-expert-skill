"""Portable workspace identity, source runs, saved handoffs and delivery records."""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import re
import shutil
import tempfile
import uuid
import zipfile

from PIL import Image

from .item_delivery import artifact, validate_delivery, MAX_FILE_BYTES
from .item_segmentation import digest_file, load_json
from .item_sheet import _atomic_json
from .locks import acquire_run_lock, LOCK_FILENAME
from .workflow_lanes import describe_run, final_command

WORKSPACE_VERSION = "sprite-workspace-v1"
FOLDERS = ("imports", "runs", "logs", "exports", "handoffs")
GUIDE = """# Sprite workspace

This folder contains the project data. Move or copy the whole folder after
processing stops. Open it with an installed Spritesheet Expert skill:

    python /path/to/skill/scripts/serve_item_studio.py --workspace /path/to/this-folder

Use the current client's tools, model and permissions for agent work. Prepared
handoffs do not authorize execution or approve returned images. Host-specific
Python environments and model caches are configured by the client, outside this
workspace. Opening, reviewing and organizing saved results do not require models.

- workspace.json: stable project identity and name. Paths below are relative.
- imports/: source bytes and collection/run metadata.
- runs/: processing, masks, crops, current review head and predecessor evidence.
- exports/: saved delivery archives and their source-manifest hashes.
- handoffs/: prepared jobs and archive state, including jobs no longer in the queue.
- logs/: process logs. Old absolute paths in logs are historical evidence.

Use manage_studio_workspace.py inspect --workspace /path/to/this-folder for the
catalog. Import returned images with its import command and --job-id to connect
the result to a saved handoff. Use adopt-run to copy an existing workflow run
without changing its original. Use organize to name, group or archive a run.
Archive hides a run from the default list; it does not delete its files.

Grid, animation and tileset runs use workspace-run.json to bind their copied
artifacts to a lane. Their ZIP is a draft snapshot, not an engine delivery.
Use check_workflow.py from the installed skill for that lane's final checks.
Local item runs keep workflow.json and the shared item-atlas executor.

Review source pixels and labels before approval. Export checks current bytes;
a draft or a successful technical check is not approval for production.
"""


def now():
    return datetime.now(timezone.utc).isoformat()


def identifier(value, *, run=False):
    pattern = r"[0-9a-f]{32}" if run else r"[A-Za-z0-9_-]{1,160}"
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise ValueError("invalid run id" if run else "invalid job id")
    return value


def label(value, name, *, empty=False, maximum=160):
    if not isinstance(value, str) or len(value.strip()) > maximum or (not empty and not value.strip()):
        raise ValueError(f"{name} must be {'at most' if empty else '1 to'} {maximum} characters")
    return value.strip()


class Workspace:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.path = self.root / "workspace.json"
        self.document = load_json(self.path)
        if self.document.get("schemaVersion") != WORKSPACE_VERSION:
            raise ValueError("unsupported workspace version")
        identifier(self.document.get("id"), run=True)
        label(self.document.get("name"), "workspace name")
        for folder in FOLDERS:
            target = self.root / folder
            if not target.is_dir() or target.is_symlink() or target.resolve() != target:
                raise ValueError(f"missing or linked workspace folder: {folder}")

    @classmethod
    def create(cls, root: Path, name: str, *, adopt=False):
        root = Path(root).resolve()
        name = label(name, "workspace name")
        root.mkdir(parents=True, exist_ok=True)
        with acquire_run_lock(root, "workspace-create"):
            if (root / "workspace.json").exists():
                raise ValueError("workspace already exists; open it instead")
            entries = {p.name for p in root.iterdir()} - {LOCK_FILENAME}
            if entries and (not adopt or not entries.issubset(set(FOLDERS))):
                raise ValueError("new workspace must use an empty directory")
            for folder in FOLDERS:
                target = root / folder
                if target.is_symlink() or target.resolve() != target:
                    raise ValueError("workspace folders must not be links")
                target.mkdir(exist_ok=True)
            (root / "WORKSPACE.md").write_text(GUIDE, encoding="utf-8")
            _atomic_json(root / "workspace.json", {"schemaVersion": WORKSPACE_VERSION,
                "id": uuid.uuid4().hex, "name": name, "createdAt": now()})
        return cls(root)

    def run_root(self, run_id):
        path = self.root / "runs" / identifier(run_id, run=True)
        if path.is_symlink() or path.resolve() != path:
            raise ValueError("run directory must not be a link")
        return path

    def metadata(self, run_id):
        return load_json(artifact(self.root, f"imports/{identifier(run_id, run=True)}.json"))

    def catalog(self):
        runs, exports = [], []
        for path in sorted((self.root / "imports").glob("*.json")):
            run_id = path.stem
            try:
                meta = self.metadata(run_id)
                root = self.run_root(run_id)
                state = load_json(root / "workflow.json") if (root / "workflow.json").is_file() else {"status": "imported"}
                row = {"id": run_id, "name": meta["name"], "collection": meta.get("collection", ""),
                    "lane": meta.get("lane", "static-items"),
                    "archived": meta.get("archived", False), "jobId": meta.get("jobId"),
                    "path": f"runs/{run_id}", "status": state["status"], "processingComplete": state.get("processingComplete", False)}
                if meta.get("lane") in {"true-grid", "animation", "tileset"}:
                    envelope = load_json(artifact(root, "workspace-run.json"))
                    request = load_json(artifact(root, "sprite-request.json"))
                    manifest = envelope.get("manifest")
                    if manifest and digest_file(artifact(root, manifest)) != envelope["manifestSha256"]:
                        raise ValueError("current manifest hash mismatch")
                    row.update({"status": envelope["status"], "processingComplete": bool(manifest),
                        "reviewStatus": "pending", "manifest": f"runs/{run_id}/{manifest}" if manifest else None,
                        "manifestSha256": envelope.get("manifestSha256"),
                        "items": sum(entry.get("frames", 1) for entry in request.get("states", {}).values()),
                        "unreviewed": None, "pendingPixels": None,
                        "finalCheckArgv": final_command(meta["lane"], root, allow_imported=True),
                        "previews": [path for path in envelope["artifacts"] if path.endswith((".html", ".png", ".gif")) and path.startswith("qa/")]})
                    runs.append(row)
                    continue
                if state.get("manifest"):
                    manifest_path = artifact(root, state["manifest"])
                    if digest_file(manifest_path) != state.get("manifestSha256"):
                        raise ValueError("current manifest hash mismatch")
                    manifest = load_json(manifest_path)
                    row.update({"manifest": f"runs/{run_id}/{state['manifest']}", "manifestSha256": state["manifestSha256"],
                        "items": len(manifest["items"]), "pendingPixels": manifest["completion"].get("pendingPixels", 0),
                        "unreviewed": sum(i.get("review", {}).get("status") != "approved" for i in manifest["items"])})
                runs.append(row)
            except (ValueError, OSError, KeyError, TypeError) as exc:
                runs.append({"id": run_id, "name": run_id, "status": "invalid", "error": str(exc)})
        for path in sorted((self.root / "exports").glob("*/record.json")):
            try:
                record = load_json(artifact(self.root, path.relative_to(self.root).as_posix()))
                artifact(self.root, record["path"])
                exports.append(record)
            except (ValueError, OSError, KeyError, TypeError) as exc:
                exports.append({"id": path.parent.name, "error": str(exc)})
        return {**self.document, "root": str(self.root), "runs": runs, "exports": exports,
                "collections": sorted({r.get("collection") for r in runs if r.get("collection")})}

    def import_image(self, data: bytes, name: str, *, collection="", job_id=None):
        name, collection = label(name, "source name"), label(collection, "collection", empty=True)
        if not 0 < len(data) <= 128 * 1024 * 1024:
            raise ValueError("source must be between 1 byte and 128 MiB")
        with Image.open(BytesIO(data)) as image:
            if image.width * image.height > 50_000_000:
                raise ValueError("source exceeds 50 million pixels")
            image.load()
            if "A" not in image.getbands() or image.getchannel("A").getextrema()[0] == 255:
                raise ValueError("this workflow requires a transparent source image")
        run_id = uuid.uuid4().hex
        with acquire_run_lock(self.root, "workspace-import"):
            if job_id:
                artifact(self.root, f"handoffs/{identifier(job_id)}.json")
            (self.root / "imports" / f"{run_id}.png").write_bytes(data)
            _atomic_json(self.root / "imports" / f"{run_id}.json", {"name": name,
                "lane": "static-items",
                "sha256": sha256(data).hexdigest(), "collection": collection, "jobId": job_id,
                "archived": False, "createdAt": now()})
        return {"id": run_id, "workspaceId": self.document["id"]}

    def organize(self, run_id, changes):
        allowed = {"name", "collection", "archived"}
        if not isinstance(changes, dict) or not changes or set(changes) - allowed:
            raise ValueError("organize accepts name, collection and archived")
        with acquire_run_lock(self.root, "workspace-organize"):
            meta = self.metadata(run_id)
            for key, value in changes.items():
                if key == "archived":
                    if type(value) is not bool:
                        raise ValueError("archived must be a boolean")
                else:
                    value = label(value, key, empty=key == "collection")
                meta[key] = value
            _atomic_json(self.root / "imports" / f"{run_id}.json", meta)
        return meta

    def handoffs(self):
        return [load_json(artifact(self.root, f"handoffs/{p.name}"))
                for p in sorted((self.root / "handoffs").glob("*.json"))]

    def handoff(self, payload):
        with acquire_run_lock(self.root, "workspace-handoff"):
            if payload.get("kind") == "add":
                job = payload.get("job")
                if not isinstance(job, dict) or job.get("schemaVersion") != "studio-handoff-v1":
                    raise ValueError("expected a studio-handoff-v1 job")
                job_id = identifier(job.get("jobId"))
                if len(json.dumps(job).encode()) > 256 * 1024 or not isinstance(job.get("prompt"), str):
                    raise ValueError("job must contain a prompt and fit in 256 KiB")
                path = self.root / "handoffs" / f"{job_id}.json"
                if path.exists():
                    raise ValueError("job id already exists")
                _atomic_json(path, {"job": job, "archived": False, "savedAt": now()})
            elif payload.get("kind") == "archive":
                ids = payload.get("jobIds")
                if not isinstance(ids, list) or not ids or len(ids) > 1000:
                    raise ValueError("select 1 to 1000 jobs")
                records = [(artifact(self.root, f"handoffs/{identifier(i)}.json"), None) for i in ids]
                records = [(p, load_json(p)) for p, _ in records]
                for path, record in records:
                    _atomic_json(path, {**record, "archived": True})
            else:
                raise ValueError("unknown handoff operation")
        return self.handoffs()

    def adopt_run(self, source: Path, *, name: str, collection="", lane=None):
        """Copy an existing workflow and preserve its current reviewed head."""
        source = Path(source).resolve()
        name, collection = label(name, "run name"), label(collection, "collection", empty=True)
        if self.root.is_relative_to(source) or source.is_relative_to(self.root):
            raise ValueError("copy from a run outside the destination workspace")
        run_id = source.name if re.fullmatch(r"[0-9a-f]{32}", source.name) else uuid.uuid4().hex
        destination = self.run_root(run_id)
        with acquire_run_lock(self.root, "workspace-adopt"), acquire_run_lock(source, "workspace-copy"):
            if destination.exists() or (self.root / "imports" / f"{run_id}.json").exists():
                raise ValueError("run already exists in this workspace")
            lane, state = describe_run(source, lane=lane)
            if lane == "static-items":
                original = artifact(source, "input/source.png")
                if digest_file(original) != state["config"]["sourceSha256"]:
                    raise ValueError("source snapshot hash mismatch")
            if state.get("manifest"):
                current = artifact(source, state["manifest"])
                if state.get("manifestSha256") and digest_file(current) != state["manifestSha256"]:
                    raise ValueError("current manifest hash mismatch")
                state["manifestSha256"] = digest_file(current)
                if lane == "static-items":
                    report = validate_delivery(current, draft=True)
                    if report["status"] != "pass":
                        raise ValueError("invalid run: " + "; ".join(report["integrityErrors"]))
            if state.get("status") == "running":
                raise ValueError("stop processing before copying a run")
            staging = Path(tempfile.mkdtemp(prefix=".import-", dir=self.root))
            try:
                total, hashes = 0, {}
                for file in source.rglob("*"):
                    if file.is_symlink() or file.resolve() != file:
                        raise ValueError("run contains a linked path")
                    if not file.is_file() or file.name in {LOCK_FILENAME, "cancel.request"}:
                        continue
                    checked = artifact(source, file.relative_to(source).as_posix())
                    total += checked.stat().st_size
                    if total > 2 * 1024 ** 3:
                        raise ValueError("run copy exceeds 2 GiB")
                    target = staging / file.relative_to(source)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(checked, target)
                    if digest_file(target) != digest_file(checked):
                        raise ValueError("run changed while copying")
                    hashes[file.relative_to(source).as_posix()] = digest_file(target)
                if lane != "static-items":
                    _atomic_json(staging / "workspace-run.json", {"schemaVersion": "workspace-run-v1", "lane": lane,
                        "manifest": state.get("manifest"), "manifestSha256": state.get("manifestSha256"),
                        "status": "review-required" if state.get("manifest") else "prepared", "artifacts": hashes})
                staging.rename(destination)
                if lane == "static-items":
                    shutil.copyfile(destination / "input/source.png", self.root / "imports" / f"{run_id}.png")
                _atomic_json(self.root / "imports" / f"{run_id}.json", {"name": name,
                    "lane": lane, "sha256": state["config"]["sourceSha256"] if lane == "static-items" else hashes["sprite-request.json"], "collection": collection,
                    "archived": False, "createdAt": now()})
            except Exception:
                # Only paths created by this attempt are rolled back. The source is untouched.
                if destination.exists() and not staging.exists():
                    destination.rename(staging)
                    (self.root / "imports" / f"{run_id}.png").unlink(missing_ok=True)
                raise
            finally:
                if staging.exists():
                    shutil.rmtree(staging)
        return {"id": run_id, "workspaceId": self.document["id"]}

    def archive_run(self, run_id):
        """Archive a component-row snapshot; this is not an engine delivery."""
        root = self.run_root(run_id)
        with acquire_run_lock(root, "workspace-snapshot"):
            envelope = load_json(artifact(root, "workspace-run.json"))
            archive = BytesIO()
            total = 0
            with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zipped:
                for relative, expected in envelope["artifacts"].items():
                    data = artifact(root, relative).read_bytes()
                    total += len(data)
                    if total > 512 * 1024 * 1024:
                        raise ValueError("snapshot exceeds 512 MiB")
                    if sha256(data).hexdigest() != expected:
                        raise ValueError("adopted snapshot hash mismatch: " + relative)
                    zipped.writestr(relative, data)
                zipped.writestr("workspace-run.json", json.dumps(envelope, indent=2))
            data = archive.getvalue()
        return self.save_export(run_id, data, envelope.get("manifestSha256"), draft=True, kind="workspace-snapshot")

    def save_export(self, run_id, data: bytes, manifest_hash: str, *, draft: bool, kind="item-atlas"):
        if len(data) > MAX_FILE_BYTES:
            raise ValueError("saved archive exceeds 256 MiB; split the run")
        export_id = uuid.uuid4().hex
        with acquire_run_lock(self.root, "workspace-export"):
            relative = f"exports/{export_id}/{'run' if kind == 'workspace-snapshot' else 'atlas'}{'-draft' if draft else ''}.zip"
            path = self.root / relative
            path.parent.mkdir()
            path.write_bytes(data)
            record = {"id": export_id, "runId": run_id, "path": relative, "draft": draft,
                "kind": kind,
                "manifestSha256": manifest_hash, "sha256": sha256(data).hexdigest(),
                "bytes": len(data), "createdAt": now()}
            _atomic_json(path.parent / "record.json", record)
        return record

    def export_file(self, export_id):
        identifier(export_id, run=True)
        record = load_json(artifact(self.root, f"exports/{export_id}/record.json"))
        path = artifact(self.root, record["path"])
        if digest_file(path) != record["sha256"]:
            raise ValueError("saved export hash mismatch")
        return path, record
