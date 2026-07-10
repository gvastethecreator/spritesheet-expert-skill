"""Public value objects for versioned spritesheet contracts."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any, Mapping


STATE_SLUG_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
STATE_SLUG_MAX_LENGTH = 64
_STATE_SLUG_RE = re.compile(STATE_SLUG_PATTERN)


def is_state_slug(value: object) -> bool:
    """Return whether ``value`` is a filesystem-safe 1-64 char kebab slug."""

    return (
        isinstance(value, str)
        and 1 <= len(value) <= STATE_SLUG_MAX_LENGTH
        and _STATE_SLUG_RE.fullmatch(value) is not None
    )


class ContractKind(str, Enum):
    """Contract families supported by the spritecore boundary."""

    SPRITE_REQUEST = "sprite-request"
    PROVENANCE = "provenance"
    MANIFEST = "manifest"
    REPORT = "report"


class _FrozenList(tuple):
    """Tuple-backed JSON array that retains intuitive equality with lists."""

    def __eq__(self, other: object) -> bool:
        if isinstance(other, list):
            return list(self) == other
        return super().__eq__(other)

    __hash__ = tuple.__hash__


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return _FrozenList(_freeze_json(item) for item in value)
    return deepcopy(value)


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return deepcopy(value)


@dataclass(frozen=True, slots=True)
class ContractDocument:
    """A validated contract plus its canonical kind and version."""

    kind: ContractKind
    version: int
    data: Mapping[str, Any]
    source: Path | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "data", _freeze_json(self.data))

    def to_dict(self) -> dict[str, Any]:
        """Return a detached JSON-compatible copy."""

        return _thaw_json(self.data)

    def __getitem__(self, key: str) -> Any:
        return self.data[key]
