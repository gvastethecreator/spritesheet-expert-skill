from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

from PIL import Image
import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
BACKGROUND_SCRIPT = (
    REPO_ROOT
    / "SKILLS"
    / "build-game-backgrounds"
    / "scripts"
    / "validate_background_pack.py"
)
UI_SCRIPT = (
    REPO_ROOT
    / "SKILLS"
    / "build-game-ui-kits"
    / "scripts"
    / "validate_ui_kit.py"
)
STATIC_SCRIPT = (
    REPO_ROOT
    / "SKILLS"
    / "build-static-game-assets"
    / "scripts"
    / "validate_static_pack.py"
)


def _write_background_pack(root: Path) -> Path:
    layer_path = root / "layers" / "sky.png"
    layer_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (16, 8), (40, 80, 160, 255)).save(layer_path)
    document = {
        "schema_version": 1,
        "kind": "game-background-pack",
        "pack_id": "test-background",
        "style_fingerprint": "sha256:" + "1" * 64,
        "canvas": {"width": 16, "height": 8, "color_space": "srgb"},
        "camera": {
            "aspect_ratio": "2:1",
            "horizon_y": 0.5,
            "focal_safe_zone": {"x": 0.25, "y": 0.25, "width": 0.5, "height": 0.5},
        },
        "layers": [
            {
                "id": "sky",
                "role": "sky",
                "path": "layers/sky.png",
                "sha256": sha256(layer_path.read_bytes()).hexdigest(),
                "order": 0,
                "depth": 0.0,
                "parallax_x": 0.0,
                "parallax_y": 0.0,
                "repeat_x": True,
                "blend_mode": "normal",
            }
        ],
    }
    pack_path = root / "background-pack.json"
    pack_path.write_text(json.dumps(document), encoding="utf-8")
    return pack_path


def _write_ui_kit(root: Path) -> Path:
    image_path = root / "components" / "button-default.png"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (16, 8), (40, 80, 160, 255)).save(image_path)
    document = {
        "schema_version": 1,
        "kind": "game-ui-raster-kit",
        "kit_id": "test-ui",
        "style_fingerprint": "sha256:" + "2" * 64,
        "densities": [1],
        "tokens": {
            "foreground": "#FFFFFF",
            "background": "#000000",
            "minimum_contrast": 4.5,
        },
        "components": [
            {
                "id": "primary-button",
                "type": "button",
                "base_size": {"width": 16, "height": 8},
                "required_states": ["default"],
                "states": {
                    "default": [
                        {
                            "density": 1,
                            "path": "components/button-default.png",
                            "sha256": sha256(image_path.read_bytes()).hexdigest(),
                        }
                    ]
                },
            }
        ],
    }
    kit_path = root / "ui-kit.json"
    kit_path.write_text(json.dumps(document), encoding="utf-8")
    return kit_path


def _write_static_pack(root: Path) -> Path:
    image_path = root / "assets" / "crate.png"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    for y in range(3, 14):
        for x in range(3, 13):
            image.putpixel((x, y), (140, 80, 40, 255))
    image.save(image_path)
    document = {
        "schema_version": 1,
        "kind": "static-game-asset-pack",
        "pack_id": "test-static",
        "style_fingerprint": "sha256:" + "3" * 64,
        "licenses": [
            {"id": "test-art", "status": "fixture", "reference": "integration"}
        ],
        "assets": [
            {
                "id": "crate",
                "role": "prop",
                "source": {
                    "path": "assets/crate.png",
                    "sha256": sha256(image_path.read_bytes()).hexdigest(),
                },
                "target": {"width": 16, "height": 16},
                "pivot": {"x": 0.5, "y": 1.0},
                "transparency": "required",
                "crop_policy": "contain",
                "scale_class": "small",
                "license_ref": "test-art",
            }
        ],
    }
    pack_path = root / "static-pack.json"
    pack_path.write_text(json.dumps(document), encoding="utf-8")
    return pack_path


