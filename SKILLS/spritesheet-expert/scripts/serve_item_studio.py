#!/usr/bin/env python3
"""Serve the bundled Studio and a local, typed item-workflow API."""
from __future__ import annotations

import argparse
from functools import partial
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
import mimetypes
import os
from pathlib import Path
import secrets
import subprocess
import sys
import threading
from urllib.parse import unquote, urlparse
import uuid
import zipfile

from PIL import Image
from spritecore.item_segmentation import digest_file, load_json
from spritecore.item_ownership import apply_ownership_review
from spritecore.item_sheet import _atomic_json
from spritecore.item_delivery import artifact, review_blockers, validate_delivery

SCRIPTS = Path(__file__).resolve().parent
SKILL = SCRIPTS.parent


class Studio:
    def __init__(self, workspace: Path, runtime_config: Path):
        self.workspace = workspace.resolve()
        self.runtime_config = runtime_config.resolve()
        self.token = secrets.token_urlsafe(32)
        self.processes = {}
        self.lock = threading.Lock()
        for folder in ("imports", "runs", "logs"):
            (self.workspace / folder).mkdir(parents=True, exist_ok=True)

    def run_root(self, run_id):
        if not isinstance(run_id, str) or len(run_id) != 32 or any(c not in "0123456789abcdef" for c in run_id):
            raise ValueError("invalid run id")
        return self.workspace / "runs" / run_id

    def snapshot(self, run_id):
        root = self.run_root(run_id)
        imported = load_json(self.workspace / "imports" / f"{run_id}.json")
        state = load_json(root / "workflow.json") if (root / "workflow.json").exists() else {"status": "imported"}
        if state.get("config") and digest_file(root / "input/source.png") != state["config"]["sourceSha256"]:
            raise ValueError("imported source snapshot hash mismatch")
        process = self.processes.get(run_id)
        active = process is not None and process.poll() is None
        if state["status"] == "running" and not active:
            state["status"] = "interrupted"
        if state["status"] == "imported" and process is not None and process.poll() not in (None, 0):
            state["status"] = "failed"
            log = self.workspace / "logs" / f"{run_id}.log"
            state["error"] = log.read_text(encoding="utf-8", errors="replace")[-2000:]
        response = {"id": run_id, "name": imported["name"], "active": active, **state}
        manifest_relative = state.get("manifest")
        if manifest_relative:
            path = contained(root, manifest_relative)
            if state.get("manifestSha256") and digest_file(path) != state["manifestSha256"]:
                raise ValueError("manifest evidence hash mismatch")
            manifest = load_json(path)
            response["document"] = manifest
            response["manifestSha256"] = digest_file(path)
            response["artifactBase"] = f"/api/runs/{run_id}/files/{path.parent.relative_to(root).as_posix()}/"
            response["reviewCount"] = sum(item.get("review", {}).get("status") != "approved" for item in manifest["items"])
            response["reviewBlockers"] = review_blockers(manifest)
            response["pendingPixels"] = manifest["completion"].get("pendingPixels", 0)
        stage = state.get("stage")
        if stage:
            log = root / "logs" / f"{stage}.log"
            if log.exists():
                with log.open("rb") as handle:
                    handle.seek(max(0, log.stat().st_size - 4000))
                    response["log"] = handle.read().decode("utf-8", errors="replace")
        return response

    def start(self, run_id, config):
        with self.lock:
            if any(p.poll() is None for p in self.processes.values()):
                raise ValueError("another workflow is running; wait or cancel it")
            current = self.snapshot(run_id)
            if current.get("processingComplete"):
                # Starting again must not reset the active reviewed successor.
                return {"status": "already-complete", "id": run_id}
            root = self.run_root(run_id)
            metadata_path = self.workspace / "imports" / f"{run_id}.json"
            metadata = load_json(metadata_path)
            config = metadata.get("config") or config
            models = config.get("models", "standard")
            if models not in {"none", "standard", "light"}:
                raise ValueError("invalid model profile")
            quantum, padding = config.get("quantum", 32), config.get("padding", 16)
            if type(quantum) is not int or not 1 <= quantum <= 1024 or type(padding) is not int or not 0 <= padding <= 1024:
                raise ValueError("invalid grid settings")
            metadata["config"] = {"models": models, "quantum": quantum, "padding": padding}
            _atomic_json(metadata_path, metadata)
            cancel = root / "cancel.request"
            if cancel.exists():
                cancel.unlink()
            command = [sys.executable, str(SCRIPTS / "run_item_atlas_workflow.py"),
                str(self.workspace / "imports" / f"{run_id}.png"), "--output-dir", str(root),
                "--models", models, "--runtime-config", str(self.runtime_config),
                "--grid-quantum", str(quantum), "--padding", str(padding)]
            with (self.workspace / "logs" / f"{run_id}.log").open("w", encoding="utf-8") as log:
                self.processes[run_id] = subprocess.Popen(command, stdout=log, stderr=log,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            return {"status": "started", "id": run_id}

    def review(self, run_id, payload):
        with self.lock:
            state = self.snapshot(run_id)
            if state["active"]:
                raise ValueError("wait for processing before reviewing")
            if not state.get("processingComplete"):
                raise ValueError("processing is incomplete")
            root = self.run_root(run_id)
            output = root / "reviews" / uuid.uuid4().hex
            manifest = apply_ownership_review(contained(root, state["manifest"]), payload, output)
            state = load_json(root / "workflow.json")
            state["manifest"] = (output / "manifest.json").relative_to(root).as_posix()
            state["manifestSha256"] = digest_file(output / "manifest.json")
            state["status"] = "review-required" if review_blockers(manifest) else "reviewed"
            _atomic_json(root / "workflow.json", state)
            return self.snapshot(run_id)

    def export(self, run_id, payload):
        """Recheck bytes under the mutation lock; drafts only relax review gates."""
        with self.lock:
            snapshot = self.snapshot(run_id)
            if snapshot["active"] or not snapshot.get("processingComplete") or not snapshot.get("manifest"):
                raise ValueError("processing is incomplete")
            draft = payload.get("draft", False)
            if type(draft) is not bool:
                raise ValueError("draft must be a boolean")
            root = self.run_root(run_id)
            manifest_path = contained(root, snapshot["manifest"])
            report = validate_delivery(manifest_path, draft=draft)
            if report["status"] != "pass":
                raise ValueError("delivery blocked: " + "; ".join(report["integrityErrors"] + report["reviewBlockers"]))
            if report["manifestSha256"] != snapshot["manifestSha256"]:
                raise ValueError("manifest changed during delivery validation")
            folder = manifest_path.parent
            expected = {folder / relative: digest for relative, digest in report["verifiedArtifacts"].items()}
            expected[manifest_path] = report["manifestSha256"]
            archive = BytesIO()
            total_bytes = 0
            with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zipped:
                def add(file, name):
                    nonlocal total_bytes
                    checked = artifact(root, file.relative_to(root).as_posix())
                    total_bytes += checked.stat().st_size
                    if total_bytes > 512 * 1024 * 1024:
                        raise ValueError("archive exceeds 512 MiB; use the CLI export or split the run")
                    data = checked.read_bytes()
                    if file in expected and sha256(data).hexdigest() != expected[file]:
                        raise ValueError("artifact changed while packaging: " + name)
                    zipped.writestr(name, data)
                for file in sorted(folder.rglob("*")):
                    if file.is_file() or file.is_symlink():
                        name = file.relative_to(folder).as_posix()
                        if name not in {"delivery.json", "qa/delivery-check.json"}:
                            add(file, name)
                zipped.writestr("qa/delivery-check.json", json.dumps(report, indent=2))
                zipped.writestr("delivery.json", json.dumps({"draft": draft, "manifest": manifest_path.name,
                    "manifestSha256": report["manifestSha256"], "check": "qa/delivery-check.json",
                    "engineSmokeTested": False}))
                for relative in ("workflow.json", "input", "segmentation", "classification"):
                    evidence = root / relative
                    paths = sorted(evidence.rglob("*")) if evidence.is_dir() else [evidence]
                    for file in paths:
                        if file.is_file() or file.is_symlink():
                            add(file, "workflow-evidence/" + file.relative_to(root).as_posix())
                for relative in ("alpha", "segmented", "reviews"):
                    for file in sorted((root / relative).rglob("manifest*.json")):
                        add(file, "workflow-evidence/manifests/" + file.relative_to(root).as_posix())
            return archive.getvalue()


def contained(root, relative):
    path = (root / unquote(relative)).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("path escapes workspace")
    return path


class Handler(BaseHTTPRequestHandler):
    def __init__(self, *args, studio, **kwargs):
        self.studio = studio
        super().__init__(*args, **kwargs)

    def log_message(self, *_):
        pass

    def send(self, data, content_type="application/json", status=200):
        if not isinstance(data, bytes):
            data = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def same_origin(self):
        host = self.headers.get("Host", "")
        allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        return host in allowed and self.headers.get("Origin", f"http://{host}") == f"http://{host}"

    def do_GET(self):
        try:
            if not self.same_origin():
                return self.send({"error": "local origin required"}, status=403)
            path = urlparse(self.path).path
            if path == "/api/session":
                runtime = load_json(self.studio.runtime_config) if self.studio.runtime_config.exists() else None
                profiles = []
                if runtime:
                    profiles = [p for p in ("standard", "light") if (Path(runtime["modelCacheDir"]) / f"checkpoints-{p}.json").is_file()]
                return self.send({"token": self.studio.token, "modelProfiles": profiles, "runtimeReady": runtime is not None})
            if path == "/api/runs":
                return self.send([self.studio.snapshot(p.stem) for p in sorted((self.studio.workspace / "imports").glob("*.json"))])
            pieces = path.strip("/").split("/")
            if pieces[:2] == ["api", "runs"] and len(pieces) >= 3:
                root = self.studio.run_root(pieces[2])
                if len(pieces) == 3:
                    return self.send(self.studio.snapshot(pieces[2]))
                if pieces[3] == "files":
                    file = contained(root, "/".join(pieces[4:]))
                    return self.send(file.read_bytes(), mimetypes.guess_type(file.name)[0] or "application/octet-stream")
            if path == "/skill":
                return self.send((SKILL / "SKILL.md").read_bytes(), "text/plain; charset=utf-8")
            file = contained(SKILL / "studio", path.lstrip("/") or "index.html")
            return self.send(file.read_bytes(), mimetypes.guess_type(file.name)[0] or "application/octet-stream")
        except (ValueError, OSError, KeyError) as exc:
            self.send({"error": str(exc)}, status=404)

    def do_POST(self):
        try:
            if not self.same_origin() or self.headers.get("X-Studio-Token") != self.studio.token:
                return self.send({"error": "session token required"}, status=403)
            size = int(self.headers.get("Content-Length", 0))
            if not 0 < size <= 128 * 1024 * 1024:
                raise ValueError("request size must be between 1 byte and 128 MiB")
            body = self.rfile.read(size)
            path = urlparse(self.path).path
            if path == "/api/import":
                with Image.open(BytesIO(body)) as opened:
                    if opened.width * opened.height > 50_000_000:
                        raise ValueError("source exceeds 50 million pixels")
                    opened.load()
                    if "A" not in opened.getbands() or opened.getchannel("A").getextrema()[0] == 255:
                        raise ValueError("this workflow requires a transparent source image")
                run_id = uuid.uuid4().hex
                (self.studio.workspace / "imports" / f"{run_id}.png").write_bytes(body)
                _atomic_json(self.studio.workspace / "imports" / f"{run_id}.json",
                    {"name": unquote(self.headers.get("X-Filename", "source.png")),
                     "sha256": digest_file(self.studio.workspace / "imports" / f"{run_id}.png")})
                return self.send({"id": run_id})
            payload = json.loads(body)
            if not isinstance(payload, dict):
                raise ValueError("operation payload must be an object")
            pieces = path.strip("/").split("/")
            if pieces[:2] != ["api", "runs"] or len(pieces) != 4:
                raise ValueError("unknown operation")
            run_id, operation = pieces[2:]
            root = self.studio.run_root(run_id)
            if operation == "start":
                return self.send(self.studio.start(run_id, payload))
            if operation == "cancel":
                root.mkdir(parents=True, exist_ok=True)
                (root / "cancel.request").touch()
                return self.send({"status": "cancellation-requested"})
            if operation == "review":
                return self.send(self.studio.review(run_id, payload))
            if operation == "export":
                return self.send(self.studio.export(run_id, payload), "application/zip")
            raise ValueError("unknown operation")
        except Exception as exc:
            self.send({"error": str(exc)}, status=400)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=SKILL / ".local/studio-workspace")
    parser.add_argument("--runtime-config", type=Path, default=SKILL / ".local/item-model-runtime.json")
    parser.add_argument("--port", type=int, default=4173)
    args = parser.parse_args()
    studio = Studio(args.workspace, args.runtime_config)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), partial(Handler, studio=studio))
    print(f"Spritesheet Expert Studio: http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        for run_id, process in studio.processes.items():
            if process.poll() is None:
                (studio.run_root(run_id) / "cancel.request").touch()
        server.server_close()


if __name__ == "__main__":
    main()
