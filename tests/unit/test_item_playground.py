from __future__ import annotations

import json
import re
from pathlib import Path

from PIL import Image, ImageDraw
import pytest

from spritecore.item_sheet import PackingConfig, build_item_atlas
from spritecore.item_playground import (
    DEFAULT_OUTPUT,
    DEFAULT_REPORT,
    ItemPlaygroundError,
    prepare_playground,
)


def _sheet() -> Image.Image:
    image = Image.new("RGBA", (128, 96), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 10, 34, 42), fill=(190, 55, 40, 255))
    draw.rectangle((82, 8, 118, 28), fill=(70, 135, 200, 255))
    draw.rectangle((50, 58, 72, 86), fill=(205, 170, 70, 255))
    draw.line((35, 17, 38, 17), fill=(190, 55, 40, 14), width=1)
    return image


def _run(tmp_path: Path, *, packing: PackingConfig | None = None) -> Path:
    source = tmp_path / "source.png"
    _sheet().save(source)
    root = tmp_path / "run"
    build_item_atlas(
        source,
        root,
        provenance="fixture",
        packing=packing or PackingConfig(quantum=16, padding=8),
    )
    return root


def _payload(html: str) -> dict:
    match = re.search(
        r'<script type="application/json" id="playground-data">(.*?)</script>',
        html,
        re.S,
    )
    assert match, "playground payload block is missing"
    return json.loads(match.group(1).replace("<\\/", "</"))


def _write(root: Path, result) -> tuple[Path, Path]:
    output_path, report_path, html_bytes, report = result
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(html_bytes)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return output_path, report_path


def test_playground_builds_self_contained_artifacts(tmp_path: Path) -> None:
    root = _run(tmp_path)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    output_path, report_path, html_bytes, report = prepare_playground(run_dir=root)
    assert output_path == root / DEFAULT_OUTPUT
    assert report_path == root / DEFAULT_REPORT
    html = html_bytes.decode("utf-8")
    assert "data:image/png;base64," in html
    payload = _payload(html)
    assert len(payload["items"]) == len(manifest["items"])
    assert payload["manifestSha256"] == report["manifest"]["sha256"]
    assert payload["stats"]["items"] == len(manifest["items"])
    assert report["kind"] == "item-playground"
    assert report["self_contained"] is True
    assert report["counts"]["items"] == len(manifest["items"])
    written_html, _ = _write(root, (output_path, report_path, html_bytes, report))
    assert written_html.is_file()


def test_playground_is_deterministic(tmp_path: Path) -> None:
    root = _run(tmp_path)
    first = prepare_playground(run_dir=root)
    second = prepare_playground(run_dir=root)
    assert first[2] == second[2]
    assert first[3]["input_fingerprint"] == second[3]["input_fingerprint"]
    assert first[3]["artifact"]["sha256"] == second[3]["artifact"]["sha256"]


def test_playground_supports_multiple_pages(tmp_path: Path) -> None:
    root = _run(tmp_path, packing=PackingConfig(quantum=16, padding=8, max_width=64, max_height=64))
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["pages"]) >= 2
    *_, html_bytes, report = prepare_playground(run_dir=root)
    payload = _payload(html_bytes.decode("utf-8"))
    assert len(payload["pages"]) == len(manifest["pages"])
    page_ids = {page["id"] for page in payload["pages"]}
    assert {item["pageId"] for item in payload["items"]} <= page_ids
    assert report["counts"]["pages"] == len(manifest["pages"])


def test_playground_requires_force_to_replace_outputs(tmp_path: Path) -> None:
    root = _run(tmp_path)
    result = prepare_playground(run_dir=root)
    _write(root, result)
    with pytest.raises(ItemPlaygroundError, match="already exists"):
        prepare_playground(run_dir=root)
    prepare_playground(run_dir=root, force=True)


def test_playground_rejects_outputs_outside_its_directory(tmp_path: Path) -> None:
    root = _run(tmp_path)
    with pytest.raises(ItemPlaygroundError, match="qa/item-playground/"):
        prepare_playground(run_dir=root, output_name="qa/other/index.html")


def test_playground_rejects_foreign_manifest(tmp_path: Path) -> None:
    root = tmp_path / "run"
    root.mkdir()
    (root / "manifest.json").write_text(json.dumps({"schemaVersion": "other"}), encoding="utf-8")
    with pytest.raises(ItemPlaygroundError, match="not a deterministic item atlas"):
        prepare_playground(run_dir=root)


def test_playground_rejects_missing_atlas_page(tmp_path: Path) -> None:
    root = _run(tmp_path)
    (root / "atlas.png").unlink()
    with pytest.raises(ItemPlaygroundError, match="atlas page does not exist"):
        prepare_playground(run_dir=root)
