"""Synthetic geometry fixtures only; these tests do not evaluate generated art."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

from PIL import Image
import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "SKILLS/spritesheet-expert/scripts"
sys.path.insert(0, str(SCRIPTS))
from spritecore.item_delivery import artifact, DeliveryError, validate_delivery


def save_manifest(root, manifest):
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root / "manifest.json"


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def bundle(tmp_path):
    root = tmp_path / "run"
    (root / "items").mkdir(parents=True)
    (root / "qa").mkdir()
    # The imported label is a validator input, not a claim about fixture origin.
    crop = Image.new("RGBA", (8, 8), (180, 90, 40, 128))
    source = Image.new("RGBA", (16, 16))
    source.paste(crop, (4, 4))
    atlas = Image.new("RGBA", (32, 32))
    atlas.paste(crop, (12, 12))
    source.save(root / "source.png")
    atlas.save(root / "atlas.png")
    crop.save(root / "items/a.png")
    for name in ("pending", "discarded"):
        Image.new("L", source.size).save(root / f"qa/{name}.png")
    content_hash = sha256((8).to_bytes(4, "big") * 2 + crop.tobytes()).hexdigest()
    manifest = {
        "schemaVersion": "deterministic-item-sheet-v1", "kind": "deterministic-item-atlas",
        "source": {"mode": "RGBA", "width": 16, "height": 16, "provenance": "imported"},
        "atlas": {"path": "atlas.png", "width": 32, "height": 32, "sha256": digest(root / "atlas.png")},
        "packing": {"padding": 8, "quantum": 16, "outer_padding": 0},
        "evidence": {"sourceRgba": "source.png", "sourceRgbaSha256": digest(root / "source.png"),
                     "pendingMask": "qa/pending.png", "discardedMask": "qa/discarded.png"},
        "completion": {"pendingPixels": 0, "reviewGatePassed": True, "reviewComplete": True},
        "items": [{"id": "item_a", "contentSha256": content_hash, "qaFlags": [],
            "review": {"status": "approved"}, "source": {"bbox": [4, 4, 12, 12]},
            "artifacts": {"rgba": "items/a.png", "sha256": digest(root / "items/a.png")},
            "geometry": {"originalSize": [8, 8], "frame": [12, 12, 8, 8], "cellRect": [0, 0, 32, 32],
                         "pivot": [0.5, 1], "scale": 1, "rotated": False}}],
    }
    save_manifest(root, manifest)
    return root, manifest


def check(bundle, *, draft=False):
    root, manifest = bundle
    return validate_delivery(save_manifest(root, manifest), draft=draft)


def test_verified_delivery(bundle):
    report = check(bundle)
    assert report["status"] == "pass", report
    assert report["metrics"]["ownedPixels"] == 64
    assert len(report["verifiedArtifacts"]) == 5
    assert report == check(bundle)


@pytest.mark.parametrize("status", ["pending", "rejected", "replace", "regenerate"])
def test_unflagged_item_never_becomes_final_by_completion_boolean(bundle, status):
    bundle[1]["items"][0]["review"]["status"] = status
    assert check(bundle)["status"] == "review-required"
    assert check(bundle, draft=True)["status"] == "pass"


def test_fixture_is_not_production(bundle):
    bundle[1]["source"]["provenance"] = "fixture"
    assert check(bundle)["status"] == "review-required"
    assert check(bundle, draft=True)["status"] == "pass"


def test_hard_failure_cannot_be_approved_away(bundle):
    bundle[1]["items"][0]["qaFlags"] = ["touching_source_edge"]
    assert check(bundle)["status"] == "review-required"


@pytest.mark.parametrize("target", ["atlas.png", "source.png", "items/a.png"])
def test_hash_mismatch_even_in_draft(bundle, target):
    (bundle[0] / target).write_bytes(b"not the original image")
    for draft in (False, True):
        assert check(bundle, draft=draft)["status"] == "invalid"


def test_rehashed_atlas_still_must_match_pixels(bundle):
    root, manifest = bundle
    with Image.open(root / "atlas.png") as image:
        image.putpixel((12, 12), (0, 0, 0, 128))
        image.save(root / "atlas.png")
    manifest["atlas"]["sha256"] = digest(root / "atlas.png")
    report = check(bundle)
    assert report["status"] == "invalid"
    assert "atlas pixels differ" in report["integrityErrors"][0]


def test_atlas_gutter_is_transparent(bundle):
    root, manifest = bundle
    with Image.open(root / "atlas.png") as image:
        image.putpixel((0, 0), (255, 0, 0, 255))
        image.save(root / "atlas.png")
    manifest["atlas"]["sha256"] = digest(root / "atlas.png")
    assert "unaccounted atlas" in check(bundle)["integrityErrors"][0]


@pytest.mark.parametrize("field,value", [
    ("frame", [12, 12, 0, 8]), ("frame", [True, 12, 8, 8]),
    ("originalSize", [9, 8]), ("cellRect", [1, 0, 32, 32]),
    ("pivot", [float("nan"), 0.5]), ("pivot", [True, 0.5]), ("pivot", [2, 0.5]),
    ("scale", True), ("scale", 2), ("rotated", True),
])
def test_geometry_contract(bundle, field, value):
    bundle[1]["items"][0]["geometry"][field] = value
    assert check(bundle)["status"] == "invalid"


def test_source_bounds_are_xyxy_not_xywh(bundle):
    bundle[1]["items"][0]["source"]["bbox"] = [4, 4, 8, 8]
    assert check(bundle)["status"] == "invalid"


def test_duplicate_ids(bundle):
    bundle[1]["items"].append(deepcopy(bundle[1]["items"][0]))
    assert check(bundle)["status"] == "invalid"


def test_overlapping_cells(bundle):
    item = deepcopy(bundle[1]["items"][0])
    item["id"] = "item_b"
    bundle[1]["items"].append(item)
    assert "overlapping" in check(bundle)["integrityErrors"][0]


@pytest.mark.parametrize("relative", ["../escape.png", "/absolute.png", "C:/image.png", "items\\a.png"])
def test_unsafe_paths(bundle, relative):
    bundle[1]["items"][0]["artifacts"]["rgba"] = relative
    assert check(bundle, draft=True)["status"] == "invalid"


def test_no_basename_fallback(bundle):
    bundle[1]["items"][0]["artifacts"]["rgba"] = "wrong/a.png"
    assert check(bundle)["status"] == "invalid"


def test_symlink_is_rejected(bundle):
    root, _ = bundle
    try:
        (root / "link.png").symlink_to(root / "items/a.png")
    except OSError:
        pytest.skip("symlink creation unavailable on this host")
    with pytest.raises(DeliveryError):
        artifact(root, "link.png")


def test_pending_counter_must_match_pixels(bundle):
    bundle[1]["completion"]["pendingPixels"] = 1
    assert check(bundle)["status"] == "invalid"


def test_pending_cannot_own_accepted_pixels(bundle):
    root, _ = bundle
    with Image.open(root / "qa/pending.png") as mask:
        mask.putpixel((4, 4), 255)
        mask.save(root / "qa/pending.png")
    assert "overlap" in check(bundle)["integrityErrors"][0]


def test_mask_cannot_invent_source_pixels(bundle):
    root, manifest = bundle
    with Image.open(root / "qa/pending.png") as mask:
        mask.putpixel((0, 0), 255)
        mask.save(root / "qa/pending.png")
    manifest["completion"]["pendingPixels"] = 1
    assert check(bundle)["status"] == "invalid"


def test_masks_must_be_binary(bundle):
    root, _ = bundle
    with Image.open(root / "qa/discarded.png") as mask:
        mask.putpixel((0, 0), 20)
        mask.save(root / "qa/discarded.png")
    assert "binary" in check(bundle)["integrityErrors"][0]


def test_missing_digest_not_silently_accepted(bundle):
    bundle[1]["atlas"]["sha256"] = None
    assert check(bundle)["status"] == "invalid"


def test_texture_limit(bundle):
    root, manifest = bundle
    report = validate_delivery(save_manifest(root, manifest), max_texture_size=16)
    assert "texture limit" in report["integrityErrors"][0]


def test_empty_manifest_items(bundle):
    bundle[1]["items"] = []
    assert check(bundle)["status"] == "invalid"


def test_unknown_manifest_contract(bundle):
    bundle[1]["schemaVersion"] = "future-format"
    assert check(bundle)["status"] == "invalid"


def test_invalid_json_returns_diagnostic(bundle):
    path = bundle[0] / "bad.json"
    path.write_text("{", encoding="utf-8")
    assert validate_delivery(path)["status"] == "invalid"


def test_cli_exit_codes(bundle):
    root, manifest = bundle
    command = [sys.executable, str(SCRIPTS / "validate_item_delivery.py"), "--manifest", str(root / "manifest.json")]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    assert result.returncode == 0
    assert json.loads(result.stdout)["status"] == "pass"
    manifest["items"][0]["review"]["status"] = "pending"
    save_manifest(root, manifest)
    assert subprocess.run(command, capture_output=True, check=False).returncode == 2
    assert subprocess.run(command + ["--draft"], capture_output=True, check=False).returncode == 0
    (root / "atlas.png").unlink()
    assert subprocess.run(command, capture_output=True, check=False).returncode == 3


def test_json_hash_export_uses_frame_not_cell(bundle):
    from export_item_atlas import export_atlas
    root, _ = bundle
    output = root.parent / "export"
    receipt = export_atlas(root / "manifest.json", output)
    data = json.loads((output / "atlas.json").read_text())
    frame = data["frames"]["item_a"]
    assert frame["frame"] == {"x": 12, "y": 12, "w": 8, "h": 8}
    assert frame["sourceSize"] == {"w": 8, "h": 8}
    assert frame["pivot"] == {"x": 0.5, "y": 1}
    assert (output / "atlas.png").read_bytes() == (root / "atlas.png").read_bytes()
    assert receipt["engineSmokeTested"] is False
    for name, expected in receipt["files"].items():
        assert digest(output / name) == expected
    with pytest.raises(DeliveryError):
        export_atlas(root / "manifest.json", output)


def test_export_does_not_publish_unreviewed_assets(bundle):
    from export_item_atlas import export_atlas
    root, manifest = bundle
    manifest["items"][0]["review"]["status"] = "pending"
    save_manifest(root, manifest)
    with pytest.raises(DeliveryError):
        export_atlas(root / "manifest.json", root.parent / "final")
    assert not (root.parent / "final").exists()
    receipt = export_atlas(root / "manifest.json", root.parent / "draft", draft=True)
    assert receipt["draft"] is True


def test_export_cannot_replace_or_nest_in_source_run(bundle):
    from export_item_atlas import export_atlas
    root, _ = bundle
    for target in [root, root / "export", root.parent]:
        with pytest.raises(DeliveryError):
            export_atlas(root / "manifest.json", target)


def test_two_exports_are_byte_identical(bundle):
    from export_item_atlas import export_atlas
    root, _ = bundle
    left, right = root.parent / "left", root.parent / "right"
    export_atlas(root / "manifest.json", left)
    export_atlas(root / "manifest.json", right)
    assert sorted(p.name for p in left.iterdir()) == sorted(p.name for p in right.iterdir())
    assert all(p.read_bytes() == (right / p.name).read_bytes() for p in left.iterdir())
