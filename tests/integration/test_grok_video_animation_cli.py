from __future__ import annotations

from hashlib import sha256
import json
import os
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw
import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "SKILLS" / "spritesheet-expert" / "scripts"
PREPARE = SCRIPTS / "prepare_grok_video_animation.py"
INGEST = SCRIPTS / "ingest_grok_video_animation.py"


def _request() -> dict[str, object]:
    return {
        "version": 2,
        "kind": "sprite-gen-request",
        "asset_kind": "sprite",
        "frame_semantics": "animation",
        "extraction_mode": "components",
        "raw_layout_policy": "compact-body-grids",
        "character": {
            "id": "grok-video-test",
            "description": "provider-free decoder integration fixture",
            "base_image": None,
        },
        "cell": {
            "shape": "square",
            "width": 32,
            "height": 32,
            "safe_margin": 2,
            "safe_margin_x": 2,
            "safe_margin_y": 2,
        },
        "chroma_key": {
            "name": "legacy-magenta",
            "hex": "#FF00FF",
            "rgb": [255, 0, 255],
        },
        "states": {
            "walk": {
                "frames": 4,
                "fps": 8,
                "loop": True,
                "action": "one complete walk cycle in place",
                "raw_layout": {
                    "kind": "strip",
                    "columns": 4,
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
        "generation_background": {
            "family": "neutral",
            "name": "gray",
            "hex": "#808080",
            "rgb": [128, 128, 128],
        },
        "background_removal": {
            "method": "auto",
            "model": "birefnet-general",
            "device": "auto",
            "alpha_matting": True,
            "post_rembg_chroma_cleanup": False,
            "source_family": "neutral",
        },
    }


def _prepare_job(
    repo_root: Path, *, neutral_subject: bool = False
) -> tuple[Path, Path, dict[str, object]]:
    run_dir = repo_root / "run"
    run_dir.mkdir(parents=True)
    (run_dir / "sprite-request.json").write_text(json.dumps(_request()), encoding="utf-8")
    first_frame = run_dir / "first-frame.png"
    if neutral_subject:
        _video_fixture_frame(0).convert("RGBA").save(first_frame)
    else:
        Image.new("RGBA", (8, 8), (240, 190, 45, 255)).save(first_frame)
    completed = subprocess.run(
        [
            sys.executable,
            str(PREPARE),
            "--repo-root",
            str(repo_root),
            "--run-dir",
            str(run_dir),
            "--state",
            "walk",
            "--first-frame",
            "first-frame.png",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    response = json.loads(completed.stdout)
    job_path = run_dir / response["job_path"]
    return run_dir, first_frame, json.loads(job_path.read_text(encoding="utf-8"))


def test_prepare_grok_video_job_is_dry_run_first_and_hashes_the_exact_frame(
    tmp_path: Path,
) -> None:
    run_dir, first_frame, job = _prepare_job(tmp_path)

    prompt_path = run_dir / str(job["prompt"]["path"])
    prompt = prompt_path.read_text(encoding="utf-8").lower()
    assert job["provider"] == "grok-imagine"
    assert job["operation"] == "video-from-image"
    assert job["requested_frames"] == 4
    assert job["sampling_mode"] == "cyclic-half-open"
    assert job["first_frame"]["sha256"] == sha256(first_frame.read_bytes()).hexdigest()
    assert job["sprite_request"]["sha256"] == sha256(
        (run_dir / "sprite-request.json").read_bytes()
    ).hexdigest()
    assert job["dry_run"]["args"][-1] == "--dry-run"
    assert "--ack-run" not in job["dry_run"]["args"]
    assert "locked camera" in prompt
    assert "flat neutral gray" in prompt
    assert "one continuous" in prompt
    assert "no cuts" in prompt
    assert job["prompt"]["sha256"][:10] in job["provider_output"]["result_path"]


def _write_fake_decoder(module_root: Path) -> None:
    module_root.mkdir()
    (module_root / "imageio_ffmpeg.py").write_text(
        """
__version__ = "0.test"

def read_frames(_path, pix_fmt="rgb24"):
    assert pix_fmt == "rgb24"
    yield {"size": (8, 8), "fps": 4.0, "duration": 2.0}
    for index in range(8):
        yield bytes((index * 20, 10, 5)) * 64
""".lstrip(),
        encoding="utf-8",
    )


def _run_sprite_script(name: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / name), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _video_fixture_frame(index: int) -> Image.Image:
    image = Image.new("RGB", (32, 32), (128, 128, 128))
    draw = ImageDraw.Draw(image)
    phase = (index // 2) % 4
    body_y = 11 + (phase % 2)
    draw.ellipse((12, body_y - 7, 19, body_y), fill=(242, 194, 124))
    draw.rectangle((12, body_y, 19, body_y + 11), fill=(42, 112, 224))
    leg_ends = [
        ((6, 29), (21, 25)),
        ((10, 29), (20, 28)),
        ((10, 25), (25, 29)),
        ((11, 28), (22, 29)),
    ][phase]
    arm_ends = [
        ((10, body_y + 10), (21, body_y + 8)),
        ((10, body_y + 9), (21, body_y + 10)),
        ((21, body_y + 10), (10, body_y + 8)),
        ((21, body_y + 9), (10, body_y + 10)),
    ][phase]
    leg_widths = [(4, 2), (3, 3), (2, 4), (3, 3)][phase]
    draw.line(
        (13, body_y + 10, *leg_ends[0]),
        fill=(20, 52, 136),
        width=leg_widths[0],
    )
    draw.line(
        (18, body_y + 10, *leg_ends[1]),
        fill=(20, 52, 136),
        width=leg_widths[1],
    )
    draw.line((12, body_y + 3, *arm_ends[0]), fill=(242, 194, 124), width=2)
    draw.line((19, body_y + 3, *arm_ends[1]), fill=(242, 194, 124), width=2)
    return image


def test_ingest_accepts_only_completed_provider_media_and_writes_a_deterministic_raw_grid(
    tmp_path: Path,
) -> None:
    run_dir, first_frame, job = _prepare_job(tmp_path)
    result_path = tmp_path / str(job["provider_output"]["result_path"])
    result_path.parent.mkdir(parents=True)
    result_path.write_text("{}", encoding="utf-8")
    video_path = result_path.parent / "media" / "video-01.mp4"
    video_path.parent.mkdir()
    video_path.write_bytes(b"fake-video-for-decoder-seam")
    invocation_path = result_path.parent / "invocation.json"
    prompt_path = run_dir / str(job["prompt"]["path"])
    invocation = {
        "provider": "grok-imagine",
        "mode": "video-from-image",
        "cwd": str(tmp_path.resolve()),
        "promptFile": str(prompt_path.resolve()),
        "status": "completed",
        "exitCode": 0,
        "enforcement": {
            "operation": "video-from-image",
            "sourceFiles": [str(first_frame.resolve())],
            "expectedImages": 0,
            "expectedVideos": 1,
        },
        "resultValidation": {
            "ok": True,
            "images": [],
            "videos": [str(video_path.resolve())],
        },
    }
    invocation_path.write_text(json.dumps(invocation), encoding="utf-8")
    fake_modules = tmp_path / "fake-modules"
    _write_fake_decoder(fake_modules)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(fake_modules) + os.pathsep + env.get("PYTHONPATH", "")

    completed = subprocess.run(
        [
            sys.executable,
            str(INGEST),
            "--run-dir",
            str(run_dir),
            "--state",
            "walk",
            "--invocation",
            str(invocation_path),
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    response = json.loads(completed.stdout)
    raw_path = run_dir / "raw" / "walk.png"
    with Image.open(raw_path) as raw:
        assert raw.size == (32, 8)
        assert raw.getpixel((0, 0)) == (240, 190, 45, 255)
        assert raw.getpixel((8, 0)) == (40, 10, 5, 255)
    report = json.loads((run_dir / response["report_path"]).read_text(encoding="utf-8"))
    assert report["sampled_video_indices"] == [0, 2, 4, 6]
    assert report["sampling_mode"] == "cyclic-half-open"
    assert report["exact_first_frame_preserved"] is True
    assert report["decoder"] == {"name": "imageio-ffmpeg", "version": "0.test"}
    assert report["video"]["sha256"] == sha256(video_path.read_bytes()).hexdigest()
    assert report["sprite_request"]["sha256"] == sha256(
        (run_dir / "sprite-request.json").read_bytes()
    ).hexdigest()
    assert report["prompt"]["sha256"] == sha256(prompt_path.read_bytes()).hexdigest()
    assert report["provider_result"]["sha256"] == sha256(
        result_path.read_bytes()
    ).hexdigest()
    provenance = json.loads((run_dir / "source-provenance.json").read_text(encoding="utf-8"))
    assert provenance["source_type"] == "grok-imagine-video"
    assert provenance["art_engine"] == "grok-imagine"
    assert provenance["state_coverage"] == ["walk"]
    assert provenance["accepted_sources"][0]["sha256"] == sha256(raw_path.read_bytes()).hexdigest()


def test_ingest_decodes_a_real_mp4_with_the_optional_imageio_ffmpeg_runtime(
    tmp_path: Path,
) -> None:
    imageio_ffmpeg = pytest.importorskip("imageio_ffmpeg")
    run_dir, first_frame, job = _prepare_job(tmp_path, neutral_subject=True)
    result_path = tmp_path / str(job["provider_output"]["result_path"])
    result_path.parent.mkdir(parents=True)
    result_path.write_text("{}", encoding="utf-8")
    video_path = result_path.parent / "media" / "video-01.mp4"
    video_path.parent.mkdir()
    writer = imageio_ffmpeg.write_frames(
        str(video_path),
        (32, 32),
        fps=8,
        codec="libx264",
        quality=8,
        macro_block_size=16,
    )
    writer.send(None)
    try:
        for index in range(8):
            frame = _video_fixture_frame(index)
            writer.send(frame.tobytes())
    finally:
        writer.close()
    assert video_path.stat().st_size > 0

    prompt_path = run_dir / str(job["prompt"]["path"])
    invocation_path = result_path.parent / "invocation.json"
    invocation_path.write_text(
        json.dumps(
            {
                "provider": "grok-imagine",
                "mode": "video-from-image",
                "cwd": str(tmp_path.resolve()),
                "promptFile": str(prompt_path.resolve()),
                "status": "completed",
                "exitCode": 0,
                "enforcement": {
                    "operation": "video-from-image",
                    "sourceFiles": [str(first_frame.resolve())],
                    "expectedImages": 0,
                    "expectedVideos": 1,
                },
                "resultValidation": {
                    "ok": True,
                    "images": [],
                    "videos": [str(video_path.resolve())],
                },
            }
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(INGEST),
            "--run-dir",
            str(run_dir),
            "--state",
            "walk",
            "--invocation",
            str(invocation_path),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    response = json.loads(completed.stdout)
    with Image.open(run_dir / "raw" / "walk.png") as raw:
        assert raw.size == (128, 32)
        with Image.open(first_frame) as accepted_first_frame:
            assert raw.crop((0, 0, 32, 32)).tobytes() == accepted_first_frame.convert(
                "RGBA"
            ).tobytes()
    report = json.loads(
        (run_dir / response["report_path"]).read_text(encoding="utf-8")
    )
    assert report["decoded"]["frame_count"] == 8
    assert report["sampled_video_indices"] == [0, 2, 4, 6]
    assert report["sampling_mode"] == "cyclic-half-open"
    assert report["exact_first_frame_preserved"] is True
    assert report["decoder"]["version"] == "0.6.0"

    for script, extra in (
        ("check_generation_provenance.py", ()),
        ("extract_sprite_row_frames.py", ("--min-used-pixels", "8")),
        ("compose_sprite_atlas.py", ("--min-used-pixels", "8")),
        ("preview_animation.py", ()),
        ("check_frame_alignment.py", ()),
        ("check_identity_consistency.py", ()),
        ("check_animation_contracts.py", ()),
        (
            "render_runtime_preview.py",
            ("--state", "walk", "--kind", "runtime-playback"),
        ),
        ("build_preview_workbench.py", ()),
    ):
        pipeline = _run_sprite_script(script, "--run-dir", str(run_dir), *extra)
        assert pipeline.returncode == 0, (
            f"{script} failed\n{pipeline.stdout}\n{pipeline.stderr}"
        )
    assert (run_dir / "sprite-sheet-alpha.png").is_file()
    assert (run_dir / "manifest.json").is_file()
    assert (run_dir / "qa" / "preview-workbench" / "index.html").is_file()


def test_ingest_rejects_a_failed_invocation_without_mutating_raw(tmp_path: Path) -> None:
    run_dir, _first_frame, job = _prepare_job(tmp_path)
    result_path = tmp_path / str(job["provider_output"]["result_path"])
    result_path.parent.mkdir(parents=True)
    invocation_path = result_path.parent / "invocation.json"
    invocation_path.write_text(
        json.dumps(
            {
                "provider": "grok-imagine",
                "mode": "video-from-image",
                "status": "failed",
                "exitCode": 1,
                "resultValidation": {"ok": False, "videos": []},
            }
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(INGEST),
            "--run-dir",
            str(run_dir),
            "--state",
            "walk",
            "--invocation",
            str(invocation_path),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 3
    assert not (run_dir / "raw").exists()
    assert not (run_dir / "source-provenance.json").exists()


def test_ingest_rejects_provider_results_that_mix_images_with_the_video(
    tmp_path: Path,
) -> None:
    run_dir, first_frame, job = _prepare_job(tmp_path)
    result_path = tmp_path / str(job["provider_output"]["result_path"])
    result_path.parent.mkdir(parents=True)
    result_path.write_text("{}", encoding="utf-8")
    media_dir = result_path.parent / "media"
    media_dir.mkdir()
    video_path = media_dir / "video-01.mp4"
    video_path.write_bytes(b"video")
    image_path = media_dir / "image-01.png"
    Image.new("RGB", (8, 8), (128, 128, 128)).save(image_path)
    prompt_path = run_dir / str(job["prompt"]["path"])
    invocation_path = result_path.parent / "invocation.json"
    invocation_path.write_text(
        json.dumps(
            {
                "provider": "grok-imagine",
                "mode": "video-from-image",
                "cwd": str(tmp_path.resolve()),
                "promptFile": str(prompt_path.resolve()),
                "status": "completed",
                "exitCode": 0,
                "enforcement": {
                    "operation": "video-from-image",
                    "sourceFiles": [str(first_frame.resolve())],
                    "expectedImages": 0,
                    "expectedVideos": 1,
                },
                "resultValidation": {
                    "ok": True,
                    "images": [str(image_path.resolve())],
                    "videos": [str(video_path.resolve())],
                },
            }
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(INGEST),
            "--run-dir",
            str(run_dir),
            "--state",
            "walk",
            "--invocation",
            str(invocation_path),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 3
    assert "exactly zero accepted images" in completed.stdout
    assert not (run_dir / "raw").exists()
    assert not (run_dir / "source-provenance.json").exists()


def test_prepare_rejects_a_first_frame_over_the_dimension_limit(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "sprite-request.json").write_text(
        json.dumps(_request()), encoding="utf-8"
    )
    Image.new("RGBA", (4097, 1), (128, 128, 128, 255)).save(
        run_dir / "first-frame.png"
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(PREPARE),
            "--repo-root",
            str(tmp_path),
            "--run-dir",
            str(run_dir),
            "--state",
            "walk",
            "--first-frame",
            "first-frame.png",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 3
    assert "first-frame dimensions" in completed.stdout
