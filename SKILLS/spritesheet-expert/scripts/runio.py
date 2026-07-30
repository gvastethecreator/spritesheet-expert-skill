#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Safe run-dir IO shared by the pipeline scripts.

Two concerns live together here because they answer the same question — "what
happens when two sprite-gen processes touch the same run dir at once?" (for
example Claude Code and the Codex app driving the skill in parallel):

- `acquire_run_dir_lock()` — single-writer lock per run dir. SKILL.md forbids
  two workers writing one character folder; this makes the rule enforced
  instead of documentation-only. Writers (extract / compose / export / unpack,
  and the webview's compose/export subprocesses through them) fail loudly with
  the holder's pid instead of silently interleaving output files.
- `atomic_write_text()` / `atomic_save_image()` — temp file in the target dir
  + `os.replace`, so a concurrent reader never observes a half-written
  atlas/manifest/frame.

`curation.json` is intentionally NOT under the lock: the webview already writes
it with the same atomic replace (see `serve_curation.py`), and the compose
scripts read one consistent snapshot of it. Two curator windows on one run dir
remain last-write-wins by design; the lock guards pipeline outputs, not human
edit sessions.
"""

from __future__ import annotations

import atexit
import os
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image

from spritecore.locks import (
    LOCK_FILENAME,
    STALE_LOCK_SECONDS,
    RunLock,
    RunLockError,
    acquire_run_lock,
)


_LEGACY_LOCKS: list[RunLock] = []


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except ProcessLookupError:
        return False
    except OSError:
        return False
    return True


def acquire_run_dir_lock(run_dir: Path, owner: str) -> Path:
    """Take the single-writer lock for `run_dir`, released automatically at exit.

    Create-exclusive lock file (`.sprite-gen.lock`) holding owner + pid. When
    another live process holds it, exit loudly instead of interleaving writes.
    A lock whose pid is dead — or unreadable and older than STALE_LOCK_SECONDS —
    is reclaimed, so a killed run never wedges the run dir.

    Release runs via atexit (normal return, SystemExit, KeyboardInterrupt).
    A SIGKILL'd holder is covered by the dead-pid reclaim above.
    """
    try:
        lease = acquire_run_lock(run_dir, owner)
    except RunLockError as exc:
        raise SystemExit(str(exc)) from exc
    _LEGACY_LOCKS.append(lease)
    atexit.register(lease.release)
    return lease.path


def _atomic_replace(target: Path, write_payload) -> None:
    fd, tmp_name = tempfile.mkstemp(dir=str(target.parent), prefix=f".{target.name}.", suffix=".tmp")
    try:
        write_payload(fd, tmp_name)
        os.replace(tmp_name, target)
    except BaseException:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


def atomic_write_text(target: Path, text: str) -> None:
    """Write text via temp file + os.replace so readers never see a torn file."""

    def payload(fd: int, _tmp_name: str) -> None:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)

    _atomic_replace(target, payload)


def atomic_write_bytes(target: Path, content: bytes) -> None:
    """Write exact bytes via temp file + os.replace without newline translation."""

    def payload(fd: int, _tmp_name: str) -> None:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)

    _atomic_replace(target, payload)


def atomic_save_image(image: Image.Image, target: Path, **save_kwargs: Any) -> None:
    """Save a PIL image via temp file + os.replace (format from target suffix)."""
    fmt = (target.suffix.lstrip(".") or "png").upper()
    fmt = {"JPG": "JPEG"}.get(fmt, fmt)

    def payload(fd: int, tmp_name: str) -> None:
        os.close(fd)
        image.save(tmp_name, format=fmt, **save_kwargs)

    _atomic_replace(target, payload)
