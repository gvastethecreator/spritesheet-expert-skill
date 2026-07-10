"""Fail-closed path handling for files owned by a sprite run."""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import unicodedata
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


class PathSafetyError(ValueError):
    """Raised when a requested path is not safely contained by its run."""


RUN_MARKER_FILENAME = ".sprite-gen-run.json"
RUN_MARKER_KIND = "sprite-run"
RUN_MARKER_VERSION = 1


_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}
_PATH_SEPARATOR_CONFUSABLES = frozenset("∕⁄／⧸＼﹨∖")


def _portable_relative_parts(candidate: str | Path) -> tuple[str, ...]:
    raw = str(candidate)
    if not raw or "\x00" in raw:
        raise PathSafetyError("path must be a non-empty relative path")
    if unicodedata.normalize("NFC", raw) != raw:
        raise PathSafetyError(f"path must use NFC Unicode normalization: {candidate}")
    if any(character in _PATH_SEPARATOR_CONFUSABLES for character in raw):
        raise PathSafetyError(f"Unicode path-separator confusable is not allowed: {candidate}")
    if any(unicodedata.category(character) in {"Cc", "Cf"} for character in raw):
        raise PathSafetyError(f"Unicode control or format characters are not allowed: {candidate}")
    if "/" in raw and "\\" in raw:
        raise PathSafetyError(f"mixed path separators are not allowed: {candidate}")
    if raw.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", raw):
        raise PathSafetyError(f"absolute, drive, and UNC paths are not allowed: {candidate}")
    if ":" in raw:
        raise PathSafetyError(f"drive and alternate-stream syntax is not allowed: {candidate}")

    parts = tuple(raw.replace("\\", "/").split("/"))
    for part in parts:
        if not part:
            raise PathSafetyError(f"empty path component is not allowed: {candidate}")
        if part == "..":
            raise PathSafetyError(f"path traversal is not allowed: {candidate}")
        windows_normalized = part.rstrip(" .")
        if windows_normalized != part:
            raise PathSafetyError(f"trailing dots or spaces are not allowed: {candidate}")
        device_name = windows_normalized.split(".", 1)[0].upper()
        if device_name in _WINDOWS_RESERVED_NAMES:
            raise PathSafetyError(f"reserved Windows path name is not allowed: {candidate}")
    return parts


def resolve_run_path(run_dir: Path, candidate: str | Path) -> Path:
    """Resolve a relative path and prove that it remains inside ``run_dir``."""

    run_root = Path(run_dir).expanduser().resolve()
    requested = Path(*_portable_relative_parts(candidate))

    resolved = (run_root / requested).resolve()
    try:
        resolved.relative_to(run_root)
    except ValueError as exc:
        raise PathSafetyError(f"path escapes run directory: {candidate}") from exc
    return resolved


def _resolve_run_entry_path(run_root: Path, candidate: str | Path) -> Path:
    """Resolve an owned entry while preserving a leaf link for safe unlinking."""

    requested = run_root.joinpath(*_portable_relative_parts(candidate))
    parent = requested.parent.resolve()
    try:
        parent.relative_to(run_root)
    except ValueError as exc:
        raise PathSafetyError(f"path escapes run directory: {candidate}") from exc
    is_junction = getattr(requested, "is_junction", lambda: False)()
    if requested.is_symlink() or is_junction:
        return requested
    resolved = requested.resolve()
    try:
        resolved.relative_to(run_root)
    except ValueError as exc:
        raise PathSafetyError(f"path escapes run directory: {candidate}") from exc
    return resolved


