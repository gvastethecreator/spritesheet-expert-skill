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


def _layer(path: Path, color: tuple[int, int, int, int], *, seam: bool = True) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGBA", (64, 32), color)
    draw = ImageDraw.Draw(image)
    draw.rectangle((12, 12, 28, 31), fill=(color[0] // 2, color[1] // 2, color[2] // 2, color[3]))
    if seam:
        for y in range(image.height):
            image.putpixel((image.width - 1, y), image.getpixel((0, y)))
    image.save(path)
    return sha256(path.read_bytes()).hexdigest()


def _imported_provenance() -> dict:
    return {"source_type": "imported", "art_engine": "imported", "fixture": False, "verification_status": "verified"}


def _pack(root: Path) -> dict:
    sky_hash = _layer(root / "layers" / "sky.png", (60, 100, 180, 255))
    far_hash = _layer(root / "layers" / "far.png", (80, 120, 100, 180))
    near_hash = _layer(root / "layers" / "near.png", (40, 80, 50, 220))
    return {
        "schema_version": 1,
        "kind": "game-background-pack",
        "pack_id": "forest-dusk",
        "style_fingerprint": "sha256:" + "2" * 64,
        "canvas": {"width": 64, "height": 32, "color_space": "srgb"},
        "camera": {
            "aspect_ratio": "2:1",
            "horizon_y": 0.42,
            "focal_safe_zone": {"x": 0.25, "y": 0.2, "width": 0.5, "height": 0.5},
        },
        "layers": [
            {"id": "sky", "role": "sky", "path": "layers/sky.png", "sha256": sky_hash, "provenance": _imported_provenance(), "order": 0, "depth": 0.0, "parallax_x": 0.0, "parallax_y": 0.0, "repeat_x": True, "blend_mode": "normal"},
            {"id": "far", "role": "far", "path": "layers/far.png", "sha256": far_hash, "provenance": _imported_provenance(), "order": 1, "depth": 0.5, "parallax_x": 0.25, "parallax_y": 0.05, "repeat_x": True, "blend_mode": "normal"},
            {"id": "near", "role": "near", "path": "layers/near.png", "sha256": near_hash, "provenance": _imported_provenance(), "order": 2, "depth": 1.0, "parallax_x": 0.8, "parallax_y": 0.15, "repeat_x": True, "blend_mode": "normal"},
        ],
    }


def test_background_pack_validates_and_renders_composite_and_scroll_proofs(tmp_path: Path) -> None:
    from background_pack import validate_background_pack

    report = validate_background_pack(
        _pack(tmp_path),
        root=tmp_path,
        composite_path=tmp_path / "qa" / "background-composite.png",
        scroll_path=tmp_path / "qa" / "background-scroll.gif",
    )

    assert report["ok"] is True
    assert report["representative"] is True
    assert report["source_types"] == ["imported"]
    assert report["evidence"]["production_media"]["provenance_verified"] is True
    assert report["checked_layers"] == ["sky", "far", "near"]
    assert (tmp_path / "qa" / "background-composite.png").is_file()
    assert (tmp_path / "qa" / "background-scroll.gif").is_file()


def test_background_pack_rejects_stale_hash_and_wrong_dimensions(tmp_path: Path) -> None:
    from background_pack import BackgroundPackError, validate_background_pack

    pack = _pack(tmp_path)
    pack["layers"][0]["sha256"] = "0" * 64
    pack["layers"][1]["path"] = "layers/wrong.png"
    pack["layers"][1]["sha256"] = _layer(
        tmp_path / "layers" / "wrong.png", (20, 30, 40, 255)
    )
    Image.new("RGBA", (32, 16), (20, 30, 40, 255)).save(tmp_path / "layers" / "wrong.png")
    pack["layers"][1]["sha256"] = sha256((tmp_path / "layers" / "wrong.png").read_bytes()).hexdigest()

    with pytest.raises(BackgroundPackError, match="sha256|dimensions"):
        validate_background_pack(pack, root=tmp_path)


def test_background_pack_rejects_depth_or_parallax_inversion(tmp_path: Path) -> None:
    from background_pack import BackgroundPackError, validate_background_pack

    pack = _pack(tmp_path)
    pack["layers"][2]["parallax_x"] = 0.1

    with pytest.raises(BackgroundPackError, match="parallax"):
        validate_background_pack(pack, root=tmp_path)


def test_background_pack_rejects_broken_repeat_seam(tmp_path: Path) -> None:
    from background_pack import BackgroundPackError, validate_background_pack

    pack = _pack(tmp_path)
    layer = tmp_path / "layers" / "near.png"
    with Image.open(layer) as opened:
        broken = opened.convert("RGBA")
    for y in range(broken.height):
        broken.putpixel((broken.width - 1, y), (255, 0, 255, 255))
    broken.save(layer)
    pack["layers"][2]["sha256"] = sha256(layer.read_bytes()).hexdigest()

    with pytest.raises(BackgroundPackError, match="seam"):
        validate_background_pack(pack, root=tmp_path)


def test_background_pack_rejects_unsafe_layer_path(tmp_path: Path) -> None:
    from background_pack import BackgroundPackError, validate_background_pack

    pack = _pack(tmp_path)
    pack["layers"][0]["path"] = "../sky.png"

    with pytest.raises(BackgroundPackError, match="path|traversal"):
        validate_background_pack(pack, root=tmp_path)


def test_background_pack_accepts_fully_read_only_contract_mappings(
    tmp_path: Path,
) -> None:
    from background_pack import validate_background_pack

    report = validate_background_pack(_read_only_mappings(_pack(tmp_path)), root=tmp_path)

    assert report["ok"] is True


def test_background_pack_marks_fixture_non_representative_and_requires_provenance(
    tmp_path: Path,
) -> None:
    from background_pack import BackgroundPackError, validate_background_pack

    fixture = _pack(tmp_path)
    for layer in fixture["layers"]:
        layer["provenance"] = {"source_type": "fixture", "art_engine": "fixture", "fixture": True, "verification_status": "verified"}
    assert validate_background_pack(fixture, root=tmp_path)["representative"] is False

    missing = _pack(tmp_path)
    del missing["layers"][0]["provenance"]
    with pytest.raises(BackgroundPackError, match="provenance"):
        validate_background_pack(missing, root=tmp_path)


def test_background_pack_rejects_a_stale_grok_provider_record(tmp_path: Path) -> None:
    from background_pack import BackgroundPackError, validate_background_pack

    pack = _pack(tmp_path)
    record = tmp_path / "provider" / "invocation.json"
    record.parent.mkdir()
    record.write_text('{"status":"completed"}', encoding="utf-8")
    for layer in pack["layers"]:
        layer["provenance"] = {
            "source_type": "grok-imagine-image",
            "art_engine": "grok-imagine",
            "fixture": False,
            "verification_status": "verified",
            "provider_record": {"path": "provider/invocation.json", "sha256": "0" * 64},
        }

    with pytest.raises(BackgroundPackError, match="provider record sha256 mismatch"):
        validate_background_pack(pack, root=tmp_path)


def test_background_proof_replacement_is_atomic_on_save_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from background_pack import validate_background_pack

    pack = _pack(tmp_path)
    target = tmp_path / "qa" / "background-composite.png"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"previous-proof")

    def fail_after_partial_write(self: Image.Image, path: object, *args: object, **kwargs: object) -> None:
        Path(path).write_bytes(b"partial-proof")
        raise OSError("simulated proof write failure")

    monkeypatch.setattr(Image.Image, "save", fail_after_partial_write)

    with pytest.raises(OSError, match="simulated proof write failure"):
        validate_background_pack(pack, root=tmp_path, composite_path=target)

    assert target.read_bytes() == b"previous-proof"
    assert not list(target.parent.glob(f".{target.name}.*.tmp"))


def test_background_core_rejects_proof_paths_outside_pack_root(tmp_path: Path) -> None:
    from background_pack import BackgroundPackError, validate_background_pack

    root = tmp_path / "pack"
    outside = tmp_path / "escaped.png"

    with pytest.raises(BackgroundPackError, match="proof|root|path"):
        validate_background_pack(_pack(root), root=root, composite_path=outside)

    assert not outside.exists()
