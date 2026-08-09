from __future__ import annotations

from io import BytesIO
from hashlib import sha256
import json
from pathlib import Path

from PIL import Image
import pytest

from spritecore.video_animation import (
    _exact_idle_slots_for_state,
    VideoAnimationError,
    VideoIngestResult,
    _frame_signature,
    adaptive_sample_indices,
    _compose_grid,
    _decode_selected,
    _merged_provenance,
    _video_sampling_mode,
    prepare_video_job,
    revalidate_prepared_sources,
    revalidate_video_sources,
    reviewed_selection_metrics,
    reviewed_sample_indices,
    uniform_sample_indices,
    validate_reviewed_locomotion_scale,
)


def test_shared_idle_slots_follow_move_and_attack_semantics() -> None:
    request = {
        "creature_motion": {"shared_idle": True},
        "states": {
            "idle-step": {"animation_workflows": ["front-fps-creature-locomotion"]},
            "attack": {"animation_workflows": ["front-fps-creature-attack"]},
        },
    }
    assert _exact_idle_slots_for_state(request, "idle-step", 4) == [0, 2]
    assert _exact_idle_slots_for_state(request, "attack", 4) == [0, 3]


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


def test_reviewed_locomotion_rejects_subject_scale_growth_before_extraction() -> None:
    def subject(height: int) -> Image.Image:
        image = Image.new("RGB", (64, 64), "black")
        for y in range(32 - height // 2, 32 + height // 2):
            for x in range(26, 38):
                image.putpixel((x, y), (180, 110, 70))
        return image

    exact = _frame_signature(subject(30))
    signatures = [
        exact,
        _frame_signature(subject(32)),
        exact,
        _frame_signature(subject(46)),
    ]
    request = {
        "states": {
            "idle-step": {
                "animation_workflows": ["front-fps-creature-locomotion"]
            }
        }
    }

    with pytest.raises(VideoAnimationError, match="before background removal"):
        validate_reviewed_locomotion_scale(
            request,
            "idle-step",
            signatures,
            [0, 1, 2, 3],
            exact,
            [0, 2],
        )


def test_reviewed_locomotion_accepts_wing_span_change_when_core_scale_is_fixed() -> None:
    def winged(wing_top: int, wing_bottom: int) -> Image.Image:
        image = Image.new("RGB", (64, 64), "black")
        for y in range(20, 45):
            for x in range(27, 38):
                image.putpixel((x, y), (170, 90, 130))
        for y in range(wing_top, wing_bottom):
            for x in list(range(5, 20)) + list(range(45, 60)):
                image.putpixel((x, y), (120, 70, 110))
        return image

    exact = _frame_signature(winged(25, 40))
    signatures = [
        exact,
        _frame_signature(winged(8, 55)),
        exact,
        _frame_signature(winged(14, 50)),
    ]
    request = {
        "states": {
            "idle-step": {
                "animation_workflows": ["front-fps-creature-locomotion"]
            }
        }
    }

    validate_reviewed_locomotion_scale(
        request,
        "idle-step",
        signatures,
        [0, 1, 2, 3],
        exact,
        [0, 2],
    )


def test_reviewed_selection_metrics_describe_reviewed_not_auto_indices() -> None:
    def subject(height: int) -> Image.Image:
        image = Image.new("RGB", (64, 64), "black")
        for y in range(32 - height // 2, 32 + height // 2):
            for x in range(26, 38):
                image.putpixel((x, y), (180, 110, 70))
        return image

    signatures = [_frame_signature(subject(height)) for height in (30, 31, 32, 33)]
    metrics = reviewed_selection_metrics(
        signatures,
        [0, 1, 2, 3],
        signatures[0],
        {"candidate_sets": [{"indices": [0, 3, 2, 1]}]},
    )

    assert metrics["reviewed_indices"] == [0, 1, 2, 3]
    assert metrics["candidate_sets"][0]["indices"] == [0, 3, 2, 1]
    assert metrics["reviewed_selection"]["bbox_height_ratio_vs_first_frame"][-1] > 1


def test_adaptive_sampling_finds_pose_extremes_and_idle_recovery() -> None:
    def pose(offset: int) -> Image.Image:
        image = Image.new("RGB", (32, 32), "black")
        for y in range(10, 25):
            for x in range(10 + offset, 22 + offset):
                image.putpixel((x, y), (180, 90, 40))
        return image

    frames = (
        [pose(0)] * 3
        + [pose(-1), pose(-3), pose(-5), pose(-3), pose(-1)]
        + [pose(0)] * 3
        + [pose(1), pose(3), pose(5), pose(3), pose(1)]
        + [pose(0)] * 3
    )
    indices, metrics = adaptive_sample_indices(
        [_frame_signature(frame) for frame in frames], 4
    )

    assert indices[0] == 0
    assert indices[1] in {4, 5, 6}
    assert indices[2] in {8, 9, 10}
    assert indices[3] in {12, 13, 14}
    assert metrics["method"] == "adaptive-pose-v1"
    assert metrics["phase_a_to_phase_b_distance"] > 0
    assert len(metrics["candidate_sets"]) >= 2
    assert metrics["candidate_sets"][0]["indices"] == indices


def test_adaptive_sampling_supports_non_four_frame_workflows() -> None:
    frames = []
    for index in range(36):
        image = Image.new("RGB", (32, 32), "black")
        offset = round(5 * __import__("math").sin(index / 36 * 6.283185))
        for y in range(9, 25):
            for x in range(10 + offset, 22 + offset):
                image.putpixel((x, y), (160, 100, 60))
        frames.append(image)

    indices, metrics = adaptive_sample_indices(
        [_frame_signature(frame) for frame in frames],
        6,
        sampling_mode="cyclic-half-open",
    )

    assert len(indices) == 6
    assert indices[0] == 0
    assert indices == sorted(set(indices))
    assert metrics["method"] == "adaptive-sequence-v1"
    assert len(metrics["candidate_sets"]) >= 2


def test_adaptive_sampling_ranks_source_edge_contact_below_safe_poses() -> None:
    frames = []
    for index in range(30):
        image = Image.new("RGB", (32, 32), "black")
        offset = round(6 * __import__("math").sin(index / 30 * 12.56637))
        left = 10 + offset
        right = 22 + offset
        if index in {5, 13, 21}:
            left, right = (0, 12) if index != 13 else (20, 32)
        for y in range(9, 25):
            for x in range(left, right):
                image.putpixel((x, y), (180, 90, 40))
        frames.append(image)

    signatures = [_frame_signature(frame) for frame in frames]
    indices, metrics = adaptive_sample_indices(signatures, 4)

    assert set(metrics["source_edge_contact_frames"]) == {5, 13, 21}
    assert all(signatures[index].source_edge_foreground_ratio == 0 for index in indices)
    assert metrics["candidate_sets"][0]["source_edge_contact_frames"] == []


def test_locomotion_sampling_marks_and_ranks_scale_drift_below_stable_poses() -> None:
    def pose(height: int, offset: int) -> Image.Image:
        image = Image.new("RGB", (64, 64), "black")
        top = 32 - height // 2
        bottom = top + height
        for y in range(top, bottom):
            for x in range(24 + offset, 40 + offset):
                image.putpixel((x, y), (180, 90, 40))
        return image

    frames = []
    for index in range(36):
        offset = round(5 * __import__("math").sin(index / 36 * 12.56637))
        height = 30 if index < 28 else 42
        frames.append(pose(height, offset))

    signatures = [_frame_signature(frame) for frame in frames]
    indices, metrics = adaptive_sample_indices(
        signatures, 4, enforce_scale_stability=True
    )

    assert set(range(28, 36)).issubset(metrics["scale_unstable_frames"])
    assert all(index < 28 for index in (indices[1], indices[3]))
    assert metrics["candidate_sets"][0]["scale_unstable_frames"] == []


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


def test_front_fps_creature_prompt_uses_declared_anatomy_not_biped_mirroring(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    request = _request()
    request["creature_motion"] = {
        "anatomy": "multi-legged",
        "locomotion": "crawl",
        "camera": "front-fps",
        "registration_anchor": "body-bottom",
        "shared_idle": True,
        "movement_source": "alternating diagonal groups across all eight legs",
        "attack_source": "paired front claws",
    }
    request["states"]["walk"]["animation_workflows"] = [
        "front-fps-creature-locomotion"
    ]
    request["states"]["walk"]["video_prompt"] = {
        "motion_window_seconds": 1.6,
        "edge_margin_ratio": 0.15,
        "motion_plane": "image-plane",
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
        state="walk",
        first_frame_name="first-frame.png",
    )
    prompt = prepared.prompt_text.lower()

    assert "full-frontal fps view" in prompt
    assert "creature's declared anatomy" in prompt
    assert "invoke image_to_video exactly once" in prompt
    assert "do not generate alternatives" in prompt
    assert "generic biped mirror" in prompt
    assert "exact supplied idle anchor" in prompt
    assert "subject type: multi-legged creature" in prompt
    assert "alternating diagonal groups across all eight legs" in prompt
    assert "within the first 1.6 seconds" in prompt
    assert "toward the player' as pose readability only" in prompt
    assert "clean articulated pose changes only" in prompt
    assert "moving hands, feet, jaws, wings, claws, or tendrils" in prompt
    assert "locomotion is in place" in prompt
    assert "no mirror-flip substitute" in prompt
    assert "hold each useful phase as a sharp recognizable pose" in prompt
    assert prepared.job["prompt_contract"]["phase_semantics"] == [
        "exact-idle",
        "phase-a",
        "exact-idle",
        "phase-b",
    ]
    assert prepared.job["prompt_contract"]["pose_transition_policy"] == (
        "articulated-pose-only"
    )
    assert prepared.job["prompt_contract"]["root_policy"] == (
        "stationary-image-plane-anchor"
    )


def test_front_fps_attack_prompt_uses_declared_attack_anatomy_and_flat_depth(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    request = _request()
    request["creature_motion"] = {
        "anatomy": "quadruped",
        "locomotion": "crawl",
        "camera": "front-fps",
        "registration_anchor": "body-bottom",
        "shared_idle": True,
        "movement_source": "alternating diagonal supports",
        "attack_source": "both foreclaws and the exact mouth",
    }
    request["states"] = {
        "attack": {
            "frames": 4,
            "fps": 10,
            "loop": False,
            "action": "strike toward the player",
            "animation_workflows": ["front-fps-creature-attack"],
            "raw_layout": {
                "kind": "compact-grid",
                "columns": 2,
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
        state="attack",
        first_frame_name="first-frame.png",
    )
    prompt = prepared.prompt_text.lower()

    assert "only motion driver: both foreclaws and the exact mouth" in prompt
    assert "compact anticipation, clear threatening contact" in prompt
    assert "no depth translation, foreshortening" in prompt
    assert prepared.job["prompt_contract"]["phase_semantics"] == [
        "exact-idle",
        "anticipation",
        "contact",
        "exact-idle",
    ]


def test_front_fps_video_prompt_rejects_missing_motion_source(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    request = _request()
    request["creature_motion"] = {
        "anatomy": "quadruped",
        "locomotion": "crawl",
        "camera": "front-fps",
        "registration_anchor": "body-bottom",
        "shared_idle": True,
    }
    request["states"]["walk"]["animation_workflows"] = [
        "front-fps-creature-locomotion"
    ]
    (run_dir / "sprite-request.json").write_text(
        json.dumps(request), encoding="utf-8"
    )
    Image.new("RGBA", (32, 32), (128, 128, 128, 255)).save(
        run_dir / "first-frame.png"
    )

    with pytest.raises(VideoAnimationError, match="movement_source"):
        prepare_video_job(
            repo_root=tmp_path,
            run_dir=run_dir,
            state="walk",
            first_frame_name="first-frame.png",
        )


def test_provider_action_override_is_state_local_and_auditable(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    request = _request()
    request_bytes = json.dumps(request).encode("utf-8")
    (run_dir / "sprite-request.json").write_bytes(request_bytes)
    Image.new("RGBA", (32, 32), (128, 128, 128, 255)).save(
        run_dir / "first-frame.png"
    )

    prepared = prepare_video_job(
        repo_root=tmp_path,
        run_dir=run_dir,
        state="walk",
        first_frame_name="first-frame.png",
        provider_action_override="one stricter state-local walk cycle",
    )

    assert "one stricter state-local walk cycle" in prepared.prompt_text
    assert prepared.job["prompt_contract"]["provider_action_source"] == "cli-override"
    assert prepared.job["prompt_contract"]["provider_action"] == (
        "one stricter state-local walk cycle"
    )
    assert prepared.job["sprite_request"]["sha256"] == sha256(request_bytes).hexdigest()


def test_faceless_creature_prompt_keeps_declared_anatomy_and_forbids_a_face(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    request = _request()
    request["creature_motion"] = {
        "anatomy": "hovering",
        "locomotion": "hover",
        "camera": "front-fps",
        "registration_anchor": "center",
        "shared_idle": True,
        "preserve": ["two crescent skeletal forearms", "orange rib-cage core"],
        "reject": ["invented mouth", "turning the core into a face", "extra arms"],
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
        state="walk",
        first_frame_name="first-frame.png",
    )
    prompt = prepared.prompt_text.lower()

    assert "keep the head exactly faceless" in prompt
    assert "do not create eyes, a mouth, teeth" in prompt
    assert "preserve exactly: two crescent skeletal forearms" in prompt
    assert "never produce: invented mouth" in prompt


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
