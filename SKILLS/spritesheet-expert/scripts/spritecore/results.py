"""Canonical outcomes shared by spritesheet QA checks."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
import re
from types import MappingProxyType
from typing import Any, Mapping


class CheckStatus(str, Enum):
    """Stable status vocabulary for one QA check."""

    PASS = "pass"
    FAIL = "fail"
    BLOCKED = "blocked"
    OPERATIONAL_ERROR = "operational-error"
    SKIPPED = "skipped"


_EXIT_CODE_BY_STATUS = {
    CheckStatus.PASS: 0,
    CheckStatus.FAIL: 1,
    CheckStatus.BLOCKED: 2,
    CheckStatus.OPERATIONAL_ERROR: 3,
    CheckStatus.SKIPPED: 0,
}
_CHECK_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("evidence must contain only JSON-compatible string keys")
        return MappingProxyType(
            {key: _freeze_json(value[key]) for key in sorted(value)}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise TypeError(f"evidence contains a non JSON-compatible value: {value!r}")


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _freeze_strings(name: str, values: Any) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError(f"{name} must be a sequence of strings, not a bare string")
    try:
        frozen = tuple(values)
    except TypeError as exc:
        raise TypeError(f"{name} must be a sequence of strings") from exc
    if any(not isinstance(value, str) or not value for value in frozen):
        raise TypeError(f"{name} must contain only non-empty strings")
    return frozen


@dataclass(frozen=True, slots=True)
class CheckResult:
    """Immutable, JSON-ready result returned by every core check."""

    id: str
    applicable: bool
    checked_items: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    evidence: Mapping[str, Any] = field(default_factory=dict)
    input_fingerprint: str | None = None
    complete: bool = True
    status: CheckStatus | str = CheckStatus.PASS

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or _CHECK_ID_RE.fullmatch(self.id) is None:
            raise ValueError("id must be a lowercase kebab-case check id")
        if type(self.applicable) is not bool:
            raise TypeError("applicable must be a boolean")
        if type(self.complete) is not bool:
            raise TypeError("complete must be a boolean")
        if self.input_fingerprint is not None and (
            not isinstance(self.input_fingerprint, str) or not self.input_fingerprint
        ):
            raise TypeError("input_fingerprint must be a non-empty string or None")
        if not isinstance(self.evidence, Mapping):
            raise TypeError("evidence must be a mapping")
        object.__setattr__(
            self, "checked_items", _freeze_strings("checked_items", self.checked_items)
        )
        object.__setattr__(self, "errors", _freeze_strings("errors", self.errors))
        object.__setattr__(self, "warnings", _freeze_strings("warnings", self.warnings))
        object.__setattr__(self, "evidence", _freeze_json(self.evidence))
        object.__setattr__(self, "status", CheckStatus(self.status))
        expected_facts = {
            CheckStatus.PASS: (True, True, False),
            CheckStatus.FAIL: (True, True, True),
            CheckStatus.BLOCKED: (True, False, True),
            CheckStatus.OPERATIONAL_ERROR: (True, False, True),
            CheckStatus.SKIPPED: (False, True, False),
        }
        actual_facts = (self.applicable, self.complete, bool(self.errors))
        if actual_facts != expected_facts[self.status]:
            raise ValueError(
                f"status {self.status.value!r} contradicts applicable, complete, or errors"
            )

    @property
    def exit_code(self) -> int:
        """Return the stable process exit code for this result."""

        return _EXIT_CODE_BY_STATUS[self.status]

    def to_dict(self) -> dict[str, Any]:
        """Return a detached JSON-compatible representation."""

        return {
            "id": self.id,
            "applicable": self.applicable,
            "checked_items": list(self.checked_items),
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "evidence": _thaw_json(self.evidence),
            "input_fingerprint": self.input_fingerprint,
            "complete": self.complete,
            "status": self.status.value,
        }
