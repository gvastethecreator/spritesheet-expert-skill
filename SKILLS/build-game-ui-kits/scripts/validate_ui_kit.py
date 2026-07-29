#!/usr/bin/env python3
"""Validate a raster UI kit and render deterministic state and stretch proofs."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
import json
import os
from pathlib import Path
import tempfile

class _CommandLineError(ValueError):
    def __init__(self, message: str) -> None:
        self.issues = (message,)
        super().__init__(message)


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise _CommandLineError(f"command line: {message}")


def _failure(message: str) -> dict[str, object]:
    return {
        "version": 1,
        "kind": "ui-kit-validation",
        "ok": False,
        "kit_id": None,
        "checked_components": [],
        "errors": [message],
        "warnings": [],
    }


def _atomic_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _print(payload: Mapping[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _write_report(path: Path | None, payload: dict[str, object], code: int) -> int:
    if path is not None:
        try:
            _atomic_json(path, payload)
        except OSError as exc:
            payload = _failure(f"operational failure: cannot write report: {exc}")
            code = 3
    _print(payload)
    return code


def _parse(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = _Parser(description=__doc__)
    parser.add_argument("--kit", type=Path, required=True)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--report", default="qa/ui-kit-report.json")
    parser.add_argument("--state-board", default="qa/ui-state-board.png")
    parser.add_argument("--stretch-board", default="qa/ui-nine-slice.png")
    return parser.parse_args(argv)


def _source_paths(
    document: Mapping[str, object],
    root: Path,
    resolve_path: object,
    contract_error: type[Exception],
) -> set[Path]:
    paths: set[Path] = set()
    components = document.get("components")
    if not isinstance(components, list):
        return paths
    for component in components:
        if not isinstance(component, Mapping):
            continue
        states = component.get("states")
        if not isinstance(states, Mapping):
            continue
        for variants in states.values():
            if not isinstance(variants, list):
                continue
            for variant in variants:
                if not isinstance(variant, Mapping):
                    continue
                value = variant.get("path")
                if not isinstance(value, str):
                    continue
                try:
                    paths.add(resolve_path(root, value))  # type: ignore[operator]
                except contract_error:
                    continue
    return paths


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parse(argv)
    except _CommandLineError as exc:
        return _write_report(None, _failure("; ".join(exc.issues)), 1)

    try:
        from ui_kit import UiKitError, resolve_kit_path, validate_ui_kit
    except ModuleNotFoundError as exc:
        dependency = exc.name or "required package"
        return _write_report(
            None,
            _failure(
                f"missing runtime dependency '{dependency}'; from the repository "
                "root run: python -m pip install -e ."
            ),
            3,
        )

    kit_path = args.kit.expanduser().resolve()
    root = args.root.expanduser().resolve() if args.root else kit_path.parent
    report_path: Path | None = None
    try:
        report_path = resolve_kit_path(root, args.report)
        state_board_path = resolve_kit_path(root, args.state_board)
        stretch_board_path = resolve_kit_path(root, args.stretch_board)
        outputs = (report_path, state_board_path, stretch_board_path)
        if len(set(outputs)) != len(outputs):
            raise UiKitError(["report and proof output paths must be distinct"])
        if not kit_path.is_relative_to(root):
            raise UiKitError(["kit document must be inside kit root"])
        if kit_path in outputs:
            raise UiKitError(["output paths must not overwrite the kit document"])
    except UiKitError as exc:
        return _write_report(report_path, _failure("; ".join(exc.issues)), 1)

    try:
        raw_document = kit_path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        return _write_report(report_path, _failure(f"operational failure: {exc}"), 3)
    except UnicodeError as exc:
        return _write_report(report_path, _failure(f"invalid kit document: {exc}"), 1)
    try:
        document = json.loads(raw_document)
    except (json.JSONDecodeError, UnicodeError) as exc:
        return _write_report(report_path, _failure(f"invalid kit document: {exc}"), 1)
    if not isinstance(document, Mapping):
        return _write_report(
            report_path,
            _failure("kit document root must be an object"),
            1,
        )
    if report_path in _source_paths(document, root, resolve_kit_path, UiKitError):
        return _write_report(
            None,
            _failure("report output path must not overwrite a component input"),
            1,
        )

    try:
        report = validate_ui_kit(
            document,
            root=root,
            state_board_path=state_board_path,
            stretch_board_path=stretch_board_path,
        )
    except UiKitError as exc:
        return _write_report(report_path, _failure("; ".join(exc.issues)), 1)
    except (OSError, RuntimeError) as exc:
        return _write_report(report_path, _failure(f"operational failure: {exc}"), 3)
    return _write_report(report_path, report, 0)


if __name__ == "__main__":
    raise SystemExit(main())
