from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import ModuleType

from jsonschema import Draft202012Validator
import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
LEAF_SCRIPTS = (
    REPO_ROOT
    / "SKILLS"
    / "build-static-game-assets"
    / "scripts"
    / "validate_static_pack.py",
    REPO_ROOT
    / "SKILLS"
    / "build-game-backgrounds"
    / "scripts"
    / "validate_background_pack.py",
    REPO_ROOT
    / "SKILLS"
    / "build-game-ui-kits"
    / "scripts"
    / "validate_ui_kit.py",
)
LEAF_SCHEMAS = (
    REPO_ROOT
    / "SKILLS"
    / "build-static-game-assets"
    / "references"
    / "schemas"
    / "static-asset-pack-v1.schema.json",
    REPO_ROOT
    / "SKILLS"
    / "build-game-backgrounds"
    / "references"
    / "schemas"
    / "background-pack-v1.schema.json",
    REPO_ROOT
    / "SKILLS"
    / "build-game-ui-kits"
    / "references"
    / "schemas"
    / "ui-kit-v1.schema.json",
)
HELP_SCRIPTS = (
    *LEAF_SCRIPTS,
    REPO_ROOT
    / "SKILLS"
    / "produce-2d-assets"
    / "scripts"
    / "validate_asset_pack.py",
)


def _load_script(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"test_{path.stem}_{path.parent.parent.name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("script_path", HELP_SCRIPTS, ids=lambda path: path.stem)
def test_leaf_help_works_without_site_packages(script_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-S", str(script_path), "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "usage:" in result.stdout


@pytest.mark.parametrize("schema_path", LEAF_SCHEMAS, ids=lambda path: path.stem)
def test_leaf_schema_meta_validates_as_draft_2020_12(schema_path: Path) -> None:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    Draft202012Validator.check_schema(schema)


@pytest.mark.parametrize("script_path", LEAF_SCRIPTS, ids=lambda path: path.stem)
def test_leaf_report_replacement_is_atomic_on_serialization_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    script_path: Path,
) -> None:
    module = _load_script(script_path)
    target = tmp_path / "report.json"
    target.write_bytes(b"previous-report")

    def fail_after_partial_write(payload: object, handle: object, **kwargs: object) -> None:
        handle.write("partial-report")  # type: ignore[attr-defined]
        raise OSError("simulated report write failure")

    monkeypatch.setattr(module.json, "dump", fail_after_partial_write)

    with pytest.raises(OSError, match="simulated report write failure"):
        module._atomic_json(target, {"ok": True})

    assert target.read_bytes() == b"previous-report"
    assert not list(tmp_path.glob(f".{target.name}.*.tmp"))
