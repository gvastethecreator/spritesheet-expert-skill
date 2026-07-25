from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw


REPO_ROOT = Path(__file__).resolve().parents[2]
CHECK = REPO_ROOT / "SKILLS" / "spritesheet-expert" / "scripts" / "check_colored_limb_motion.py"


COLORS = {
    "red": (235, 55, 50),
    "blue": (35, 135, 225),
    "orange": (250, 145, 30),
    "green": (100, 180, 70),
}


def draw_frame(path: Path, pose: dict[str, tuple[tuple[int, int], tuple[int, int], tuple[int, int]]]) -> None:
    image = Image.new("RGB", (200, 200), "white")
    draw = ImageDraw.Draw(image)
    draw.line((8, 180, 192, 180), fill=(100, 100, 100), width=1)
    draw.ellipse((90, 35, 110, 55), fill=(205, 205, 205), outline=(30, 30, 30))
    draw.polygon(((88, 55), (112, 55), (116, 120), (84, 120)), fill=(65, 65, 70))
    for color_name, points in pose.items():
        draw.line(points, fill=COLORS[color_name], width=11, joint="curve")
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def run_check(frames: list[Path], report: Path) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(CHECK), "--profile", "sideview-walk-6", "--report", str(report)]
    for frame in frames:
        command.extend(("--frame", str(frame)))
    return subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True, check=False)


def valid_poses() -> list[dict[str, tuple[tuple[int, int], tuple[int, int], tuple[int, int]]]]:
    shoulder_left = (92, 65)
    shoulder_right = (108, 65)
    hip_left = (94, 116)
    hip_right = (106, 116)
    return [
        {"red": (shoulder_left, (78, 90), (66, 116)), "blue": (shoulder_right, (126, 86), (140, 108)), "orange": (hip_left, (116, 145), (140, 180)), "green": (hip_right, (88, 148), (64, 180))},
        {"red": (shoulder_left, (82, 92), (72, 116)), "blue": (shoulder_right, (122, 90), (134, 112)), "orange": (hip_left, (112, 150), (128, 180)), "green": (hip_right, (86, 150), (70, 180))},
        {"red": (shoulder_left, (100, 88), (116, 108)), "blue": (shoulder_right, (98, 90), (82, 114)), "orange": (hip_left, (96, 150), (98, 180)), "green": (hip_right, (118, 142), (108, 160))},
        {"red": (shoulder_left, (126, 86), (140, 108)), "blue": (shoulder_right, (78, 90), (66, 116)), "orange": (hip_left, (88, 148), (64, 180)), "green": (hip_right, (116, 145), (140, 180))},
        {"red": (shoulder_left, (122, 90), (134, 112)), "blue": (shoulder_right, (82, 92), (72, 116)), "orange": (hip_left, (86, 150), (70, 180)), "green": (hip_right, (112, 150), (128, 180))},
        {"red": (shoulder_left, (78, 90), (66, 116)), "blue": (shoulder_right, (126, 86), (140, 108)), "orange": (hip_left, (118, 142), (108, 160)), "green": (hip_right, (104, 150), (102, 180))},
    ]


def test_checker_accepts_continuous_articulated_fixture(tmp_path: Path) -> None:
    frames: list[Path] = []
    for index, pose in enumerate(valid_poses(), start=1):
        frame = tmp_path / f"frame-{index:02d}.png"
        draw_frame(frame, pose)
        frames.append(frame)

    report = tmp_path / "report.json"
    result = run_check(frames, report)

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["ok"] is True
    assert all(item["active_transitions"] >= 4 for item in payload["trajectories"].values())


def test_checker_rejects_static_geometry_with_abrupt_color_swap(tmp_path: Path) -> None:
    poses = valid_poses()
    frozen = [poses[0], poses[0], poses[0], poses[3], poses[3], poses[3]]
    frames: list[Path] = []
    for index, pose in enumerate(frozen, start=1):
        frame = tmp_path / f"frame-{index:02d}.png"
        draw_frame(frame, pose)
        frames.append(frame)

    report = tmp_path / "report.json"
    result = run_check(frames, report)

    assert result.returncode == 1
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["ok"] is False
    assert any("active transitions" in error or "teleport or recolor jump" in error for error in payload["errors"])
