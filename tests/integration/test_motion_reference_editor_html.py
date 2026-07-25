import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EDITOR_DIR = ROOT / "SKILLS" / "spritesheet-expert" / "scripts" / "motion-reference-review"
EDITOR_EXTENSIONS = {".html", ".css", ".js", ".mjs"}


def editor_source() -> str:
    """Read the editor as one artifact even after HTML/CSS/JS are split."""
    paths = sorted(
        path
        for path in EDITOR_DIR.rglob("*")
        if path.is_file() and path.suffix.lower() in EDITOR_EXTENSIONS
    )
    assert any(path.name == "index.html" for path in paths)
    return "\n".join(path.read_text(encoding="utf-8") for path in paths)


def assert_ids(source: str, *control_ids: str) -> None:
    for control_id in control_ids:
        pattern = rf"\bid\s*=\s*[\"']{re.escape(control_id)}[\"']"
        assert re.search(pattern, source), f"missing editor control #{control_id}"


def test_editor_exposes_project_and_session_controls() -> None:
    source = editor_source()

    assert_ids(
        source,
        "projectName",
        "newProject",
        "saveProject",
        "importJson",
        "exportJson",
        "sessionStatus",
    )
    assert "localStorage" in source
    assert "sprite-animation-editor-project" in source


def test_editor_has_explicit_reference_slots_for_generation_context() -> None:
    source = editor_source()

    assert_ids(
        source,
        "referenceIdentity",
        "referenceMechanics",
        "referencePrevious",
        "referenceNext",
        "useWorkbenchTemplates",
    )
    assert "referenceSlots" in source
    assert "defaultMechanicsReferences" in source


def test_editor_surfaces_animation_contract_and_quality_gates() -> None:
    source = editor_source()

    assert_ids(source, "workflowContract", "gateChecklist", "gateSummary")
    assert "animation_contract" in source
    assert "quality_gates" in source


def test_editor_supports_a_persistent_correction_queue() -> None:
    source = editor_source()

    assert_ids(
        source,
        "correctionQueue",
        "queueCorrection",
        "exportCorrectionQueue",
    )
    assert "correctionQueue" in source
    assert "correction_jobs" in source


def test_editor_supports_multi_frame_selection_without_mutating_contract_order() -> None:
    source = editor_source()

    assert_ids(
        source,
        "selectionMode",
        "selectionSummary",
        "batchQaStatus",
        "applyBatchQa",
    )
    assert "selectedFrames" in source
    assert "toggleFrameSelection" in source

    forbidden_actions = (
        "REORDER_FRAMES",
        "DELETE_FRAME",
        "ADD_FRAME",
        "MOVE_FRAME",
        "reorderFrames",
        "deleteFrame",
        "addFrame",
        "moveFrame",
    )
    for action in forbidden_actions:
        assert action not in source


def test_editor_keeps_per_frame_variants_and_replacements_non_destructive() -> None:
    source = editor_source()

    assert_ids(
        source,
        "variantList",
        "addVariant",
        "activateVariant",
        "replaceFrame",
        "clearReplacement",
    )
    assert "frameVariants" in source
    assert "frameOverrides" in source


def test_editor_exports_a_project_and_imagegen_correction_packets() -> None:
    source = editor_source()

    assert_ids(source, "exportJson", "exportAlignment", "exportPacket", "exportPng")
    assert "sprite-animation-editor-project" in source
    assert "sprite-imagegen-frame-correction-packet" in source
    assert "alignmentProfilePayload" in source
    assert "sprite-frame-registration-corrections" in source
    assert "previous-target-next" not in source  # Packet roles remain explicit and inspectable.
    for role in ('role: "identity"', 'role: "mechanics"', 'role: "previous"', 'role: "target_to_edit"', 'role: "next"'):
        assert role in source


def test_editor_exposes_alignment_comparison_and_per_frame_qa_tools() -> None:
    source = editor_source()

    assert_ids(
        source,
        "zoomIn",
        "fitView",
        "undo",
        "redo",
        "scaleHandle",
        "offsetX",
        "offsetY",
        "scale",
        "showBaseline",
        "showCenter",
        "showThirds",
        "showBounds",
        "baseline",
        "snapMode",
        "compareMode",
        "onionPrevious",
        "onionNext",
        "frameLocked",
        "qaStatus",
        "frameNote",
        "correctionPrompt",
    )
    assert 'globalCompositeOperation = "difference"' in source
