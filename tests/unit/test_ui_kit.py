from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from typing import Any

from PIL import Image, ImageDraw
import pytest


def _read_only_mappings(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType(
            {key: _read_only_mappings(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return [_read_only_mappings(item) for item in value]
    return value


def _state_image(path: Path, size: tuple[int, int], fill: tuple[int, int, int, int]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGBA", size, fill)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, size[0] - 1, size[1] - 1), outline=(240, 240, 245, 255), width=max(1, size[0] // 16))
    image.save(path)
    return sha256(path.read_bytes()).hexdigest()


def _imported_provenance() -> dict:
    return {"source_type": "imported", "art_engine": "imported", "fixture": False, "verification_status": "verified"}


def _kit(root: Path) -> dict:
    states = {}
    for state, color in (("default", (35, 55, 85, 255)), ("pressed", (20, 35, 60, 255))):
        variants = []
        for density in (1, 2):
            path = root / "components" / f"panel-{state}@{density}x.png"
            digest = _state_image(path, (32 * density, 16 * density), color)
            variants.append(
                {
                    "density": density,
                    "path": f"components/{path.name}",
                    "sha256": digest,
                    "provenance": _imported_provenance(),
                }
            )
        states[state] = variants
    return {
        "schema_version": 1,
        "kind": "game-ui-raster-kit",
        "kit_id": "forest-hud",
        "style_fingerprint": "sha256:" + "3" * 64,
        "densities": [1, 2],
        "tokens": {
            "foreground": "#F8FAFC",
            "background": "#18243A",
            "minimum_contrast": 4.5,
        },
        "components": [
            {
                "id": "status-panel",
                "type": "panel",
                "base_size": {"width": 32, "height": 16},
                "required_states": ["default", "pressed"],
                "states": states,
                "nine_slice": {
                    "left": 4,
                    "top": 4,
                    "right": 4,
                    "bottom": 4,
                    "content_safe": {"x": 5, "y": 5, "width": 22, "height": 6},
                },
            }
        ],
    }


def test_ui_kit_validates_state_density_parity_and_renders_proof_boards(tmp_path: Path) -> None:
    from ui_kit import validate_ui_kit

    report = validate_ui_kit(
        _kit(tmp_path),
        root=tmp_path,
        state_board_path=tmp_path / "qa" / "ui-state-board.png",
        stretch_board_path=tmp_path / "qa" / "ui-nine-slice.png",
    )

    assert report["ok"] is True
    assert report["representative"] is True
    assert report["source_types"] == ["imported"]
    assert report["evidence"]["production_media"]["provenance_verified"] is True
    assert report["state_board"]["views"] == ["checker", "black", "gray", "white"]
    assert report["checked_components"] == ["status-panel"]
    assert report["contrast_ratio"] >= 4.5
    assert (tmp_path / "qa" / "ui-state-board.png").is_file()
    assert (tmp_path / "qa" / "ui-nine-slice.png").is_file()


def test_ui_kit_rejects_missing_state_or_density_variant(tmp_path: Path) -> None:
    from ui_kit import UiKitError, validate_ui_kit

    missing_state = _kit(tmp_path)
    del missing_state["components"][0]["states"]["pressed"]
    with pytest.raises(UiKitError, match="pressed"):
        validate_ui_kit(missing_state, root=tmp_path)

    missing_density = _kit(tmp_path)
    missing_density["components"][0]["states"]["default"].pop()
    with pytest.raises(UiKitError, match="density"):
        validate_ui_kit(missing_density, root=tmp_path)


def test_ui_kit_rejects_wrong_dimensions_or_stale_hash(tmp_path: Path) -> None:
    from ui_kit import UiKitError, validate_ui_kit

    kit = _kit(tmp_path)
    kit["components"][0]["states"]["default"][0]["sha256"] = "0" * 64
    with pytest.raises(UiKitError, match="sha256"):
        validate_ui_kit(kit, root=tmp_path)

    wrong = _kit(tmp_path)
    variant = wrong["components"][0]["states"]["default"][0]
    Image.new("RGBA", (31, 16), (20, 20, 20, 255)).save(tmp_path / variant["path"])
    variant["sha256"] = sha256((tmp_path / variant["path"]).read_bytes()).hexdigest()
    with pytest.raises(UiKitError, match="dimensions"):
        validate_ui_kit(wrong, root=tmp_path)


def test_ui_kit_rejects_invalid_nine_slice_content_safe_area(tmp_path: Path) -> None:
    from ui_kit import UiKitError, validate_ui_kit

    kit = _kit(tmp_path)
    kit["components"][0]["nine_slice"]["content_safe"]["x"] = 1

    with pytest.raises(UiKitError, match="content_safe"):
        validate_ui_kit(kit, root=tmp_path)


def test_ui_kit_rejects_insufficient_token_contrast(tmp_path: Path) -> None:
    from ui_kit import UiKitError, validate_ui_kit

    kit = _kit(tmp_path)
    kit["tokens"]["foreground"] = "#777777"
    kit["tokens"]["background"] = "#707070"

    with pytest.raises(UiKitError, match="contrast"):
        validate_ui_kit(kit, root=tmp_path)


def test_ui_kit_rejects_unsafe_component_path(tmp_path: Path) -> None:
    from ui_kit import UiKitError, validate_ui_kit

    kit = _kit(tmp_path)
    kit["components"][0]["states"]["default"][0]["path"] = "../escape.png"

    with pytest.raises(UiKitError, match="path|traversal"):
        validate_ui_kit(kit, root=tmp_path)


def test_ui_kit_accepts_fully_read_only_contract_mappings(tmp_path: Path) -> None:
    from ui_kit import validate_ui_kit

    report = validate_ui_kit(_read_only_mappings(_kit(tmp_path)), root=tmp_path)

    assert report["ok"] is True


def test_ui_kit_marks_fixtures_non_representative_and_requires_provenance(
    tmp_path: Path,
) -> None:
    from ui_kit import UiKitError, validate_ui_kit

    fixture = _kit(tmp_path)
    for variants in fixture["components"][0]["states"].values():
        for variant in variants:
            variant["provenance"] = {"source_type": "fixture", "art_engine": "fixture", "fixture": True, "verification_status": "verified"}
    assert validate_ui_kit(fixture, root=tmp_path)["representative"] is False

    missing = _kit(tmp_path)
    del missing["components"][0]["states"]["default"][0]["provenance"]
    with pytest.raises(UiKitError, match="provenance"):
        validate_ui_kit(missing, root=tmp_path)


def test_ui_kit_rejects_a_stale_grok_provider_record(tmp_path: Path) -> None:
    from ui_kit import UiKitError, validate_ui_kit

    kit = _kit(tmp_path)
    record = tmp_path / "provider" / "invocation.json"
    record.parent.mkdir()
    record.write_text('{"status":"completed"}', encoding="utf-8")
    for variants in kit["components"][0]["states"].values():
        for variant in variants:
            variant["provenance"] = {
                "source_type": "grok-imagine-image",
                "art_engine": "grok-imagine",
                "fixture": False,
                "verification_status": "verified",
                "provider_record": {"path": "provider/invocation.json", "sha256": "0" * 64},
            }

    with pytest.raises(UiKitError, match="provider record sha256 mismatch"):
        validate_ui_kit(kit, root=tmp_path)


def test_ui_proof_replacement_is_atomic_on_save_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ui_kit import validate_ui_kit

    kit = _kit(tmp_path)
    target = tmp_path / "qa" / "ui-state-board.png"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"previous-proof")

    def fail_after_partial_write(self: Image.Image, path: object, *args: object, **kwargs: object) -> None:
        Path(path).write_bytes(b"partial-proof")
        raise OSError("simulated proof write failure")

    monkeypatch.setattr(Image.Image, "save", fail_after_partial_write)

    with pytest.raises(OSError, match="simulated proof write failure"):
        validate_ui_kit(kit, root=tmp_path, state_board_path=target)

    assert target.read_bytes() == b"previous-proof"
    assert not list(target.parent.glob(f".{target.name}.*.tmp"))


def test_ui_core_rejects_proof_paths_outside_kit_root(tmp_path: Path) -> None:
    from ui_kit import UiKitError, validate_ui_kit

    root = tmp_path / "kit"
    outside = tmp_path / "escaped.png"

    with pytest.raises(UiKitError, match="proof|root|path"):
        validate_ui_kit(_kit(root), root=root, state_board_path=outside)

    assert not outside.exists()
