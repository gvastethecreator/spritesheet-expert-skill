"""Self-contained fail-closed paths for portable asset packs."""

from __future__ import annotations

from pathlib import Path
import re
import unicodedata


class AssetPackPathError(ValueError):
    """A declared pack path is not portable or safely contained."""


_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}
_PATH_SEPARATOR_CONFUSABLES = frozenset("∕⁄／⧸＼﹨∖")


def portable_relative_parts(candidate: str | Path) -> tuple[str, ...]:
    """Return safe POSIX path parts or fail before filesystem access."""

    raw = str(candidate)
    if not raw or "\x00" in raw:
        raise AssetPackPathError("path must be a non-empty relative path")
    if unicodedata.normalize("NFC", raw) != raw:
        raise AssetPackPathError("path must use NFC Unicode normalization")
    if any(character in _PATH_SEPARATOR_CONFUSABLES for character in raw):
        raise AssetPackPathError("Unicode path-separator confusable is not allowed")
    if any(unicodedata.category(character) in {"Cc", "Cf"} for character in raw):
        raise AssetPackPathError("Unicode control or format characters are not allowed")
    if "\\" in raw:
        raise AssetPackPathError("portable paths must use forward slashes")
    if raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
        raise AssetPackPathError("absolute, drive, and UNC paths are not allowed")
    if ":" in raw:
        raise AssetPackPathError("drive and alternate-stream syntax is not allowed")

    parts = tuple(raw.split("/"))
    for part in parts:
        if part in {"", ".", ".."}:
            raise AssetPackPathError("empty and traversal path components are not allowed")
        if part.rstrip(" .") != part:
            raise AssetPackPathError("trailing dots or spaces are not allowed")
        if part.split(".", 1)[0].upper() in _WINDOWS_RESERVED_NAMES:
            raise AssetPackPathError("reserved Windows path name is not allowed")
    return parts


def resolve_pack_path(pack_root: Path, candidate: str | Path) -> Path:
    """Resolve one portable path and prove symlinks remain below the pack root."""

    root = Path(pack_root).expanduser().resolve()
    target = root.joinpath(*portable_relative_parts(candidate)).resolve()
    if not target.is_relative_to(root):
        raise AssetPackPathError(f"path escapes pack root: {candidate}")
    return target


__all__ = ["AssetPackPathError", "portable_relative_parts", "resolve_pack_path"]
