"""Fact-based gate selection for spritesheet QA workflows."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from spritecore.models import ContractDocument


GATE_IDS = (
    "generation-provenance",
    "animation-contracts",
    "frame-alignment",
    "identity-consistency",
    "motion-variation",
    "asset-slots",
    "isometric-tiles",
    "segmentation-diagnostic",
    "frame-registration",
    "runtime-preview",
)
WORKFLOWS = ("production", "import-diagnostic")
_LOCOMOTION_WORKFLOWS = frozenset(
    {"sideview-locomotion", "topdown-locomotion", "run-gun-layered-motion"}
)
_ISOMETRIC_PROJECTIONS = frozenset(
    {"isometric", "dimetric-2:1", "2:1-dimetric", "2:1 dimetric diamond"}
)
_ASSET_KINDS = frozenset(
    {"sprite", "tileset", "texture", "asset", "prop", "icon", "ui", "vfx"}
)
_FRAME_SEMANTICS = frozenset(
    {
        "animation",
        "variants",
        "tiles",
        "seamless-textures",
        "still-assets",
        "effects",
        "user-defined",
    }
)
_EXTRACTION_MODES = frozenset({"components", "slots"})


class GatePolicyError(ValueError):
    """The requested workflow, selector, or normalized fact is unsupported."""


@dataclass(frozen=True, slots=True)
class GateDecision:
    """Why one registered gate is applied or skipped."""

    id: str
    applied: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "applied": self.applied, "reason": self.reason}


@dataclass(frozen=True, slots=True)
class GatePolicy:
    """Immutable gate decisions for one normalized request and workflow."""

    workflow: str
    categories: tuple[str, ...]
    selectors: tuple[str, ...] | None
    decisions: tuple[GateDecision, ...]

    @property
    def required_gate_ids(self) -> tuple[str, ...]:
        return tuple(decision.id for decision in self.decisions if decision.applied)

    @property
    def applied_reasons(self) -> Mapping[str, str]:
        return MappingProxyType(
            {decision.id: decision.reason for decision in self.decisions if decision.applied}
        )

    @property
    def skipped_reasons(self) -> Mapping[str, str]:
        return MappingProxyType(
            {decision.id: decision.reason for decision in self.decisions if not decision.applied}
        )

    def decision_for(self, gate_id: str) -> GateDecision:
        try:
            return next(decision for decision in self.decisions if decision.id == gate_id)
        except StopIteration as exc:
            raise GatePolicyError(f"unknown gate id: {gate_id!r}") from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow": self.workflow,
            "categories": list(self.categories),
            "selectors": None if self.selectors is None else list(self.selectors),
            "required_gate_ids": list(self.required_gate_ids),
            "decisions": [decision.to_dict() for decision in self.decisions],
        }


def derive_gate_policy(
    request: ContractDocument | Mapping[str, Any],
    *,
    workflow: str = "production",
    selectors: Iterable[str] | None = None,
) -> GatePolicy:
    """Derive gate decisions from canonical request fields, never prose."""

    if workflow not in WORKFLOWS:
        raise GatePolicyError(
            f"unknown workflow {workflow!r}; expected one of {', '.join(WORKFLOWS)}"
        )
    selected = _normalize_selectors(selectors)
    facts = request.data if isinstance(request, ContractDocument) else request
    if not isinstance(facts, Mapping):
        raise GatePolicyError("request must be a normalized request mapping")
    _validate_normalized_request_facts(facts)

    asset_kind = facts.get("asset_kind")
    frame_semantics = facts.get("frame_semantics")
    extraction_mode = facts.get("extraction_mode")
    source_type = facts.get("source_type")
    if source_type is not None and (
        not isinstance(source_type, str)
        or source_type
        not in {
            "imagegen",
            "grok-imagine-image",
            "grok-imagine-video",
            "imported",
            "fixture",
            "mixed",
        }
    ):
        raise GatePolicyError(f"unknown normalized source_type: {source_type!r}")
    animated = frame_semantics in {"animation", "effects"}
    states = facts.get("states")
    static_sprite_frame_count = 0
    if isinstance(states, Mapping):
        static_sprite_frame_count = sum(
            max(0, frames)
            for entry in states.values()
            if isinstance(entry, Mapping)
            and isinstance((frames := entry.get("frames")), int)
            and not isinstance(frames, bool)
        )
    multi_frame_static_sprite = (
        not animated
        and asset_kind == "sprite"
        and static_sprite_frame_count > 1
    )
    workflows = _explicit_animation_workflows(facts)
    locomotion = sorted(workflows & _LOCOMOTION_WORKFLOWS)
    isometric_tiles, isometric_reason = _isometric_tileset(facts, asset_kind)

    categories: list[str] = ["animated" if animated else "static"]
    if source_type in {
        "imagegen",
        "grok-imagine-image",
        "grok-imagine-video",
        "mixed",
    }:
        categories.append("generated")
    if asset_kind == "tileset":
        categories.append("tileset")
    if asset_kind == "texture":
        categories.append("texture")
    if workflow == "import-diagnostic":
        categories.append("import-diagnostic")

    rules: dict[str, tuple[bool, str]] = {
        "generation-provenance": (
            workflow == "production",
            f"production source_type={source_type or 'unspecified'} requires provenance"
            if workflow == "production"
            else "import-diagnostic does not assert production provenance",
        ),
        "animation-contracts": (
            workflow == "production" and animated,
            f"frame_semantics={frame_semantics} is animated"
            if animated
            else f"frame_semantics={frame_semantics} is not animated",
        ),
        "frame-alignment": (
            workflow == "production" and animated and asset_kind == "sprite",
            "animated asset_kind=sprite requires frame alignment"
            if animated and asset_kind == "sprite"
            else "requires animated asset_kind=sprite",
        ),
        "identity-consistency": (
            workflow == "production"
            and asset_kind == "sprite"
            and (animated or multi_frame_static_sprite),
            (
                "animated asset_kind=sprite requires identity consistency"
                if animated
                else (
                    "multi-frame static asset_kind=sprite requires pose-set identity consistency"
                    if multi_frame_static_sprite
                    else "requires animated or multi-frame static asset_kind=sprite"
                )
            ),
        ),
        "motion-variation": (
            workflow == "production" and bool(locomotion),
            f"explicit locomotion workflow: {', '.join(locomotion)}"
            if locomotion
            else "no explicit locomotion animation_workflows fact",
        ),
        "asset-slots": (
            workflow == "production" and extraction_mode == "slots",
            f"asset_kind={asset_kind} extraction_mode=slots requires asset slot QA"
            if extraction_mode == "slots"
            else f"extraction_mode={extraction_mode} does not use slots",
        ),
        "isometric-tiles": (
            workflow == "production" and isometric_tiles,
            isometric_reason,
        ),
        "segmentation-diagnostic": (
            workflow == "import-diagnostic",
            "import-diagnostic requires segmentation evidence"
            if workflow == "import-diagnostic"
            else "production workflow does not use diagnostic segmentation as a gate",
        ),
        "frame-registration": (
            workflow == "import-diagnostic" and asset_kind == "sprite",
            "import-diagnostic asset_kind=sprite requires frame registration"
            if workflow == "import-diagnostic" and asset_kind == "sprite"
            else "requires import-diagnostic asset_kind=sprite",
        ),
        "runtime-preview": (
            workflow == "production" and animated,
            f"frame_semantics={frame_semantics} requires manifest-driven runtime evidence"
            if animated
            else f"frame_semantics={frame_semantics} does not require playback evidence",
        ),
    }
    if workflow != "production":
        for gate_id in GATE_IDS[1:7]:
            rules[gate_id] = (
                False,
                f"workflow={workflow} skips production-only gate {gate_id}",
            )
    decisions: list[GateDecision] = []
    for gate_id in GATE_IDS:
        applied, reason = rules[gate_id]
        if selected is not None and gate_id not in selected:
            applied = False
            reason = f"not selected by explicit gate selectors; policy reason: {reason}"
        decisions.append(GateDecision(id=gate_id, applied=applied, reason=reason))
    return GatePolicy(
        workflow=workflow,
        categories=tuple(categories),
        selectors=selected,
        decisions=tuple(decisions),
    )


def _explicit_animation_workflows(facts: Mapping[str, Any]) -> set[str]:
    workflows: set[str] = set()

    def add(values: Any) -> None:
        if isinstance(values, (list, tuple)):
            workflows.update(value for value in values if isinstance(value, str))

    add(facts.get("animation_workflows"))
    states = facts.get("states")
    if isinstance(states, Mapping):
        for entry in states.values():
            if isinstance(entry, Mapping):
                add(entry.get("animation_workflows"))
    return workflows


def _normalize_selectors(selectors: Iterable[str] | None) -> tuple[str, ...] | None:
    if selectors is None:
        return None
    supplied = (selectors,) if isinstance(selectors, str) else tuple(selectors)
    unknown = [
        selector
        for selector in supplied
        if not isinstance(selector, str) or selector not in GATE_IDS
    ]
    if unknown:
        rendered = ", ".join(sorted((repr(value) for value in unknown)))
        raise GatePolicyError(f"unknown gate selector(s): {rendered}")
    requested = set(supplied)
    return tuple(gate_id for gate_id in GATE_IDS if gate_id in requested)


def _validate_normalized_request_facts(facts: Mapping[str, Any]) -> None:
    issues: list[str] = []
    if facts.get("version") != 2:
        issues.append("version must be 2")
    if facts.get("kind") != "sprite-gen-request":
        issues.append("kind must be sprite-gen-request")
    if facts.get("asset_kind") not in _ASSET_KINDS:
        issues.append(f"asset_kind is unknown or missing: {facts.get('asset_kind')!r}")
    if facts.get("frame_semantics") not in _FRAME_SEMANTICS:
        issues.append(
            f"frame_semantics is unknown or missing: {facts.get('frame_semantics')!r}"
        )
    if facts.get("extraction_mode") not in _EXTRACTION_MODES:
        issues.append(
            f"extraction_mode is unknown or missing: {facts.get('extraction_mode')!r}"
        )
    states = facts.get("states")
    if not isinstance(states, Mapping) or not states:
        issues.append("states must be a non-empty mapping")
    if issues:
        raise GatePolicyError("request is not normalized: " + "; ".join(issues))


def _isometric_tileset(
    facts: Mapping[str, Any], asset_kind: Any
) -> tuple[bool, str]:
    if asset_kind != "tileset":
        return False, "asset_kind is not tileset"
    projection = facts.get("projection")
    if isinstance(projection, str) and projection in _ISOMETRIC_PROJECTIONS:
        return True, f"asset_kind=tileset projection={projection}"
    if facts.get("camera") == "isometric":
        return True, "asset_kind=tileset camera=isometric"
    catalog = facts.get("asset_catalog")
    catalog_projection = catalog.get("projection") if isinstance(catalog, Mapping) else None
    if (
        isinstance(catalog_projection, str)
        and catalog_projection in _ISOMETRIC_PROJECTIONS
    ):
        return True, f"asset_kind=tileset asset_catalog.projection={catalog_projection}"
    isometric = facts.get("isometric")
    if isinstance(isometric, Mapping) and isometric.get("enabled") is True:
        return True, "asset_kind=tileset isometric.enabled=true"
    return False, "tileset has no normalized isometric projection fact"
