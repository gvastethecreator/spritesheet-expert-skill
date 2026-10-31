"""Shared safety primitives for spritesheet pipeline scripts."""

from .locks import LOCK_FILENAME, RunLock, RunLockError, RunLockHeldError, acquire_run_lock
from .paths import (
    RUN_MARKER_FILENAME,
    PathSafetyError,
    create_run_marker,
    guarded_clean_run_dir,
    remove_known_outputs,
    replace_owned_run,
    resolve_run_path,
)
from .policy import GateDecision, GatePolicy, GatePolicyError, derive_gate_policy
from .results import CheckResult, CheckStatus

__all__ = [
    "CheckResult",
    "CheckStatus",
    "GateDecision",
    "GatePolicy",
    "GatePolicyError",
    "LOCK_FILENAME",
    "RUN_MARKER_FILENAME",
    "PathSafetyError",
    "RunLock",
    "RunLockError",
    "RunLockHeldError",
    "acquire_run_lock",
    "create_run_marker",
    "derive_gate_policy",
    "guarded_clean_run_dir",
    "remove_known_outputs",
    "replace_owned_run",
    "resolve_run_path",
]
