from __future__ import annotations

from copy import deepcopy
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


def _write_asset(path: Path, *, size: tuple[int, int] = (32, 32), alpha: bool = True) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGBA", size, (0, 0, 0, 0) if alpha else (80, 120, 160, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((6, 4, size[0] - 7, size[1] - 3), fill=(120, 80, 40, 255))
    image.save(path)
    return sha256(path.read_bytes()).hexdigest()


def _valid_pack(root: Path) -> dict:
    barrel_hash = _write_asset(root / "sources" / "barrel.png")
    red_hash = _write_asset(root / "sources" / "barrel-red.png")
    return {
        "schema_version": 1,
        "kind": "static-game-asset-pack",
        "pack_id": "forest-props",
        "style_fingerprint": "sha256:" + "1" * 64,
        "licenses": [
            {"id": "owned-art", "status": "user-owned", "reference": "project-owner"}
        ],
        "assets": [
            {
                "id": "barrel",
                "role": "prop",
                "source": {"path": "sources/barrel.png", "sha256": barrel_hash},
                "target": {"width": 32, "height": 32},
                "pivot": {"x": 0.5, "y": 1.0},
                "transparency": "required",
                "crop_policy": "contain",
                "scale_class": "medium",
                "license_ref": "owned-art",
            },
            {
                "id": "barrel-red",
                "role": "prop",
                "source": {"path": "sources/barrel-red.png", "sha256": red_hash},
                "target": {"width": 32, "height": 32},
                "pivot": {"x": 0.5, "y": 1.0},
                "transparency": "required",
                "crop_policy": "contain",
                "scale_class": "medium",
                "license_ref": "owned-art",
                "variant_of": "barrel",
                "parent_sha256": barrel_hash,
                "axes": {"palette": "red"},
                "allowed_transforms": ["recolor"],
            },
        ],
    }


def test_static_pack_validates_files_lineage_and_renders_contact_sheet(tmp_path: Path) -> None:
    from static_assets import validate_static_pack

    pack = _valid_pack(tmp_path)
    contact = tmp_path / "qa" / "static-pack-contact.png"

    report = validate_static_pack(pack, root=tmp_path, contact_sheet=contact)

    assert report["ok"] is True
    assert report["checked_assets"] == ["barrel", "barrel-red"]
    assert contact.is_file()
    assert report["contact_sheet"]["sha256"] == sha256(contact.read_bytes()).hexdigest()
    assert all("absolute_path" not in asset for asset in report["assets"])


def test_static_pack_rejects_changed_source_hash(tmp_path: Path) -> None:
    from static_assets import StaticAssetPackError, validate_static_pack

    pack = _valid_pack(tmp_path)
    (tmp_path / "sources" / "barrel.png").write_bytes(b"changed")

    with pytest.raises(StaticAssetPackError, match="sha256"):
        validate_static_pack(pack, root=tmp_path)


def test_static_pack_rejects_wrong_target_dimensions_and_alpha_policy(tmp_path: Path) -> None:
    from static_assets import StaticAssetPackError, validate_static_pack

    pack = _valid_pack(tmp_path)
    opaque = tmp_path / "sources" / "opaque.png"
    opaque_hash = _write_asset(opaque, size=(24, 24), alpha=False)
    pack["assets"][0]["source"] = {"path": "sources/opaque.png", "sha256": opaque_hash}

    with pytest.raises(StaticAssetPackError, match="dimensions.*transparency|required"):
        validate_static_pack(pack, root=tmp_path)


def test_static_pack_rejects_stale_or_cyclic_variant_lineage(tmp_path: Path) -> None:
    from static_assets import StaticAssetPackError, validate_static_pack

    stale = _valid_pack(tmp_path)
    stale["assets"][1]["parent_sha256"] = "0" * 64
    with pytest.raises(StaticAssetPackError, match="stale parent_sha256"):
        validate_static_pack(stale, root=tmp_path)

    cyclic = _valid_pack(tmp_path)
    cyclic["assets"][0]["variant_of"] = "barrel-red"
    cyclic["assets"][0]["parent_sha256"] = cyclic["assets"][1]["source"]["sha256"]
    cyclic["assets"][0]["axes"] = {"damage": "clean"}
    cyclic["assets"][0]["allowed_transforms"] = ["recolor"]
    with pytest.raises(StaticAssetPackError, match="variant cycle"):
        validate_static_pack(cyclic, root=tmp_path)


def test_static_pack_rejects_unknown_license_and_unsafe_path(tmp_path: Path) -> None:
    from static_assets import StaticAssetPackError, validate_static_pack

    unknown_license = _valid_pack(tmp_path)
    unknown_license["assets"][0]["license_ref"] = "missing"
    with pytest.raises(StaticAssetPackError, match="license"):
        validate_static_pack(unknown_license, root=tmp_path)

    unsafe = _valid_pack(tmp_path)
    unsafe["assets"][0]["source"]["path"] = "../outside.png"
    with pytest.raises(StaticAssetPackError, match="path|traversal"):
        validate_static_pack(unsafe, root=tmp_path)


def test_static_pack_contract_rejects_variant_without_axes_or_transform_policy(
    tmp_path: Path,
) -> None:
    from static_assets import StaticAssetPackError, validate_static_pack

    pack = _valid_pack(tmp_path)
    del pack["assets"][1]["axes"]
    del pack["assets"][1]["allowed_transforms"]

    with pytest.raises(StaticAssetPackError, match="axes|allowed_transforms"):
        validate_static_pack(pack, root=tmp_path)


def test_static_pack_accepts_fully_read_only_contract_mappings(tmp_path: Path) -> None:
    from static_assets import validate_static_pack

    pack = _valid_pack(tmp_path)
    report = validate_static_pack(_read_only_mappings(pack), root=tmp_path)

    assert report["ok"] is True


def test_static_core_rejects_proof_paths_outside_pack_root(tmp_path: Path) -> None:
    from static_assets import StaticAssetPackError, validate_static_pack

    root = tmp_path / "pack"
    outside = tmp_path / "escaped.png"

    with pytest.raises(StaticAssetPackError, match="proof|root|path"):
        validate_static_pack(_valid_pack(root), root=root, contact_sheet=outside)

    assert not outside.exists()


def test_static_proof_replacement_is_atomic_on_save_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from static_assets import validate_static_pack

    pack = _valid_pack(tmp_path)
    target = tmp_path / "qa" / "static-pack-contact.png"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"previous-proof")

    def fail_after_partial_write(self: Image.Image, path: object, *args: object, **kwargs: object) -> None:
        Path(path).write_bytes(b"partial-proof")
        raise OSError("simulated proof write failure")

    monkeypatch.setattr(Image.Image, "save", fail_after_partial_write)

    with pytest.raises(OSError, match="simulated proof write failure"):
        validate_static_pack(pack, root=tmp_path, contact_sheet=target)

    assert target.read_bytes() == b"previous-proof"
    assert not list(target.parent.glob(f".{target.name}.*.tmp"))