def create_run_marker(
    run_dir: Path, *, run_id: str | None = None, kind: str = RUN_MARKER_KIND
) -> Path:
    """Atomically mark a directory as owned by the sprite pipeline."""

    if run_id is not None and (not isinstance(run_id, str) or not run_id.strip()):
        raise PathSafetyError("run marker id must be a non-empty string")
    marker_run_id = run_id if run_id is not None else uuid.uuid4().hex
    run_root = Path(run_dir).expanduser().resolve()
    if run_root.exists() and not run_root.is_dir():
        raise PathSafetyError(f"run path is not a directory: {run_root}")
    marker_path = run_root / RUN_MARKER_FILENAME
    if marker_path.is_file():
        existing = _load_run_marker(marker_path)
        if run_id is not None and existing["run_id"] != run_id:
            raise PathSafetyError(f"run marker id does not match existing run: {marker_path}")
        return marker_path
    if run_root.is_dir() and any(run_root.iterdir()):
        raise PathSafetyError(f"refusing to mark a non-empty unowned directory: {run_root}")

    run_root.mkdir(parents=True, exist_ok=True)
    marker = {
        "version": RUN_MARKER_VERSION,
        "kind": kind,
        "run_id": marker_run_id,
    }

    fd, temp_name = tempfile.mkstemp(
        dir=str(run_root), prefix=f".{RUN_MARKER_FILENAME}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(marker, handle, sort_keys=True)
            handle.write("\n")
        os.replace(temp_name, marker_path)
    except BaseException:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
        raise
    return marker_path


def _load_run_marker(marker_path: Path) -> dict[str, Any]:
    is_junction = getattr(marker_path, "is_junction", lambda: False)()
    if marker_path.is_symlink() or is_junction:
        raise PathSafetyError(f"run marker is unsafe: {marker_path}")
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PathSafetyError(f"run marker is unreadable: {marker_path}") from exc
    if not isinstance(marker, dict):
        raise PathSafetyError(f"run marker must be an object: {marker_path}")
    if marker.get("version") != RUN_MARKER_VERSION:
        raise PathSafetyError(f"unsupported run marker version: {marker_path}")
    if marker.get("kind") != RUN_MARKER_KIND:
        raise PathSafetyError(f"unexpected run marker kind: {marker_path}")
    run_id = marker.get("run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        raise PathSafetyError(f"run marker id is missing: {marker_path}")
    return marker


def _reject_dangerous_clean_root(run_root: Path) -> None:
    cwd = Path.cwd().resolve()
    home = Path.home().resolve()
    if run_root == Path(run_root.anchor) or cwd.is_relative_to(run_root) or home.is_relative_to(run_root):
        raise PathSafetyError(f"refusing to clean dangerous directory: {run_root}")


def guarded_clean_run_dir(run_dir: Path) -> list[Path]:
    """Clean an owned run directory, refusing unmarked directories."""

    run_root = Path(run_dir).expanduser().resolve()
    _reject_dangerous_clean_root(run_root)
    marker_path = run_root / RUN_MARKER_FILENAME
    if not marker_path.is_file():
        raise PathSafetyError(f"run marker is missing: {marker_path}")
    _load_run_marker(marker_path)

    removed: list[Path] = []
    for child in sorted(run_root.iterdir(), key=lambda path: path.name.casefold()):
        if child == marker_path:
            continue
        removed.append(child)
        is_junction = getattr(child, "is_junction", lambda: False)()
        if child.is_symlink() or is_junction:
            child.unlink()
        elif child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    return removed


def remove_known_outputs(
    run_dir: Path,
    relative_paths: list[str | Path] | tuple[str | Path, ...],
    *,
    require_marker: bool = True,
) -> list[Path]:
    """Remove only explicitly named outputs from a run directory."""

    run_root = Path(run_dir).expanduser().resolve()
    _reject_dangerous_clean_root(run_root)
    if require_marker:
        marker_path = run_root / RUN_MARKER_FILENAME
        if not marker_path.is_file():
            raise PathSafetyError(f"run marker is missing: {marker_path}")
        _load_run_marker(marker_path)

    removed: list[Path] = []
    marker_path = run_root / RUN_MARKER_FILENAME
    validated_targets: list[Path] = []
    for relative_path in relative_paths:
        target = _resolve_run_entry_path(run_root, relative_path)
        if target == marker_path:
            raise PathSafetyError("the run marker cannot be removed as a known output")
        validated_targets.append(target)

    seen: set[Path] = set()
    for target in validated_targets:
        is_junction = getattr(target, "is_junction", lambda: False)()
        if target in seen or (
            not target.exists() and not target.is_symlink() and not is_junction
        ):
            continue
        seen.add(target)
        removed.append(target)
        if target.is_symlink() or is_junction:
            target.unlink()
        elif target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
    return removed


def _require_owned_run(run_root: Path, run_id: str) -> None:
    _reject_dangerous_clean_root(run_root)
    marker_path = run_root / RUN_MARKER_FILENAME
    if marker_path.is_symlink() or not marker_path.is_file():
        raise PathSafetyError(f"run marker is missing or unsafe: {marker_path}")
    marker = _load_run_marker(marker_path)
    if marker["run_id"] != run_id:
        raise PathSafetyError(f"run marker id does not match {run_id!r}: {marker_path}")


def _unused_sibling_path(run_root: Path, label: str) -> Path:
    for _attempt in range(100):
        candidate = run_root.with_name(f".{run_root.name}.{label}-{uuid.uuid4().hex}")
        if not candidate.exists() and not candidate.is_symlink():
            return candidate
    raise PathSafetyError(f"could not allocate a unique {label} path next to {run_root}")


def _remove_path(path: Path) -> None:
    """Remove one transaction-owned path without following directory links."""

    is_junction = getattr(path, "is_junction", lambda: False)()
    if path.is_symlink() or is_junction or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


@contextmanager
def replace_owned_run(run_dir: Path, run_id: str) -> Iterator[Path]:
    """Transactionally replace a marked run directory."""

    run_root = Path(run_dir).expanduser().resolve()
    _require_owned_run(run_root, run_id)
    backup = _unused_sibling_path(run_root, "backup")
    run_root.rename(backup)
    try:
        run_root.mkdir()
        create_run_marker(run_root, run_id=run_id)
        yield run_root
    except BaseException as error:
        quarantine: Path | None = None
        try:
            if run_root.exists() or run_root.is_symlink():
                quarantine = _unused_sibling_path(run_root, "rollback")
                run_root.rename(quarantine)
            backup.rename(run_root)
        except BaseException as rollback_error:
            error.add_note(f"Failed to restore original run: {rollback_error}")
            raise rollback_error from error

        if quarantine is not None:
            try:
                _remove_path(quarantine)
            except OSError as cleanup_error:
                error.add_note(
                    f"Restored original run but could not remove rollback path: {cleanup_error}"
                )
        raise
    else:
        shutil.rmtree(backup)
