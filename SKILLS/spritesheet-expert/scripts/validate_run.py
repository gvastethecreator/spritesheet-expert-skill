#!/usr/bin/env python3
"""Run every applicable QA gate and write one final machine decision."""

from __future__ import annotations

import argparse
import atexit
import json
from pathlib import Path
import sys

from jsonschema import Draft202012Validator

from runio import atomic_write_text
from spritecore.locks import RunLockError, acquire_run_lock
from spritecore.orchestrator import STAGES, validate_run
from spritecore.paths import PathSafetyError, resolve_run_path


DEFAULT_REPORT = "qa/run-validation-report.json"


def _report_target(run_dir: Path, candidate: str) -> Path:
    target = resolve_run_path(run_dir, candidate)
    inputs = (
        "sprite-request.json", "source-provenance.json", "manifest.json",
        "frames/frames-manifest.json",
    )
    if target in {(run_dir / name).resolve() for name in inputs}:
        raise PathSafetyError("report output would replace a run input")
    if target.exists():
        try:
            previous = json.loads(target.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise PathSafetyError(f"report output would replace an unreadable or non-report artifact: {exc}") from exc
        if (
            not isinstance(previous, dict)
            or previous.get("kind") != "sprite-run-validation-report"
            or previous.get("version") != 1
        ):
            raise PathSafetyError("report output would replace a non-aggregate artifact")
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--stage", required=True, choices=STAGES)
    parser.add_argument("--workflow", default="production")
    parser.add_argument("--gate", action="append", dest="gates")
    parser.add_argument("--allow-imported-source", action="store_true")
    parser.add_argument("--allow-fixture", action="store_true")
    parser.add_argument("--report", default=DEFAULT_REPORT)
    args = parser.parse_args()

    run_dir = args.run_dir.expanduser().resolve()
    if not run_dir.is_dir():
        print(f"run directory does not exist: {run_dir}", file=sys.stderr)
        return 3
    try:
        target = _report_target(run_dir, args.report)
    except PathSafetyError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except OSError as exc:
        print(str(exc), file=sys.stderr)
        return 3

    try:
        lease = acquire_run_lock(run_dir, "validate_run")
    except RunLockError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    atexit.register(lease.release)
    report, exit_code = validate_run(
        run_dir,
        stage=args.stage,
        workflow=args.workflow,
        selectors=args.gates,
        allow_imported=args.allow_imported_source,
        allow_fixture=args.allow_fixture,
    )
    schema_path = (
        Path(__file__).resolve().parents[1]
        / "references"
        / "schemas"
        / "run-validation-report-v1.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    schema_errors = sorted(
        validator.iter_errors(report), key=lambda error: list(error.absolute_path)
    )
    if schema_errors:
        for error in schema_errors:
            path = ".".join(str(part) for part in error.absolute_path)
            print(f"aggregate report schema error {path}: {error.message}", file=sys.stderr)
        return 3
    try:
        target = _report_target(run_dir, args.report)
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(
            target, json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        )
    except PathSafetyError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except OSError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
