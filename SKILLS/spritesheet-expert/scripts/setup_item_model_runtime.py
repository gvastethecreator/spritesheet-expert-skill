#!/usr/bin/env python3
"""Create the optional portable Python 3.12 local-model environment with uv."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess


class ModelRuntimeSetupError(RuntimeError):
    pass


SKILL_ROOT = Path(__file__).resolve().parents[1]
PROJECT = SKILL_ROOT / "model-runtime"


def _default_paths() -> tuple[Path, Path, Path, Path]:
    local = SKILL_ROOT / ".local"
    return (
        local / "item-model-runtime",
        local / "model-cache",
        local / "uv-cache",
        local / "item-model-runtime.json",
    )


def _python_path(runtime: Path) -> Path:
    windows = runtime / "Scripts" / "python.exe"
    return windows if os.name == "nt" else runtime / "bin" / "python"


def _parser() -> argparse.ArgumentParser:
    runtime, model_cache, uv_cache, config = _default_paths()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-dir", type=Path, default=runtime)
    parser.add_argument("--model-cache-dir", type=Path, default=model_cache)
    parser.add_argument("--uv-cache-dir", type=Path, default=uv_cache)
    parser.add_argument("--config", type=Path, default=config)
    parser.add_argument("--python", default="3.12")
    parser.add_argument("--profile", choices=("cpu", "nvidia"), default="cpu")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        uv = shutil.which("uv")
        if not uv:
            raise ModelRuntimeSetupError(
                "uv is required. Install uv, then rerun this command; no environment was changed."
            )
        runtime = args.runtime_dir.expanduser().resolve()
        model_cache = args.model_cache_dir.expanduser().resolve()
        uv_cache = args.uv_cache_dir.expanduser().resolve()
        config = args.config.expanduser().resolve()
        command = [
            uv,
            "sync",
            "--project",
            str(PROJECT),
            "--python",
            str(args.python),
            "--no-dev",
            "--locked",
            "--extra",
            args.profile,
        ]
        payload = {
            "schemaVersion": "item-model-runtime-v1",
            "project": str(PROJECT),
            "runtimeDir": str(runtime),
            "python": str(_python_path(runtime)),
            "modelCacheDir": str(model_cache),
            "uvCacheDir": str(uv_cache),
            "command": command,
            "downloadsModelWeights": False,
            "profile": args.profile,
        }
        if args.dry_run:
            payload["status"] = "dry-run"
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0
        runtime.parent.mkdir(parents=True, exist_ok=True)
        model_cache.mkdir(parents=True, exist_ok=True)
        uv_cache.mkdir(parents=True, exist_ok=True)
        environment = os.environ.copy()
        environment.update(
            {
                "UV_PROJECT_ENVIRONMENT": str(runtime),
                "UV_CACHE_DIR": str(uv_cache),
                "HF_HOME": str(model_cache),
                "HF_HUB_CACHE": str(model_cache / "hub"),
            }
        )
        completed = subprocess.run(command, env=environment, text=True, check=False)
        if completed.returncode:
            raise ModelRuntimeSetupError(f"uv sync failed with exit code {completed.returncode}")
        python = _python_path(runtime)
        if not python.is_file():
            raise ModelRuntimeSetupError(f"runtime Python was not created: {python}")
        config.parent.mkdir(parents=True, exist_ok=True)
        temporary = config.with_suffix(config.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(config)
    except (ModelRuntimeSetupError, OSError) as exc:
        print(json.dumps({"status": "operational-error", "errors": [str(exc)]}, ensure_ascii=False))
        return 3
    payload["status"] = "pass"
    payload["config"] = str(config)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
