"""Recoverable directory publication with immutable predecessor snapshots."""
from __future__ import annotations

import json
from pathlib import Path
import uuid

from .locks import acquire_run_lock
from runio import atomic_write_text


def publish_directory(staging: Path, output: Path, *, replace: bool = False) -> None:
    """Publish a staged run. Never delete a previously published revision.

    The small journal makes an interrupted two-rename transaction recoverable on
    Windows as well as POSIX. A predecessor stays in the sibling revision store.
    Readers use the workflow's atomic active-manifest pointer after publication.
    """
    if staging.is_symlink() or output.is_symlink():
        raise ValueError("publication cannot use linked directories")
    staging, output = staging.resolve(), output.resolve()
    if staging.parent != output.parent or not staging.is_dir() or staging == output:
        raise ValueError("publication requires a distinct staging sibling")
    store = output.parent / f".{output.name}.revisions"
    if store.is_symlink() or (store.exists() and store.resolve() != store):
        raise ValueError("revision store cannot be a linked path")
    store.mkdir(exist_ok=True)
    with acquire_run_lock(store, "publish-directory"):
        journal = store / "publication.json"
        if journal.exists():
            pending = json.loads(journal.read_text(encoding="utf-8"))
            revision = pending["previous"]
            if not isinstance(revision, str) or len(revision) != 32 or any(c not in "0123456789abcdef" for c in revision):
                raise ValueError("invalid publication journal")
            previous = store / revision
            if not output.exists() and previous.is_dir():
                previous.replace(output)
            journal.unlink()
        if output.exists() and (not output.is_dir() or output.is_symlink()):
            raise ValueError("publication target must be an ordinary directory")
        previous = None
        if output.exists():
            if any(output.iterdir()) and not replace:
                raise ValueError("output directory changed during publication")
            previous = store / uuid.uuid4().hex
            atomic_write_text(journal, json.dumps({"previous": previous.name}))
            output.replace(previous)
        try:
            staging.replace(output)
        except BaseException:
            if previous is not None and previous.exists() and not output.exists():
                previous.replace(output)
            raise
        finally:
            if output.exists():
                journal.unlink(missing_ok=True)
