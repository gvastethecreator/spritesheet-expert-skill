#!/usr/bin/env python3
"""Validate an asset pack, its deliverables, and every leaf validation report."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping

DEFAULT_REPORT = "validation/asset-pack-validation-report.json"


def _failure_report(
    *,
    pack_id: str | None,
    pack_root: Path,
    blocker: str,
    status: str,
    input_fingerprint: str | None,
) -> tuple[dict[str, Any], int]:
    exit_code = {"fail": 1, "blocked": 2, "operational-error": 3}[status]
    return (
        {
            "version": 1,
            "kind": "asset-pack-validation-report",
            "pack_id": pack_id,
            "pack_root": str(pack_root),
            "ok": False,
            "status": status,
            "complete": status == "fail",
            "exit_code": exit_code,
            "input_fingerprint": input_fingerprint,
            "checked_assets": [],
            "deliverables": [],
            "leaf_reports": [],
            "blockers": [blocker],
        },
        exit_code,
    )


def _atomic_write_json(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
            temporary_path = Path(handle.name)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument(
        "--pack-root",
        type=Path,
        help="artifact root; defaults to the asset-pack document directory",
    )
    parser.add_argument("--report", default=DEFAULT_REPORT)
    args = parser.parse_args()

    pack_path = args.pack.expanduser().resolve()
    pack_root = (
        args.pack_root.expanduser().resolve()
        if args.pack_root is not None
        else pack_path.parent
    )
    try:
        from assetpack import AssetPackContractError, validate_asset_pack_root
        from assetpack.paths import resolve_pack_path
    except ModuleNotFoundError as exc:
        dependency = exc.name or "required package"
        report, exit_code = _failure_report(
            pack_id=None,
            pack_root=pack_root,
            blocker=(
                f"missing runtime dependency '{dependency}'; from the repository "
                "root run: python -m pip install -e ."
            ),
            status="operational-error",
            input_fingerprint=None,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return exit_code
    raw: bytes | None = None
    document: Mapping[str, Any] | None = None
    try:
        if not pack_path.is_relative_to(pack_root):
            raise OSError("asset-pack document must be below pack root")
        raw = pack_path.read_bytes()
    except OSError as exc:
        report, exit_code = _failure_report(
            pack_id=None,
            pack_root=pack_root,
            blocker=f"could not read asset-pack document: {exc}",
            status="operational-error",
            input_fingerprint=None,
        )
    else:
        pack_fingerprint = sha256(raw).hexdigest()
        try:
            decoded = json.loads(raw.decode("utf-8-sig"))
            if not isinstance(decoded, Mapping):
                raise ValueError("asset-pack root must be a JSON object")
            document = decoded
        except (UnicodeDecodeError, ValueError) as exc:
            report, exit_code = _failure_report(
                pack_id=None,
                pack_root=pack_root,
                blocker=f"invalid asset-pack JSON: {exc}",
                status="fail",
                input_fingerprint=pack_fingerprint,
            )
        else:
            try:
                report, exit_code = validate_asset_pack_root(document, pack_root)
            except AssetPackContractError as exc:
                issue_text = "; ".join(
                    f"{issue.path}: {issue.message}" for issue in exc.issues
                )
                report, exit_code = _failure_report(
                    pack_id=(
                        document.get("pack_id")
                        if isinstance(document.get("pack_id"), str)
                        else None
                    ),
                    pack_root=pack_root,
                    blocker=f"asset-pack contract failed: {issue_text}",
                    status="fail",
                    input_fingerprint=pack_fingerprint,
                )

    try:
        report_path = resolve_pack_path(pack_root, args.report)
        _atomic_write_json(report_path, report)
    except (OSError, ValueError) as exc:
        report["ok"] = False
        report["status"] = "operational-error"
        report["complete"] = False
        report["exit_code"] = 3
        report["blockers"] = sorted(
            {*report["blockers"], f"could not write aggregate report: {exc}"}
        )
        exit_code = 3

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
