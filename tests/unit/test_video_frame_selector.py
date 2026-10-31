from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

from PIL import Image
import pytest

from build_video_frame_selector import (
    build_selector,
    selector_review_contract,
    thumbnail_data,
    write_timeline_pages,
)


def _write_request(run_dir: Path) -> None:
    request = {
        "creature_motion": {
            "anatomy": "multi-legged",
            "locomotion": "crawl",
            "movement_source": "alternating diagonal leg groups",
            "attack_source": "paired front claws",
        },
        "states": {
            "idle-step": {
                "animation_workflows": ["front-fps-creature-locomotion"]
            },
            "attack": {
                "animation_workflows": ["front-fps-creature-attack"]
            },
        },
    }
    (run_dir / "sprite-request.json").write_text(
        json.dumps(request), encoding="utf-8"
    )


def test_selector_labels_creature_type_and_locomotion_slots(tmp_path: Path) -> None:
    _write_request(tmp_path)

    contract = selector_review_contract(tmp_path, "idle-step", 4, [0, 2])

    assert contract["creatureType"] == "multi-legged / crawl"
    assert contract["motionSource"] == "alternating diagonal leg groups"
    assert contract["slotLabels"] == [
        "Exact idle",
        "Phase A",
        "Exact idle",
        "Phase B",
    ]
    assert len(contract["checks"]) == 5


def test_selector_labels_attack_intent_and_contact_slot(tmp_path: Path) -> None:
    _write_request(tmp_path)

    contract = selector_review_contract(tmp_path, "attack", 4, [0, 3])

    assert contract["motionSource"] == "paired front claws"
    assert contract["slotLabels"] == [
        "Exact idle",
        "Anticipation",
        "Contact",
        "Exact idle",
    ]


def test_selector_writes_exhaustive_timeline_pages(tmp_path: Path) -> None:
    history = tmp_path / "timeline-page-99.png"
    history.write_bytes(b"historical review")
    thumbnails = [
        thumbnail_data(Image.new("RGB", (32, 32), (index, 0, 0)), index, index / 24)
        for index in range(26)
    ]

    result = write_timeline_pages(tmp_path, thumbnails, 24.0)

    manifest = json.loads((tmp_path / "timeline-pages.json").read_text(encoding="utf-8"))
    assert [page["path"] for page in result["pages"]] == [
        "timeline-page-01.png",
        "timeline-page-02.png",
    ]
    assert manifest["frame_count"] == 26
    assert manifest["pages"][0]["first"] == 0
    assert manifest["pages"][0]["last"] == 24
    assert manifest["pages"][1]["first"] == 25
    assert manifest["pages"][1]["last"] == 25
    assert history.read_bytes() == b"historical review"
    assert all(page["path"] != history.name for page in manifest["pages"])
    empty = tmp_path / "empty"
    with pytest.raises(ValueError, match="requires frames"):
        write_timeline_pages(empty, [], 24.0)
    assert not empty.exists()


def test_selector_preserves_sources_before_writing(tmp_path: Path, monkeypatch) -> None:
    _write_request(tmp_path)
    request = tmp_path / "sprite-request.json"
    video = tmp_path / "source.mp4"
    video.write_bytes(b"source video")
    output_dir = tmp_path / "qa" / "idle-step-video-frame-selector"
    output_dir.mkdir(parents=True)
    report_path = output_dir / "selector.evidence.json"
    report = {
        "kind": "sprite-video-source", "status": "pass", "state": "idle-step",
        "sprite_request": {"path": request.name, "sha256": sha256(request.read_bytes()).hexdigest()},
        "video": {"path": video.name, "sha256": sha256(video.read_bytes()).hexdigest()},
        "decoded": {"width": 32, "height": 32, "fps": 12.0, "frame_count": 2},
        "sampled_video_indices": [0, 1], "exact_idle_slots": [0],
        "exact_first_frame_preserved": False,
    }
    report_bytes = json.dumps(report).encode()
    report_path.write_bytes(report_bytes)
    thumbnail = thumbnail_data(Image.new("RGB", (32, 32), "black"), 0, 0)
    def decode(_path):
        return [thumbnail, thumbnail], 12.0, (32, 32)
    monkeypatch.setattr("build_video_frame_selector.decode_thumbnails", decode)
    with pytest.raises(ValueError, match="cannot overwrite sources"):
        build_selector(run_dir=tmp_path, state="idle-step", source_report=report_path, force=True)
    assert report_path.read_bytes() == report_bytes
    assert not (output_dir / "index.html").exists()

    source_report = tmp_path / "video-source.json"
    source_report.write_bytes(report_bytes)
    def changing_decode(path):
        request.write_bytes(request.read_bytes() + b"\n")
        return decode(path)
    monkeypatch.setattr("build_video_frame_selector.decode_thumbnails", changing_decode)
    with pytest.raises(ValueError, match="sources changed before commit"):
        build_selector(run_dir=tmp_path, state="idle-step", source_report=source_report, force=True)
    assert not (output_dir / "index.html").exists()
