from __future__ import annotations

from PIL import Image

from check_asset_slots import self_repeat_metrics
from repair_repeat_edges import (
    harmonize_repeat_edges,
    merge_provider_provenance,
    periodic_phase_crop,
)


def test_repeat_edge_repair_matches_edges_and_preserves_center() -> None:
    source = Image.new("RGBA", (32, 32), (60, 100, 40, 255))
    for y in range(32):
        for x in range(32):
            source.putpixel((x, y), (20 + x * 6, 60 + y * 3, 40, 255))
    center_before = source.crop((6, 6, 26, 26)).tobytes()

    repaired = harmonize_repeat_edges(source, blend_width=6, edge_strip=2)

    metrics = self_repeat_metrics(repaired, 2)
    assert metrics["horizontal_edge_error"] == 0.0
    assert metrics["vertical_edge_error"] == 0.0
    assert repaired.crop((6, 6, 26, 26)).tobytes() == center_before


def test_phase_crop_finds_matching_periodic_boundaries_before_narrow_blend() -> None:
    source = Image.new("RGBA", (150, 146), (0, 0, 0, 255))
    for y in range(source.height):
        for x in range(source.width):
            grout = x % 12 < 2 or y % 10 < 2
            value = 30 if grout else 190 + ((x // 12 + y // 10) % 2) * 20
            source.putpixel((x, y), (value, value, value, 255))
    raw = self_repeat_metrics(source.resize((64, 64), Image.Resampling.LANCZOS), 2)

    normalized, report = periodic_phase_crop(source, output_size=(64, 64))
    repaired = harmonize_repeat_edges(normalized, blend_width=4, edge_strip=2)
    final = self_repeat_metrics(repaired, 2)

    assert report["x"]["trim_ratio"] > 0
    assert report["y"]["trim_ratio"] > 0
    assert report["x"]["span"] % 12 == 0
    assert report["y"]["span"] % 10 == 0
    assert report["x"]["boundary_error"] == 0
    assert report["y"]["boundary_error"] == 0
    assert final["horizontal_edge_error"] < 0.02
    assert final["vertical_edge_error"] < 0.02


def test_provider_retry_merge_keeps_concrete_per_source_metadata() -> None:
    provenance = {
        "version": 2,
        "kind": "sprite-source-provenance",
        "source_type": "grok-imagine-video",
        "art_engine": "grok-imagine",
        "fixture": False,
        "verification_status": "verified",
        "accepted_sources": [
            {
                "path": "provider/video.mp4",
                "sha256": "a" * 64,
                "size_bytes": 10,
                "states": ["tiles"],
            }
        ],
        "state_coverage": ["tiles"],
    }
    request = {
        "version": 2,
        "kind": "sprite-gen-request",
        "asset_kind": "tileset",
        "frame_semantics": "tiles",
        "extraction_mode": "slots",
        "raw_layout_policy": "compact-body-grids",
        "source_type": "grok-imagine-video",
        "cell": {"width": 32, "height": 32},
        "states": {
            "tiles": {
                "frames": 1,
                "fps": 1,
                "raw_layout": {
                    "kind": "strip",
                    "columns": 1,
                    "rows": 1,
                    "order": "left-to-right",
                    "delivery": "compose-runtime-row",
                },
            }
        },
        "sampling_policy": {
            "filter": "nearest",
            "wrap": "clamp-to-edge",
            "mipmaps": False,
            "pixel_snap": True,
        },
    }
    addition = {
        "path": "provider/retry.png",
        "sha256": "b" * 64,
        "size_bytes": 20,
        "states": ["tiles"],
        "source_type": "imagegen",
        "art_engine": "imagegen",
    }

    merged, updated_request = merge_provider_provenance(
        provenance, request, [addition], provider="imagegen"
    )

    assert merged["source_type"] == "mixed"
    assert merged["art_engine"] == "mixed"
    assert updated_request["source_type"] == "mixed"
    assert merged["accepted_sources"][0]["source_type"] == "grok-imagine-video"
    assert merged["accepted_sources"][0]["art_engine"] == "grok-imagine"
    assert merged["accepted_sources"][1]["source_type"] == "imagegen"
    assert all(
        item.get("source_type") != "mixed" for item in merged["accepted_sources"]
    )


def test_provider_retry_merge_deduplicates_provenance_note_and_source() -> None:
    source = {
        "path": "provider/retry.png",
        "sha256": "c" * 64,
        "size_bytes": 20,
        "states": ["tiles"],
        "source_type": "imagegen",
        "art_engine": "imagegen",
    }
    provenance = {
        "version": 2,
        "kind": "sprite-source-provenance",
        "source_type": "imagegen",
        "art_engine": "imagegen",
        "fixture": False,
        "verification_status": "verified",
        "accepted_sources": [source.copy()],
        "state_coverage": ["tiles"],
        "notes": (
            "accepted; provider slot retries normalized by periodic phase crop; "
            "provider slot retries normalized by periodic phase crop"
        ),
    }
    request = {
        "version": 2,
        "kind": "sprite-gen-request",
        "asset_kind": "texture",
        "frame_semantics": "seamless-textures",
        "extraction_mode": "slots",
        "raw_layout_policy": "compact-body-grids",
        "cell": {"width": 32, "height": 32},
        "states": {
            "tiles": {
                "frames": 1,
                "fps": 1,
                "raw_layout": {
                    "kind": "strip",
                    "columns": 1,
                    "rows": 1,
                    "order": "left-to-right",
                    "delivery": "compose-runtime-row",
                },
            }
        },
        "sampling_policy": {
            "filter": "linear",
            "wrap": "repeat",
            "mipmaps": False,
            "pixel_snap": False,
        },
    }

    merged, _ = merge_provider_provenance(
        provenance, request, [source], provider="imagegen"
    )

    assert len(merged["accepted_sources"]) == 1
    assert merged["notes"].count("periodic phase crop") == 1
