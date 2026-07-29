#!/usr/bin/env python3
"""Validate, seal, and resolve a portable asset-presentation contract."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
import json
import os
from pathlib import Path
import tempfile

REQUIREMENTS = Path(__file__).resolve().parents[1] / "requirements-runtime.txt"


class _CommandLineError(ValueError):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise _CommandLineError(f"command line: {message}")


def _parse(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = _Parser(description=__doc__)
    parser.add_argument("--presentation", type=Path, required=True)
    parser.add_argument("--root", type=Path)
    parser.add_argument(
        "--prepared",
        default="presentation/prepared-presentation.json",
        help="portable prepared-contract output below root",
    )
    parser.add_argument(
        "--resolved",
        default="presentation/resolved-presentation.json",
        help="portable resolved-import output below root",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="validate and write the prepared contract without copying pinned assets",
    )
    return parser.parse_args(argv)


def _portable_output(root: Path, value: str) -> Path:
    relative = Path(value)
    if relative.is_absolute() or "\\" in value or any(
        part in {"", ".", ".."} for part in value.split("/")
    ):
        raise ValueError(f"output path must be portable and relative: {value}")
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"output path escapes presentation root: {value}") from exc
    return candidate


def _source_paths(document: Mapping[str, object], root: Path) -> set[Path]:
    sources: set[Path] = set()
    inventory = document.get("inventory")
    brand_kit = document.get("brand_kit")
    groups: list[object] = []
    if isinstance(inventory, Mapping):
        groups.append(inventory.get("assets"))
    if isinstance(brand_kit, Mapping):
        groups.append(brand_kit.get("fonts"))
    for records in groups:
        if not isinstance(records, list):
            continue
        for record in records:
            if not isinstance(record, Mapping):
                continue
            source = record.get("source")
            if not isinstance(source, Mapping):
                continue
            for pin in source.values():
                if not isinstance(pin, Mapping) or not isinstance(pin.get("path"), str):
                    continue
                try:
                    sources.add(_portable_output(root, pin["path"]))
                except ValueError:
                    continue
    return sources


def _atomic_json(path: Path, document: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(document, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _emit(ok: bool, status: str, message: str, **values: object) -> int:
    payload = {
        "version": 1,
        "kind": "asset-presentation-preparation",
        "ok": ok,
        "status": status,
        "message": message,
        **values,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if ok else (3 if status == "operational-error" else 1)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parse(argv)
    except _CommandLineError as exc:
        return _emit(False, "contract-failed", str(exc))

    presentation_path = args.presentation.expanduser().resolve()
    root = args.root.expanduser().resolve() if args.root else presentation_path.parent
    try:
        presentation_path.relative_to(root)
        prepared_path = _portable_output(root, args.prepared)
        resolved_path = _portable_output(root, args.resolved)
        if prepared_path == resolved_path:
            raise ValueError("prepared and resolved outputs must be distinct")
        if presentation_path in {prepared_path, resolved_path}:
            raise ValueError("outputs must not overwrite the presentation document")
    except ValueError as exc:
        return _emit(False, "contract-failed", str(exc))

    try:
        raw = presentation_path.read_text(encoding="utf-8-sig")
        document = json.loads(raw)
    except OSError as exc:
        return _emit(False, "operational-error", f"cannot read presentation: {exc}")
    except (UnicodeError, json.JSONDecodeError) as exc:
        return _emit(False, "contract-failed", f"invalid presentation JSON: {exc}")
    if not isinstance(document, Mapping):
        return _emit(False, "contract-failed", "presentation root must be an object")
    if {prepared_path, resolved_path} & _source_paths(document, root):
        return _emit(False, "contract-failed", "outputs must not overwrite pinned inputs")

    try:
        from presentation_pipeline import (
            PresentationContractError,
            prepare_presentation,
            resolve_presentation,
        )
    except ModuleNotFoundError as exc:
        dependency = exc.name or "required package"
        return _emit(
            False,
            "operational-error",
            f"missing runtime dependency '{dependency}'; install from this copied "
            f'skill with: python -m pip install -r "{REQUIREMENTS}"',
        )

    try:
        prepared = prepare_presentation(document)
        resolved = None if args.validate_only else resolve_presentation(prepared, root)
        _atomic_json(prepared_path, prepared)
        if resolved is not None:
            _atomic_json(resolved_path, resolved)
    except PresentationContractError as exc:
        issues = "; ".join(
            f"{issue.path}: {issue.message}" for issue in exc.issues
        )
        return _emit(False, "contract-failed", issues)
    except (FileNotFoundError, ValueError) as exc:
        return _emit(False, "contract-failed", str(exc))
    except OSError as exc:
        return _emit(False, "operational-error", str(exc))

    return _emit(
        True,
        "prepared",
        "presentation contract prepared",
        presentation_id=document.get("presentation_id"),
        presentation_sha256=prepared["presentation_sha256"],
        prepared_path=prepared_path.relative_to(root).as_posix(),
        resolved_path=(
            resolved_path.relative_to(root).as_posix() if resolved is not None else None
        ),
        import_count=len(resolved["imports"]) if resolved is not None else 0,
    )


if __name__ == "__main__":
    raise SystemExit(main())
