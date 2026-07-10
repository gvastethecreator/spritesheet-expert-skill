from __future__ import annotations

import json
import os
import socket
import time
from pathlib import Path

import pytest

from spritecore.locks import LOCK_FILENAME, RunLockHeldError, acquire_run_lock


def test_run_lock_records_process_identity_and_releases_on_exit(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    with acquire_run_lock(run_dir, "extract") as lease:
        lock_path = run_dir / LOCK_FILENAME
        payload = json.loads(lock_path.read_text(encoding="utf-8"))

        assert lease.path == lock_path
        assert payload == {
            "version": 2,
            "token": lease.token,
            "owner": "extract",
            "host": socket.gethostname(),
            "pid": os.getpid(),
            "started": payload["started"],
        }

    assert not lock_path.exists()


def test_run_lock_never_releases_a_foreign_token(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    lease = acquire_run_lock(run_dir, "extract")
    foreign_payload = {
        "version": 2,
        "token": "successor-token",
        "owner": "compose",
        "host": socket.gethostname(),
        "pid": os.getpid(),
        "started": 1.0,
    }
    lease.path.write_text(json.dumps(foreign_payload), encoding="utf-8")

    assert lease.release() is False
    assert json.loads(lease.path.read_text(encoding="utf-8"))["token"] == "successor-token"


def test_run_lock_reclaims_a_dead_same_host_holder(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    lock_path = run_dir / LOCK_FILENAME
    lock_path.write_text(
        json.dumps(
            {
                "version": 2,
                "token": "dead-token",
                "owner": "extract",
                "host": socket.gethostname(),
                "pid": 2_147_483_647,
                "started": 1.0,
            }
        ),
        encoding="utf-8",
    )

    lease = acquire_run_lock(run_dir, "compose")
    try:
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
        assert payload["token"] == lease.token
        assert payload["owner"] == "compose"
    finally:
        lease.release()


def test_legacy_runio_wrapper_returns_the_lock_path_and_writes_v2(tmp_path: Path) -> None:
    from runio import acquire_run_dir_lock

    run_dir = tmp_path / "run"
    run_dir.mkdir()

    lock_path = acquire_run_dir_lock(run_dir, "legacy-compose")
    try:
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
        assert lock_path == run_dir / LOCK_FILENAME
        assert payload["version"] == 2
        assert payload["token"]
        assert payload["host"] == socket.gethostname()
        assert payload["pid"] == os.getpid()
    finally:
        lock_path.unlink(missing_ok=True)


def test_run_lock_does_not_probe_or_reclaim_a_fresh_remote_holder(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    lock_path = run_dir / LOCK_FILENAME
    lock_path.write_text(
        json.dumps(
            {
                "version": 2,
                "token": "remote-token",
                "owner": "remote-extract",
                "host": "remote-build-host",
                "pid": 2_147_483_647,
                "started": time.time(),
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RunLockHeldError, match="remote-build-host"):
        acquire_run_lock(run_dir, "local-compose")

    assert json.loads(lock_path.read_text(encoding="utf-8"))["token"] == "remote-token"
