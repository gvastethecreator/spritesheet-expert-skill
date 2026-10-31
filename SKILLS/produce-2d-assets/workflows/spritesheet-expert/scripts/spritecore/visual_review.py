"""Load and validate hash-bound visual review contracts without writing files."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any, IO, Mapping

from jsonschema import Draft202012Validator, FormatChecker

from spritecore.paths import PathSafetyError, resolve_run_path


VISUAL_REVIEW_VERSION = 1
VISUAL_REVIEW_KIND = "sprite-visual-review"
VISUAL_REVIEW_RELATIVE_PATH = "qa/visual-review.json"
_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "references"
    / "schemas"
    / "visual-review-v1.schema.json"
)
_VISUAL_ARTIFACT_SUFFIXES = {".png", ".gif", ".webp", ".jpg", ".jpeg"}


class VisualReviewError(ValueError):
    """Base error for visual review contract operations."""


class VisualReviewLoadError(VisualReviewError):
    """The supplied review could not be read as a JSON object."""


class VisualReviewValidationError(VisualReviewError):
    """The review violates its schema or no longer matches its artifacts."""

    def __init__(self, issues: list[str]):
        self.issues = tuple(issues)
        super().__init__("invalid visual review: " + "; ".join(issues))


VisualReviewSource = Mapping[str, Any] | str | Path | IO[str]


def _load_validator() -> Draft202012Validator:
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


_VALIDATOR = _load_validator()


def load_visual_review(
    source: VisualReviewSource | None = None, *, run_dir: Path
) -> dict[str, Any]:
    """Load one JSON review source and validate it against the current run."""

    if source is None:
        try:
            source = resolve_run_path(run_dir, VISUAL_REVIEW_RELATIVE_PATH)
        except PathSafetyError as exc:
            raise VisualReviewLoadError(
                f"could not locate visual review: {exc}"
            ) from exc
    payload = _read_source(source)
    return validate_visual_review(payload, run_dir=run_dir)


def validate_visual_review(
    payload: Mapping[str, Any], *, run_dir: Path
) -> dict[str, Any]:
    """Return a detached valid review or raise with every discovered issue."""

    document = deepcopy(dict(payload))
    schema_errors = sorted(
        _VALIDATOR.iter_errors(document), key=lambda error: list(error.absolute_path)
    )
    issues = [_format_schema_error(error) for error in schema_errors]
    if issues:
        raise VisualReviewValidationError(issues)
    issues.extend(_reference_issues(document))

    actual_artifacts: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for index, declared in enumerate(document["reviewed_artifacts"]):
        path = declared["path"]
        try:
            actual = snapshot_review_artifact(run_dir, path)
        except VisualReviewValidationError as exc:
            issues.extend(
                f"reviewed_artifacts.{index}: {issue}" for issue in exc.issues
            )
            continue
        actual_artifacts.append(actual)
        if actual["path"] in seen_paths:
            issues.append(
                f"reviewed_artifacts.{index}.path: duplicate artifact {actual['path']!r}"
            )
        seen_paths.add(actual["path"])
        if path != actual["path"]:
            issues.append(
                f"reviewed_artifacts.{index}.path: expected canonical run-relative "
                f"path {actual['path']!r}"
            )
        if declared["sha256"] != actual["sha256"]:
            issues.append(
                f"reviewed_artifacts.{index}.sha256: artifact changed; expected "
                f"{declared['sha256']}, got {actual['sha256']}"
            )
        if declared["size_bytes"] != actual["size_bytes"]:
            issues.append(
                f"reviewed_artifacts.{index}.size_bytes: artifact changed; expected "
                f"{declared['size_bytes']}, got {actual['size_bytes']}"
            )

    if len(actual_artifacts) == len(document["reviewed_artifacts"]):
        actual_fingerprint = compute_input_fingerprint(actual_artifacts)
        if document["input_fingerprint"] != actual_fingerprint:
            issues.append(
                "input_fingerprint: reviewed artifact set changed; expected "
                f"{document['input_fingerprint']}, got {actual_fingerprint}"
            )
    if issues:
        raise VisualReviewValidationError(issues)
    return document


def snapshot_review_artifact(run_dir: Path, candidate: str | Path) -> dict[str, Any]:
    """Return canonical path, SHA-256, and byte size for one safe run artifact."""

    run_root = Path(run_dir).expanduser().resolve()
    try:
        artifact = resolve_run_path(run_root, candidate)
    except PathSafetyError as exc:
        raise VisualReviewValidationError([str(exc)]) from exc
    if not artifact.is_file():
        raise VisualReviewValidationError([f"reviewed artifact is missing: {candidate}"])

    digest = hashlib.sha256()
    size_bytes = 0
    try:
        with artifact.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
                size_bytes += len(chunk)
    except OSError as exc:
        raise VisualReviewValidationError(
            [f"could not read reviewed artifact {candidate!r}: {exc}"]
        ) from exc
    return {
        "path": artifact.relative_to(run_root).as_posix(),
        "sha256": digest.hexdigest(),
        "size_bytes": size_bytes,
    }


def snapshot_review_artifacts(
    run_dir: Path, candidates: list[str | Path]
) -> list[dict[str, Any]]:
    """Snapshot a non-empty, unique set of reviewed run artifacts."""

    if not candidates:
        raise VisualReviewValidationError(["at least one reviewed artifact is required"])
    records = [snapshot_review_artifact(run_dir, candidate) for candidate in candidates]
    paths = [record["path"] for record in records]
    if len(paths) != len(set(paths)):
        raise VisualReviewValidationError(["reviewed artifact paths must be unique"])
    return records


def compute_input_fingerprint(artifacts: list[Mapping[str, Any]]) -> str:
    """Fingerprint a canonical reviewed-artifact set independent of list order."""

    canonical = sorted(
        (
            {
                "path": str(artifact["path"]),
                "sha256": str(artifact["sha256"]),
                "size_bytes": int(artifact["size_bytes"]),
            }
            for artifact in artifacts
        ),
        key=lambda artifact: artifact["path"],
    )
    encoded = json.dumps(
        canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _read_source(source: VisualReviewSource) -> dict[str, Any]:
    try:
        if isinstance(source, Mapping):
            payload = deepcopy(dict(source))
        elif hasattr(source, "read"):
            payload = json.loads(source.read())
        else:
            payload = json.loads(
                Path(source).expanduser().resolve().read_text(encoding="utf-8-sig")
            )
    except (OSError, TypeError, ValueError) as exc:
        raise VisualReviewLoadError(f"could not load visual review: {exc}") from exc
    if not isinstance(payload, dict):
        raise VisualReviewLoadError("visual review root must be a JSON object")
    return payload


def _format_schema_error(error: Any) -> str:
    path = ".".join(str(part) for part in error.absolute_path)
    return f"{path}: {error.message}" if path else error.message


def _reference_issues(document: Mapping[str, Any]) -> list[str]:
    issues: list[str] = []
    rubric_ids = [answer["id"] for answer in document["rubric"]]
    failure_ids = [failure["id"] for failure in document["failures"]]
    reviewed_paths = {
        artifact["path"] for artifact in document["reviewed_artifacts"]
    }
    if not any(
        Path(path).suffix.lower() in _VISUAL_ARTIFACT_SUFFIXES
        for path in reviewed_paths
    ):
        issues.append(
            "reviewed_artifacts must include at least one raster visual artifact"
        )
    reviewed_at = datetime.fromisoformat(document["reviewed_at"].replace("Z", "+00:00"))
    if len(rubric_ids) != len(set(rubric_ids)):
        issues.append("rubric ids must be unique")
    for index, answer in enumerate(document["rubric"]):
        verdict = answer["answer"]
        score = answer["score"]
        if verdict == "pass" and score < 3:
            issues.append(
                f"rubric.{index}.score: pass requires a score of at least 3"
            )
        elif verdict == "fail" and score > 2:
            issues.append(
                f"rubric.{index}.score: fail requires a score of at most 2"
            )
        elif verdict == "not-applicable" and score != 0:
            issues.append(
                f"rubric.{index}.score: not-applicable requires score 0"
            )
    rubric_by_id = {answer["id"]: answer for answer in document["rubric"]}
    if document["status"] == "pass" and any(
        answer["answer"] == "fail" for answer in document["rubric"]
    ):
        issues.append("status pass cannot contain a failing rubric answer")
    if len(failure_ids) != len(set(failure_ids)):
        issues.append("failure ids must be unique")
    for index, failure in enumerate(document["failures"]):
        if failure["rubric_id"] not in rubric_ids:
            issues.append(
                f"failures.{index}.rubric_id: unknown rubric answer "
                f"{failure['rubric_id']!r}"
            )
        elif rubric_by_id[failure["rubric_id"]]["answer"] != "fail":
            issues.append(
                f"failures.{index}.rubric_id: referenced rubric answer is not fail"
            )
        artifact_path = failure.get("artifact_path")
        if artifact_path is not None and artifact_path not in reviewed_paths:
            issues.append(
                f"failures.{index}.artifact_path: artifact was not reviewed: "
                f"{artifact_path!r}"
            )
    for index, waiver in enumerate(document["waivers"]):
        if waiver["failure_id"] not in failure_ids:
            issues.append(
                f"waivers.{index}.failure_id: unknown failure "
                f"{waiver['failure_id']!r}"
            )
        expires_at = datetime.fromisoformat(waiver["expires_at"].replace("Z", "+00:00"))
        if expires_at <= reviewed_at:
            issues.append(
                f"waivers.{index}.expires_at: must be after reviewed_at"
            )
    return issues
