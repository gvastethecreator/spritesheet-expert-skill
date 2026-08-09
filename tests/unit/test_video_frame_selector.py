from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from build_video_frame_selector import (
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
        "Idle exacto",
        "Fase A",
        "Idle exacto",
        "Fase B",
    ]
    assert len(contract["checks"]) == 5


def test_selector_labels_attack_intent_and_contact_slot(tmp_path: Path) -> None:
    _write_request(tmp_path)

    contract = selector_review_contract(tmp_path, "attack", 4, [0, 3])

    assert contract["motionSource"] == "paired front claws"
    assert contract["slotLabels"] == [
        "Idle exacto",
        "Anticipación",
        "Contacto",
        "Idle exacto",
    ]


def test_selector_writes_exhaustive_timeline_pages(tmp_path: Path) -> None:
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
