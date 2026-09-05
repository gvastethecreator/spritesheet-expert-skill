#!/usr/bin/env python3
"""Inspect the isolated local-model runtime, CUDA device, and cache paths."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess


SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = SKILL_ROOT / ".local" / "item-model-runtime.json"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    return parser


def main() -> int:
    args = _parser().parse_args()
    config_path = args.config.expanduser().resolve()
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        python = Path(config["python"]).resolve()
        if not python.is_file():
            raise RuntimeError(f"runtime Python does not exist: {python}")
        probe = (
            "import json, torch, transformers, accelerate; "
            "print(json.dumps({'torch': torch.__version__, 'transformers': transformers.__version__, "
            "'accelerate': accelerate.__version__, 'cudaAvailable': torch.cuda.is_available(), "
            "'cudaVersion': torch.version.cuda, 'deviceCount': torch.cuda.device_count(), "
            "'devices': [torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())]}))"
        )
        environment = os.environ.copy()
        environment.update(
            {
                "HF_HOME": str(Path(config["modelCacheDir"]).resolve()),
                "HF_HUB_CACHE": str(Path(config["modelCacheDir"]).resolve() / "hub"),
            }
        )
        completed = subprocess.run(
            [str(python), "-c", probe],
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise RuntimeError(f"runtime probe failed: {detail}")
        report = json.loads(completed.stdout)
    except (OSError, KeyError, json.JSONDecodeError, RuntimeError) as exc:
        print(
            json.dumps(
                {
                    "status": "operational-error",
                    "errors": [str(exc)],
                    "setup": str(SKILL_ROOT / "scripts" / "setup_item_model_runtime.py"),
                },
                ensure_ascii=False,
            )
        )
        return 3
    print(
        json.dumps(
            {
                "status": "pass",
                "config": str(config_path),
                "python": str(python),
                "modelCacheDir": str(Path(config["modelCacheDir"]).resolve()),
                **report,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
