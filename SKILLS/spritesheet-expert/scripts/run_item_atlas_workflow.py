#!/usr/bin/env python3
"""Run or resume source inspection, local inference, packing, and review preparation."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

from spritecore.item_segmentation import digest_file, load_json
from spritecore.item_sheet import _atomic_json
from spritecore.locks import acquire_run_lock, LOCK_FILENAME

SCRIPTS = Path(__file__).resolve().parent
SKILL = SCRIPTS.parent


def artifact_hashes(root: Path, relative: str) -> dict[str, str]:
    target = root / relative
    paths = sorted(target.rglob("*")) if target.is_dir() else [target]
    return {p.relative_to(root).as_posix(): digest_file(p) for p in paths if p.is_file()}


def run_workflow(args) -> dict:
    root = args.output_dir.resolve()
    source = args.source.resolve()
    if source.is_relative_to(root):
        raise ValueError("output cannot contain the source")
    config = {"sourceSha256": digest_file(source), "models": args.models,
              "quantum": args.grid_quantum, "padding": args.padding, "maxWidth": args.max_width,
              "provenance": args.provenance, "taxonomySha256": digest_file(args.taxonomy)}
    code_digest = sha256()
    for path in sorted(SCRIPTS.rglob("*.py")):
        code_digest.update(path.relative_to(SCRIPTS).as_posix().encode())
        code_digest.update(path.read_bytes())
    config["compilerSha256"] = code_digest.hexdigest()
    environment = os.environ.copy()
    model_python, checkpoint = None, None
    if args.models != "none":
        runtime = load_json(args.runtime_config.resolve())
        model_python = Path(runtime["python"])
        cache = Path(runtime["modelCacheDir"])
        if not model_python.is_file():
            raise ValueError("runtime is missing; run setup_item_model_runtime.py")
        checkpoint = load_json(cache / f"checkpoints-{args.models}.json")
        config["checkpoints"] = checkpoint
        config["runtimeLockSha256"] = digest_file(SKILL / "model-runtime/uv.lock")
        config["runtimeProfile"] = runtime["profile"]
        environment.update({"HF_HOME": str(cache), "HF_HUB_CACHE": str(cache / "hub"),
                            "HF_HUB_OFFLINE": "1", "PYTHONUNBUFFERED": "1"})
    fingerprint = sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    state_path = root / "workflow.json"
    if state_path.exists():
        state = load_json(state_path)
        if state["fingerprint"] != fingerprint:
            raise ValueError("inputs or implementation changed; use a new output directory")
        if digest_file(root / "input/source.png") != config["sourceSha256"]:
            raise ValueError("imported source snapshot hash mismatch")
    else:
        if root.exists() and any(p.name not in {LOCK_FILENAME, "cancel.request"} for p in root.iterdir()):
            raise ValueError("output directory must be empty or contain a matching workflow")
        root.mkdir(parents=True, exist_ok=True)
        (root / "input").mkdir()
        shutil.copy2(source, root / "input/source.png")
        if digest_file(root / "input/source.png") != config["sourceSha256"]:
            raise ValueError("source changed during import")
        state = {"schemaVersion": "item-atlas-workflow-v1", "fingerprint": fingerprint,
                 "config": config, "status": "prepared", "stages": {}, "manifest": None}
    cancel = root / "cancel.request"
    state.setdefault("history", []).append({"event":"start", "at":datetime.now(timezone.utc).isoformat()})
    state["status"] = "running"
    state.pop("error", None)
    _atomic_json(state_path, state)
    (root / "logs").mkdir(exist_ok=True)

    def stage(name, arguments, products, python=sys.executable):
        if cancel.exists():
            raise InterruptedError("cancelled by user")
        previous = state["stages"].get(name)
        if previous and previous["status"] == "complete":
            if all((root / p).is_file() and digest_file(root / p) == h for p,h in previous["artifacts"].items()):
                return
            raise ValueError(f"stage evidence changed: {name}; use a new output directory")
        started = time.monotonic()
        state["stage"] = name
        state["stages"][name] = {"status": "running"}
        _atomic_json(state_path, state)
        command = [str(python), str(SCRIPTS / arguments[0]), *map(str, arguments[1:])]
        old_log = root / "logs" / f"{name}.log"
        if old_log.exists():
            archived = root / "logs" / f"{name}-attempt-{len(state['history'])}.log"
            shutil.copy2(old_log, archived)
            state["history"].append({"event":"retry", "stage":name, "previousLog":archived.relative_to(root).as_posix()})
            _atomic_json(state_path, state)
        with (root / "logs" / f"{name}.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen(command, stdout=log, stderr=log, env=environment, cwd=SKILL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                start_new_session=os.name != "nt")
            while process.poll() is None:
                if cancel.exists():
                    if os.name == "nt":
                        # uv's Windows venv Python launches a child interpreter.
                        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                            stdout=log, stderr=log, check=False,
                            creationflags=subprocess.CREATE_NO_WINDOW)
                    else:
                        os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        if os.name == "nt":
                            process.kill()
                        else:
                            os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                    raise InterruptedError("cancelled by user")
                time.sleep(.2)
        if process.returncode:
            raise RuntimeError(f"{name} failed ({process.returncode}); see logs/{name}.log")
        hashes = {}
        for product in products:
            found = artifact_hashes(root, product)
            if not found:
                raise ValueError(f"missing stage output: {product}")
            hashes.update(found)
        state["stages"][name] = {"status": "complete", "seconds": round(time.monotonic()-started,3), "artifacts": hashes}
        _atomic_json(state_path, state)

    try:
        stage("alpha", ["build_deterministic_item_atlas.py", root / "input/source.png", "--output-dir", root / "alpha",
            "--provenance", args.provenance, "--grid-quantum", args.grid_quantum, "--padding", args.padding,
            "--max-width", args.max_width, "--force"], ["alpha/manifest.json", "alpha/items", "alpha/qa", "alpha/atlas.png", "alpha/source.png"])
        manifest = root / "alpha/manifest.json"
        if args.models != "none":
            vision, mask = checkpoint["models"]["vision"], checkpoint["models"]["mask"]
            stage("prepare-segmentation", ["prepare_item_segmentation.py", "--manifest", manifest,
                "--out", root / "segmentation/jobs.jsonl", "--force"], ["segmentation/jobs.jsonl", "alpha/inference"])
            stage("segment", ["run_item_model_worker.py", "--task", "segment", "--jobs", root / "segmentation/jobs.jsonl",
                "--run-root", manifest.parent, "--out", root / "segmentation/results.jsonl", "--model", vision["id"],
                "--revision", vision["revision"], "--mask-model", mask["id"], "--mask-revision", mask["revision"],
                "--max-new-tokens", 1024, "--local-files-only", "--force"], ["segmentation"], model_python)
            stage("pack", ["apply_item_segmentation.py", "--manifest", manifest, "--jobs", root / "segmentation/jobs.jsonl",
                "--results", root / "segmentation/results.jsonl", "--output-dir", root / "segmented", "--force"], ["segmented"])
            manifest = root / "segmented/manifest.json"
            stage("prepare-classification", ["prepare_item_classification.py", "--manifest", manifest,
                "--taxonomy", args.taxonomy.resolve(), "--out", root / "classification/jobs.jsonl", "--force"], ["classification/jobs.jsonl"])
            stage("classify", ["run_item_model_worker.py", "--task", "classify", "--jobs", root / "classification/jobs.jsonl",
                "--run-root", manifest.parent, "--out", root / "classification/results.jsonl", "--model", vision["id"],
                "--revision", vision["revision"], "--max-new-tokens", 768, "--local-files-only", "--force"], ["classification/results.jsonl"], model_python)
            stage("apply-classification", ["apply_item_classification.py", "--manifest", manifest,
                "--taxonomy", args.taxonomy.resolve(), "--results", root / "classification/results.jsonl",
                "--out", manifest.parent / "manifest.classified.json", "--require-complete", "--force"], ["segmented/manifest.classified.json"])
            manifest = manifest.parent / "manifest.classified.json"
        state["manifest"] = manifest.relative_to(root).as_posix()
        state["manifestSha256"] = digest_file(manifest)
        state["status"] = "review-required"
        state["processingComplete"] = True
    except Exception as exc:
        state["status"] = "cancelled" if isinstance(exc, InterruptedError) else "failed"
        state["error"] = str(exc)
        state["history"].append({"event":state["status"], "stage":state.get("stage"),
            "error":str(exc), "at":datetime.now(timezone.utc).isoformat()})
        state["processingComplete"] = False
        if state.get("stage"):
            state["stages"][state["stage"]]["status"] = state["status"]
        _atomic_json(state_path, state)
        raise
    _atomic_json(state_path, state)
    return state


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("source", type=Path)
    result.add_argument("--output-dir", type=Path, required=True)
    result.add_argument("--models", choices=("none", "standard", "light"), default="standard")
    result.add_argument("--runtime-config", type=Path, default=SKILL / ".local/item-model-runtime.json")
    result.add_argument("--taxonomy", type=Path, default=SKILL / "references/taxonomies/game-assets-v1.json")
    result.add_argument("--grid-quantum", type=int, default=32)
    result.add_argument("--padding", type=int, default=16)
    result.add_argument("--max-width", type=int, default=0)
    result.add_argument("--provenance", choices=("imported", "fixture", "imagegen", "grok-imagine-image", "mixed"), default="imported")
    return result


def main():
    try:
        args = parser().parse_args()
        root = args.output_dir.resolve()
        if args.source.resolve().is_relative_to(root):
            raise ValueError("output cannot contain the source")
        root.mkdir(parents=True, exist_ok=True)
        with acquire_run_lock(root, "item-atlas-workflow"):
            state = run_workflow(args)
        print(json.dumps({"status":state["status"], "manifest":state["manifest"]}))
        return 0
    except Exception as exc:
        print(json.dumps({"status":"failed", "error":str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
