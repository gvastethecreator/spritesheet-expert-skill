from __future__ import annotations

from io import BytesIO
from hashlib import sha256
import json
from pathlib import Path

from PIL import Image
import pytest

from spritecore.video_animation import (
    VideoAnimationError,
    VideoIngestResult,
    _compose_grid,
    _decode_selected,
    _merged_provenance,
    _video_sampling_mode,
    prepare_video_job,
    revalidate_prepared_sources,
    revalidate_video_sources,
    reviewed_sample_indices,
    uniform_sample_indices,
)


def _request() -> dict[str, object]:
    return {
        "version": 2,
        "kind": "sprite-gen-request",
        "asset_kind": "sprite",
        "frame_semantics": "animation",
        "extraction_mode": "components",
        "raw_layout_policy": "compact-body-grids",
        "cell": {"width": 32, "height": 32, "safe_margin": 2},
        "states": {
            "walk": {
                "frames": 5,
                "fps": 8,
                "loop": True,
                "action": "walk in place",
                "raw_layout": {
                    "kind": "compact-grid",
                    "columns": 3,
                    "rows": 2,
                    "order": "row-major",
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
        "generation_background": {
            "family": "neutral",
            "name": "gray",
            "hex": "#808080",
            "rgb": [128, 128, 128],
        },
    }


def test_compose_grid_allows_unused_capacity_and_leaves_it_transparent() -> None:
    frames = [Image.new("RGBA", (2, 2), (index * 30, 80, 120, 255)) for index in range(5)]

    encoded = _compose_grid(frames, 3, 2)

    with Image.open(BytesIO(encoded)) as grid:
        assert grid.size == (6, 4)
        assert grid.convert("RGBA").getpixel((5, 3)) == (0, 0, 0, 0)


def test_compose_grid_rejects_capacity_smaller_than_frame_count() -> None:
    frames = [Image.new("RGBA", (2, 2), (0, 0, 0, 255)) for _ in range(5)]

    with pytest.raises(VideoAnimationError, match="cannot hold"):
        _compose_grid(frames, 2, 2)


def test_bookended_sampling_includes_the_provider_closure_frame() -> None:
    assert uniform_sample_indices(
        8,
        4,
        sampling_mode="bookended-inclusive",
    ) == [0, 2, 5, 7]


def test_cyclic_sampling_stays_half_open_to_avoid_a_duplicate_contact() -> None:
    assert uniform_sample_indices(
        8,
        4,
        sampling_mode="cyclic-half-open",
    ) == [0, 2, 4, 6]


def test_reviewed_sampling_accepts_a_chronological_phase_selection() -> None:
    assert reviewed_sample_indices(145, 4, [0, 7, 14, 21]) == [0, 7, 14, 21]


@pytest.mark.parametrize(
    "indices, message",
    [
        ([1, 7, 14, 21], "start"),
        ([0, 7, 7, 21], "duplicate"),
        ([0, 14, 7, 21], "chronological"),
        ([0, 7, 14, 145], "inside"),
    ],
)
def test_reviewed_sampling_rejects_unverifiable_indices(
    indices: list[int], message: str
) -> None:
    with pytest.raises(VideoAnimationError, match=message):
        reviewed_sample_indices(145, 4, indices)


def test_character_wave_uses_bookended_sampling_not_a_cyclic_water_policy() -> None:
    assert _video_sampling_mode(
        "wave",
        {
            "loop": True,
            "action": "six-frame planted friendly hand wave loop",
        },
    ) == "bookended-inclusive"


def test_gesture_video_prompt_freezes_the_entire_lower_body(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    request = _request()
    request["states"] = {
        "wave": {
            "frames": 6,
            "fps": 6,
            "loop": True,
            "action": "planted friendly hand wave loop",
            "animation_workflows": ["gesture-loop"],
            "raw_layout": {
                "kind": "compact-grid",
                "columns": 3,
                "rows": 2,
                "order": "row-major",
                "delivery": "compose-runtime-row",
            },
        }
    }
    (run_dir / "sprite-request.json").write_text(
        json.dumps(request), encoding="utf-8"
    )
    Image.new("RGBA", (32, 32), (128, 128, 128, 255)).save(
        run_dir / "first-frame.png"
    )

    prepared = prepare_video_job(
        repo_root=tmp_path,
        run_dir=run_dir,
        state="wave",
        first_frame_name="first-frame.png",
    )
    prompt = prepared.prompt_text.lower()

    assert "pelvis, both legs, knees, ankles, both feet, and the contact footprint" in prompt
    assert "pixel-for-pixel fixed" in prompt
    assert "only the waving shoulder, arm, wrist, and hand" in prompt
    assert "do not add blush, cheek dots, new markings" in prompt


def test_sideview_locomotion_prompt_requires_opposite_support_legs(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    request = _request()
    request["states"]["walk"]["animation_workflows"] = ["sideview-locomotion"]
    (run_dir / "sprite-request.json").write_text(
        json.dumps(request), encoding="utf-8"
    )
    Image.new("RGBA", (32, 32), (128, 128, 128, 255)).save(
        run_dir / "first-frame.png"
    )

    prepared = prepare_video_job(
        repo_root=tmp_path,
        run_dir=run_dir,
        state="walk",
        first_frame_name="first-frame.png",
    )
    prompt = prepared.prompt_text.lower()

    assert "two unmistakably opposite anatomical contact phases" in prompt
    assert "same leg and foot must be visibly lifted" in prompt
    assert "other anatomical leg is extended forward and planted" in prompt
    assert "never repeat the same support limb" in prompt
    assert "without forward root travel or foot sliding" in prompt


def test_decode_selected_validates_unselected_second_pass_frames() -> None:
    class MalformedDecoder:
        @staticmethod
        def read_frames(_path: str, pix_fmt: str = "rgb24"):
            assert pix_fmt == "rgb24"
            yield {"size": (2, 2), "fps": 4.0}
            yield bytes((20, 30, 40)) * 4
            yield b"short"

    with pytest.raises(VideoAnimationError, match="malformed RGB frame on second pass"):
        _decode_selected(
            MalformedDecoder,
            Path("unused.mp4"),
            [0],
            (2, 2),
            2,
        )


def test_prepared_job_revalidation_detects_a_changed_request(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    request_path = run_dir / "sprite-request.json"
    request_path.write_text(json.dumps(_request()), encoding="utf-8")
    Image.new("RGBA", (32, 32), (128, 128, 128, 255)).save(
        run_dir / "first-frame.png"
    )
    prepared = prepare_video_job(
        repo_root=tmp_path,
        run_dir=run_dir,
        state="walk",
        first_frame_name="first-frame.png",
    )
    request_path.write_text(
        request_path.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )

    with pytest.raises(VideoAnimationError, match="changed before job commit"):
        revalidate_prepared_sources(prepared)


def _pending_ingest_result(tmp_path: Path) -> VideoIngestResult:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    local = {
        "sprite_request": run_dir / "sprite-request.json",
        "job": run_dir / "provider" / "job.json",
        "prompt": run_dir / "provider" / "prompt.txt",
        "first_frame": run_dir / "provider" / "first-frame.png",
    }
    external = {
        "invocation": tmp_path / "provider-output" / "invocation.json",
        "provider_result": tmp_path / "provider-output" / "result.json",
        "video": tmp_path / "provider-output" / "media" / "video-01.mp4",
    }
    for name, path in {**local, **external}.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"{name}-bytes".encode())
    report = {
        "sprite_request": {"path": "sprite-request.json"},
        "job": {"path": "provider/job.json"},
        "prompt": {"path": "provider/prompt.txt"},
        "first_frame": {"path": "provider/first-frame.png"},
        **{name: {"path": str(path)} for name, path in external.items()},
    }
    hashes = {
        name: sha256(path.read_bytes()).hexdigest()
        for name, path in {**local, **external}.items()
    }
    hashes["prior_provenance"] = "<absent>"
    return VideoIngestResult(
        run_dir=run_dir,
        raw_path=run_dir / "raw" / "walk.png",
        report_path=run_dir / "provider" / "video-source.json",
        provenance_path=run_dir / "source-provenance.json",
        raw_bytes=b"pending",
        report=report,
        provenance={},
        source_hashes=hashes,
        force=False,
    )


def test_video_source_revalidation_detects_provider_result_mutation(
    tmp_path: Path,
) -> None:
    result = _pending_ingest_result(tmp_path)
    revalidate_video_sources(result)
    Path(result.report["provider_result"]["path"]).write_bytes(b"changed")

    with pytest.raises(VideoAnimationError, match="sources changed"):
        revalidate_video_sources(result)


def test_video_source_revalidation_detects_provenance_appearing_before_commit(
    tmp_path: Path,
) -> None:
    result = _pending_ingest_result(tmp_path)
    result.provenance_path.write_text("{}", encoding="utf-8")

    with pytest.raises(VideoAnimationError, match="sources changed"):
        revalidate_video_sources(result)


def test_replacing_the_only_prior_state_does_not_leave_false_mixed_provenance(
    tmp_path: Path,
) -> None:
    prior = {
        "source_type": "imagegen-generated",
        "art_engine": "imagegen",
        "accepted_sources": [
            {
                "path": "raw/walk.png",
                "sha256": "0" * 64,
                "size_bytes": 1,
                "states": ["walk"],
                "source_type": "imagegen-generated",
                "art_engine": "imagegen",
            }
        ],
    }

    provenance = _merged_provenance(
        tmp_path,
        _request(),
        state="walk",
        raw_bytes=b"video-derived-grid",
        report_path=tmp_path / "provider" / "video-source.json",
        prior=prior,
        force=True,
    )

    assert provenance["source_type"] == "grok-imagine-video"
    assert provenance["art_engine"] == "grok-imagine"
    assert len(provenance["accepted_sources"]) == 1
