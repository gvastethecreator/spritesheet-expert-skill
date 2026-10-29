"""Token-bearing single-writer locks for sprite run directories."""

from __future__ import annotations

import json
import os
import socket
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType


LOCK_FILENAME = ".sprite-gen.lock"
LOCK_VERSION = 2
STALE_LOCK_SECONDS = 15 * 60


if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    _STILL_ACTIVE = 259
    _ERROR_ACCESS_DENIED = 5
    _KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _KERNEL32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _KERNEL32.OpenProcess.restype = wintypes.HANDLE
    _KERNEL32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    _KERNEL32.GetExitCodeProcess.restype = wintypes.BOOL
    _KERNEL32.CloseHandle.argtypes = [wintypes.HANDLE]
    _KERNEL32.CloseHandle.restype = wintypes.BOOL


class RunLockError(RuntimeError):
    """Base error for run lock operations."""


class RunLockHeldError(RunLockError):
    """Raised when another writer owns the run lock."""


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        handle = _KERNEL32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return ctypes.get_last_error() == _ERROR_ACCESS_DENIED
        try:
            exit_code = wintypes.DWORD()
            if not _KERNEL32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return True
            return exit_code.value == _STILL_ACTIVE
        finally:
            _KERNEL32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except ProcessLookupError:
        return False
    except OSError:
        return False
    return True


def _read_lock_snapshot(path: Path) -> tuple[bytes, dict[str, object]] | None:
    try:
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    return raw, payload


def _remove_unchanged_lock(path: Path, expected: bytes) -> bool:
    try:
        if path.read_bytes() != expected:
            return False
        path.unlink()
    except OSError:
        return False
    return True


def _lock_age_seconds(path: Path) -> float:
    try:
        return max(0.0, time.time() - path.stat().st_mtime)
    except OSError:
        return 0.0


def _try_reclaim_stale_lock(path: Path, local_host: str, stale_after_seconds: float) -> bool:
    snapshot = _read_lock_snapshot(path)
    if snapshot is None:
        if _lock_age_seconds(path) <= stale_after_seconds:
            return False
        try:
            path.unlink()
        except OSError:
            return False
        return True

    raw, payload = snapshot
    holder_host = payload.get("host")
    holder_pid = payload.get("pid")
    same_host = holder_host in (None, local_host)
    if same_host and isinstance(holder_pid, int):
        if _pid_alive(holder_pid):
            return False
        return _remove_unchanged_lock(path, raw)
    if _lock_age_seconds(path) > stale_after_seconds:
        return _remove_unchanged_lock(path, raw)
    return False


def _held_message(path: Path) -> str:
    snapshot = _read_lock_snapshot(path)
    if snapshot is None:
        return f"run directory has an unreadable lock: {path}"
    _raw, payload = snapshot
    return (
        f"run directory is locked by {payload.get('owner', 'unknown')} "
        f"on {payload.get('host', 'unknown')} (pid {payload.get('pid', 'unknown')}): {path.parent}"
    )


@dataclass(slots=True)
class RunLock:
    """An acquired run lock whose token identifies its ownership."""

    path: Path
    token: str
    owner: str
    host: str
    pid: int
    _released: bool = field(default=False, init=False, repr=False)

    def release(self) -> bool:
        if self._released:
            return False
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, ValueError):
            self._released = True
            return False
        if not isinstance(payload, dict) or payload.get("token") != self.token:
            self._released = True
            return False
        try:
            self.path.unlink()
        except FileNotFoundError:
            self._released = True
            return False
        self._released = True
        return True

    def __enter__(self) -> "RunLock":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.release()


def acquire_run_lock(
    run_dir: Path, owner: str, *, stale_after_seconds: float = STALE_LOCK_SECONDS
) -> RunLock:
    """Acquire the exclusive writer lock for ``run_dir``."""

    run_root = Path(run_dir).expanduser().resolve()
    if not run_root.is_dir():
        raise RunLockError(f"run directory does not exist: {run_root}")
    if not owner.strip():
        raise RunLockError("lock owner must be a non-empty string")

    path = run_root / LOCK_FILENAME
    token = uuid.uuid4().hex
    host = socket.gethostname()
    pid = os.getpid()
    payload = {
        "version": LOCK_VERSION,
        "token": token,
        "owner": owner,
        "host": host,
        "pid": pid,
        "started": time.time(),
    }
    while True:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError as exc:
            if _try_reclaim_stale_lock(path, host, stale_after_seconds):
                continue
            raise RunLockHeldError(_held_message(path)) from exc
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True)
            handle.write("\n")
    except BaseException:
        try:
            path.unlink()
        except OSError:
            pass
        raise
    return RunLock(path=path, token=token, owner=owner, host=host, pid=pid)