def test_background_cli_writes_current_atomic_proof_report(tmp_path: Path) -> None:
    pack_path = _write_background_pack(tmp_path)

    result = subprocess.run(
        [
            sys.executable,
            str(BACKGROUND_SCRIPT),
            "--pack",
            str(pack_path),
            "--root",
            str(tmp_path),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(
        (tmp_path / "qa" / "background-pack-report.json").read_text(encoding="utf-8")
    )
    composite = tmp_path / "qa" / "background-composite.png"
    scroll = tmp_path / "qa" / "background-scroll.gif"
    assert report["ok"] is True
    assert report["composite"]["path"] == "qa/background-composite.png"
    assert report["scroll_preview"]["path"] == "qa/background-scroll.gif"
    assert report["composite"]["sha256"] == sha256(composite.read_bytes()).hexdigest()
    assert report["scroll_preview"]["sha256"] == sha256(scroll.read_bytes()).hexdigest()
    assert not list((tmp_path / "qa").glob(".*.tmp"))


def test_ui_cli_writes_current_atomic_proof_report(tmp_path: Path) -> None:
    kit_path = _write_ui_kit(tmp_path)

    result = subprocess.run(
        [
            sys.executable,
            str(UI_SCRIPT),
            "--kit",
            str(kit_path),
            "--root",
            str(tmp_path),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(
        (tmp_path / "qa" / "ui-kit-report.json").read_text(encoding="utf-8")
    )
    state_board = tmp_path / "qa" / "ui-state-board.png"
    stretch_board = tmp_path / "qa" / "ui-nine-slice.png"
    assert report["ok"] is True
    assert report["state_board"]["path"] == "qa/ui-state-board.png"
    assert report["stretch_board"]["path"] == "qa/ui-nine-slice.png"
    assert report["state_board"]["sha256"] == sha256(state_board.read_bytes()).hexdigest()
    assert report["stretch_board"]["sha256"] == sha256(stretch_board.read_bytes()).hexdigest()
    assert not list((tmp_path / "qa").glob(".*.tmp"))


def test_static_cli_writes_current_atomic_proof_report_without_host_paths(
    tmp_path: Path,
) -> None:
    pack_path = _write_static_pack(tmp_path)

    result = subprocess.run(
        [
            sys.executable,
            str(STATIC_SCRIPT),
            "--pack",
            str(pack_path),
            "--root",
            str(tmp_path),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    report_path = tmp_path / "qa" / "static-pack-report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    contact = tmp_path / "qa" / "static-pack-contact.png"
    assert report["ok"] is True
    assert report["contact_sheet"]["path"] == "qa/static-pack-contact.png"
    assert report["contact_sheet"]["sha256"] == sha256(contact.read_bytes()).hexdigest()
    assert "absolute_path" not in report_path.read_text(encoding="utf-8")
    assert not list((tmp_path / "qa").glob(".*.tmp"))


def test_static_cli_classifies_malformed_json_as_contract_failure(tmp_path: Path) -> None:
    pack_path = tmp_path / "static-pack.json"
    pack_path.write_text("{", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(STATIC_SCRIPT),
            "--pack",
            str(pack_path),
            "--root",
            str(tmp_path),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1, result.stdout + result.stderr
    report = json.loads(
        (tmp_path / "qa" / "static-pack-report.json").read_text(encoding="utf-8")
    )
    assert report["ok"] is False
    assert "invalid pack document" in report["errors"][0]


@pytest.mark.parametrize(
    ("script", "document_flag", "writer", "proof_paths"),
    [
        (
            STATIC_SCRIPT,
            "--pack",
            _write_static_pack,
            ("qa/static-pack-contact.png",),
        ),
        (
            BACKGROUND_SCRIPT,
            "--pack",
            _write_background_pack,
            ("qa/background-composite.png", "qa/background-scroll.gif"),
        ),
        (
            UI_SCRIPT,
            "--kit",
            _write_ui_kit,
            ("qa/ui-state-board.png", "qa/ui-nine-slice.png"),
        ),
    ],
)
def test_leaf_clis_do_not_mutate_proofs_before_contract_validation(
    tmp_path: Path,
    script: Path,
    document_flag: str,
    writer: object,
    proof_paths: tuple[str, ...],
) -> None:
    document_path = writer(tmp_path)  # type: ignore[operator]
    document = json.loads(document_path.read_text(encoding="utf-8"))
    document["schema_version"] = 999
    document_path.write_text(json.dumps(document), encoding="utf-8")
    proofs = [tmp_path / relative for relative in proof_paths]
    for proof in proofs:
        proof.parent.mkdir(parents=True, exist_ok=True)
        proof.write_bytes(b"previous-proof")

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            document_flag,
            str(document_path),
            "--root",
            str(tmp_path),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert all(proof.read_bytes() == b"previous-proof" for proof in proofs)


@pytest.mark.parametrize(
    ("script", "document_flag", "writer", "proof_flag"),
    [
        (STATIC_SCRIPT, "--pack", _write_static_pack, "--contact-sheet"),
        (BACKGROUND_SCRIPT, "--pack", _write_background_pack, "--composite"),
        (UI_SCRIPT, "--kit", _write_ui_kit, "--state-board"),
    ],
)
def test_leaf_clis_reject_unsafe_root_relative_proof_paths(
    tmp_path: Path,
    script: Path,
    document_flag: str,
    writer: object,
    proof_flag: str,
) -> None:
    document_path = writer(tmp_path)  # type: ignore[operator]
    escaped = tmp_path.parent / "escaped-proof.png"
    escaped.unlink(missing_ok=True)

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            document_flag,
            str(document_path),
            "--root",
            str(tmp_path),
            proof_flag,
            "../escaped-proof.png",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert not escaped.exists()


@pytest.mark.parametrize(
    ("script", "document_flag", "writer", "source_relative"),
    [
        (STATIC_SCRIPT, "--pack", _write_static_pack, "assets/crate.png"),
        (BACKGROUND_SCRIPT, "--pack", _write_background_pack, "layers/sky.png"),
        (UI_SCRIPT, "--kit", _write_ui_kit, "components/button-default.png"),
    ],
)
def test_leaf_cli_report_cannot_overwrite_a_validated_source(
    tmp_path: Path,
    script: Path,
    document_flag: str,
    writer: object,
    source_relative: str,
) -> None:
    document_path = writer(tmp_path)  # type: ignore[operator]
    source = tmp_path / source_relative
    previous = source.read_bytes()

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            document_flag,
            str(document_path),
            "--root",
            str(tmp_path),
            "--report",
            source_relative,
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert source.read_bytes() == previous


@pytest.mark.parametrize(
    ("script", "document_flag"),
    [
        (STATIC_SCRIPT, "--pack"),
        (BACKGROUND_SCRIPT, "--pack"),
        (UI_SCRIPT, "--kit"),
    ],
)
def test_leaf_clis_use_exit_three_for_missing_input_io(
    tmp_path: Path,
    script: Path,
    document_flag: str,
) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            document_flag,
            str(tmp_path / "missing.json"),
            "--root",
            str(tmp_path),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 3, result.stdout + result.stderr
    assert "operational failure" in result.stdout


@pytest.mark.parametrize(
    ("script", "document_flag", "filename", "report_relative"),
    [
        (STATIC_SCRIPT, "--pack", "static-pack.json", "qa/static-pack-report.json"),
        (
            BACKGROUND_SCRIPT,
            "--pack",
            "background-pack.json",
            "qa/background-pack-report.json",
        ),
        (UI_SCRIPT, "--kit", "ui-kit.json", "qa/ui-kit-report.json"),
    ],
)
def test_leaf_clis_classify_invalid_utf8_as_contract_failure(
    tmp_path: Path,
    script: Path,
    document_flag: str,
    filename: str,
    report_relative: str,
) -> None:
    document_path = tmp_path / filename
    document_path.write_bytes(b"\xff")

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            document_flag,
            str(document_path),
            "--root",
            str(tmp_path),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert "invalid" in result.stdout
    assert result.stderr == ""
    assert json.loads((tmp_path / report_relative).read_text(encoding="utf-8"))["ok"] is False


@pytest.mark.parametrize("script", [STATIC_SCRIPT, BACKGROUND_SCRIPT, UI_SCRIPT])
def test_leaf_clis_use_exit_one_for_command_contract_errors(script: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert "command line" in result.stdout
