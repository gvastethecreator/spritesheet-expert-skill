"""run.json: the single source of truth for one run folder."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from . import SCHEMA

RUN_FILE = "run.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load(run_dir: Path) -> dict:
    path = run_dir / RUN_FILE
    if not path.is_file():
        raise SystemExit(f"{path} not found. Run `sprite.py plan` first.")
    run = json.loads(path.read_text(encoding="utf-8"))
    if run.get("schema") != SCHEMA:
        raise SystemExit(f"{path} is not a {SCHEMA} run.")
    return run


def save(run_dir: Path, run: dict) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / RUN_FILE).write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")


def state(run: dict, name: str) -> dict:
    for entry in run["states"]:
        if entry["name"] == name:
            return entry
    raise SystemExit(f"unknown state {name!r}; run.json has {[s['name'] for s in run['states']]}")
