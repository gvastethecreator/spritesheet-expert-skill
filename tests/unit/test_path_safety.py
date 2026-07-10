from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from spritecore.paths import (
    RUN_MARKER_FILENAME,
    PathSafetyError,
    create_run_marker,
    guarded_clean_run_dir,
    remove_known_outputs,
    replace_owned_run,
    resolve_run_path,
)


def test_resolve_run_path_confines_relative_paths_to_the_run(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    assert resolve_run_path(run_dir, "frames/idle/frame-0.png") == (
        run_dir / "frames" / "idle" / "frame-0.png"
    ).resolve()

    with pytest.raises(PathSafetyError, match="traversal"):
        resolve_run_path(run_dir, "../outside.png")


@pytest.mark.parametrize(
    "unsafe_path",
    [
        "/tmp/outside.png",
        r"C:\temp\outside.png",
        "C:/temp/outside.png",
        r"\\server\share\outside.png",
        "//server/share/outside.png",
        r"..\outside.png",
        r"frames\idle/frame-0.png",
        ".",
        "CON",
        "aux.txt",
        "frames/NUL.png",
        "frames/file:stream.png",
    ],
)
def test_resolve_run_path_rejects_cross_platform_unsafe_syntax(
    tmp_path: Path, unsafe_path: str
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    with pytest.raises(PathSafetyError):
        resolve_run_path(run_dir, unsafe_path)


def test_resolve_run_path_requires_canonical_unicode_normalization(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    assert resolve_run_path(run_dir, "frames/caf\N{LATIN SMALL LETTER E WITH ACUTE}.png") == (
        run_dir / "frames" / "caf\N{LATIN SMALL LETTER E WITH ACUTE}.png"
    ).resolve()
    with pytest.raises(PathSafetyError, match="Unicode normalization"):
        resolve_run_path(run_dir, "frames/cafe\N{COMBINING ACUTE ACCENT}.png")


def test_resolve_run_path_rejects_unicode_separator_confusables(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    for separator in ("∕", "⁄", "／", "⧸", "＼", "﹨", "∖"):
        with pytest.raises(PathSafetyError, match="confusable"):
            resolve_run_path(run_dir, f"frames{separator}..{separator}outside.png")


def test_resolve_run_path_rejects_control_and_bidi_format_characters(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    for character in ("\n", "\r", "\t", "\N{RIGHT-TO-LEFT OVERRIDE}", "\N{LEFT-TO-RIGHT ISOLATE}"):
        with pytest.raises(PathSafetyError, match="control or format"):
            resolve_run_path(run_dir, f"frames/idle{character}.png")


def test_resolve_run_path_rejects_empty_or_aliased_components(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    for candidate in ("frames//idle.png", "frames/idle.png/", r"frames\\idle.png"):
        with pytest.raises(PathSafetyError, match="empty path component"):
            resolve_run_path(run_dir, candidate)


def test_resolve_run_path_rejects_1000_deterministic_hostile_attempts(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    hostile_patterns = (
        lambda index: f"../outside-{index}.png",
        lambda index: f"frames/../../outside-{index}.png",
        lambda index: rf"C:\temp\outside-{index}.png",
        lambda index: rf"\\server\share\outside-{index}.png",
        lambda index: rf"frames\idle/frame-{index}.png",
        lambda index: f"frames/file-{index}:stream.png",
        lambda index: f"frames/NUL.{index}",
        lambda index: f"frames/trailing-{index}. ",
        lambda index: f"frames∕..∕outside-{index}.png",
        lambda index: f"frames/idle-{index}\n.png",
    )
    hostile_paths = [
        hostile_patterns[index % len(hostile_patterns)](index)
        for index in range(1000)
    ]

    assert len(set(hostile_paths)) == 1000
    for hostile_path in hostile_paths:
        with pytest.raises(PathSafetyError):
            resolve_run_path(run_dir, hostile_path)


def test_guarded_clean_refuses_an_unmarked_directory(tmp_path: Path) -> None:
    run_dir = tmp_path / "unmarked"
    run_dir.mkdir()
    sentinel = run_dir / "keep.txt"
    sentinel.write_text("keep", encoding="utf-8")

    with pytest.raises(PathSafetyError, match="marker"):
        guarded_clean_run_dir(run_dir)

    assert sentinel.read_text(encoding="utf-8") == "keep"


def test_guarded_clean_rejects_a_symlinked_marker_before_deleting_contents(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    sentinel = run_dir / "keep.txt"
    sentinel.write_text("keep", encoding="utf-8")
    external_marker = tmp_path / "external-marker.json"
    external_marker.write_text(
        json.dumps({"version": 1, "kind": "sprite-run", "run_id": "run-123"}),
        encoding="utf-8",
    )
    try:
        (run_dir / RUN_MARKER_FILENAME).symlink_to(external_marker)
    except OSError as exc:
        pytest.skip(f"file symlinks are unavailable: {exc}")

    with pytest.raises(PathSafetyError, match="unsafe"):
        guarded_clean_run_dir(run_dir)

    assert sentinel.read_text(encoding="utf-8") == "keep"
    assert external_marker.is_file()


def test_create_run_marker_refuses_a_nonempty_unowned_directory(tmp_path: Path) -> None:
    run_dir = tmp_path / "existing"
    run_dir.mkdir()
    sentinel = run_dir / "artist-source.png"
    sentinel.write_bytes(b"preserve")

    with pytest.raises(PathSafetyError, match="non-empty"):
        create_run_marker(run_dir, run_id="claimed-run")

    assert sentinel.read_bytes() == b"preserve"
    assert not (run_dir / RUN_MARKER_FILENAME).exists()


def test_create_run_marker_rejects_an_invalid_id_before_creating_the_run(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "not-created"

    with pytest.raises(PathSafetyError, match="non-empty string"):
        create_run_marker(run_dir, run_id="   ")

    assert not run_dir.exists()


def test_guarded_clean_removes_only_owned_run_contents(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    marker = create_run_marker(run_dir, run_id="run-123")
    nested = run_dir / "frames" / "idle"
    nested.mkdir(parents=True)
    payload = nested / "frame-0.png"
    payload.write_bytes(b"sprite")

    removed = guarded_clean_run_dir(run_dir)

    assert removed == [run_dir / "frames"]
    assert not payload.exists()
    assert marker == run_dir / RUN_MARKER_FILENAME
    assert marker.is_file()


def test_remove_known_outputs_requires_a_marker_by_default(tmp_path: Path) -> None:
    run_dir = tmp_path / "existing-run"
    run_dir.mkdir()
    generated = run_dir / "manifest.json"
    generated.write_text("generated", encoding="utf-8")

    with pytest.raises(PathSafetyError, match="marker"):
        remove_known_outputs(run_dir, ["manifest.json"])

    assert generated.read_text(encoding="utf-8") == "generated"


def test_remove_known_outputs_preserves_unknown_files(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    create_run_marker(run_dir, run_id="run-123")
    qa_dir = run_dir / "qa"
    qa_dir.mkdir(parents=True)
    manifest = run_dir / "manifest.json"
    manifest.write_text("generated", encoding="utf-8")
    (qa_dir / "report.json").write_text("generated", encoding="utf-8")
    unknown = run_dir / "artist-notes.txt"
    unknown.write_text("preserve", encoding="utf-8")

    removed = remove_known_outputs(
        run_dir, ["manifest.json", "qa", "output-that-does-not-exist.png"]
    )

    assert removed == [manifest, qa_dir]
    assert not manifest.exists()
    assert not qa_dir.exists()
    assert unknown.read_text(encoding="utf-8") == "preserve"
    assert (run_dir / RUN_MARKER_FILENAME).is_file()


def test_remove_known_outputs_validates_every_path_before_deleting_anything(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    create_run_marker(run_dir, run_id="run-123")
    manifest = run_dir / "manifest.json"
    manifest.write_text("generated", encoding="utf-8")

    with pytest.raises(PathSafetyError, match="traversal"):
        remove_known_outputs(run_dir, ["manifest.json", "../outside.png"])

    assert manifest.read_text(encoding="utf-8") == "generated"


def test_remove_known_outputs_unlinks_a_leaf_symlink_without_deleting_its_target(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    create_run_marker(run_dir, run_id="run-123")
    sentinel = run_dir / "artist-source.png"
    sentinel.write_bytes(b"preserve")
    link = run_dir / "manifest.json"
    try:
        link.symlink_to(sentinel)
    except OSError as exc:
        pytest.skip(f"file symlinks are unavailable: {exc}")

    removed = remove_known_outputs(run_dir, ["manifest.json"])

    assert removed == [link]
    assert not link.exists()
    assert sentinel.read_bytes() == b"preserve"


def test_resolve_run_path_rejects_a_symlink_escape(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    outside = tmp_path / "outside"
    run_dir.mkdir()
    outside.mkdir()
    (outside / "payload.png").write_bytes(b"outside")
    link = run_dir / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks are unavailable: {exc}")

    with pytest.raises(PathSafetyError, match="escapes"):
        resolve_run_path(run_dir, "linked/payload.png")


def test_replace_owned_run_commits_a_new_marked_run(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    create_run_marker(run_dir, run_id="run-123")
    original = run_dir / "old-atlas.png"
    original.write_bytes(b"old")

    with replace_owned_run(run_dir, "run-123") as replacement:
        assert replacement == run_dir
        assert (replacement / RUN_MARKER_FILENAME).is_file()
        assert not original.exists()
        (replacement / "new-atlas.png").write_bytes(b"new")

    assert not original.exists()
    assert (run_dir / "new-atlas.png").read_bytes() == b"new"
    assert list(tmp_path.glob(".run.backup-*")) == []


def test_replace_owned_run_restores_the_original_on_error(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    create_run_marker(run_dir, run_id="run-123")
    original = run_dir / "artist-source.png"
    original.write_bytes(b"original")

    with pytest.raises(RuntimeError, match="render failed"):
        with replace_owned_run(run_dir, "run-123") as replacement:
            (replacement / "partial-atlas.png").write_bytes(b"partial")
            raise RuntimeError("render failed")

    assert original.read_bytes() == b"original"
    assert not (run_dir / "partial-atlas.png").exists()
    assert (run_dir / RUN_MARKER_FILENAME).is_file()
    assert list(tmp_path.glob(".run.backup-*")) == []


def test_replace_owned_run_rejects_a_different_run_id(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    create_run_marker(run_dir, run_id="run-123")
    original = run_dir / "artist-source.png"
    original.write_bytes(b"original")

    with pytest.raises(PathSafetyError, match="marker id"):
        with replace_owned_run(run_dir, "run-999"):
            pytest.fail("a mismatched marker must not enter the transaction")

    assert original.read_bytes() == b"original"
    assert list(tmp_path.glob(".run.backup-*")) == []


def test_replace_owned_run_skips_an_existing_backup_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = tmp_path / "run"
    create_run_marker(run_dir, run_id="run-123")
    collision = tmp_path / ".run.backup-collision"
    collision.mkdir()
    sentinel = collision / "keep.txt"
    sentinel.write_text("keep", encoding="utf-8")
    suffixes = iter(["collision", "available"])
    monkeypatch.setattr(
        "spritecore.paths.uuid.uuid4",
        lambda: SimpleNamespace(hex=next(suffixes)),
    )

    with replace_owned_run(run_dir, "run-123") as replacement:
        (replacement / "atlas.png").write_bytes(b"new")

    assert sentinel.read_text(encoding="utf-8") == "keep"
    assert (run_dir / "atlas.png").read_bytes() == b"new"
    assert not (tmp_path / ".run.backup-available").exists()


@pytest.mark.parametrize(
    "dangerous_root",
    [Path.cwd(), Path.home(), Path(Path.cwd().anchor)],
)
def test_replace_owned_run_rejects_dangerous_roots(dangerous_root: Path) -> None:
    with pytest.raises(PathSafetyError, match="dangerous"):
        with replace_owned_run(dangerous_root, "run-123"):
            pytest.fail("a dangerous root must not enter the transaction")
