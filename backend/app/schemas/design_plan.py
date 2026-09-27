"""Strict structured contracts for proposed Design Plans."""
import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from app.models.design_plan import DesignPlanStatus


class StrictModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")


class PagePlan(StrictModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    primary_user_goal: str = Field(min_length=1)
    primary_action: str = Field(min_length=1)
    sections: list[str]
    requirements: list[str]
    research_evidence: list[str]
    responsive_notes: list[str]
    accessibility_notes: list[str]
    rationale: str = Field(min_length=1)


class UserFlowPlan(StrictModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    entry_points: list[str]
    steps: list[str]
    success_state: str = Field(min_length=1)
    failure_states: list[str]
    edge_cases: list[str]
    requirements: list[str]
    rationale: str = Field(min_length=1)


class InformationArchitecture(StrictModel):
    primary_navigation: list[str]
    secondary_navigation: list[str]
    pages: list[str]
    hierarchy: list[str]
    content_groups: list[str]
    rationale: str = Field(min_length=1)


class LayoutStrategy(StrictModel):
    page_shell: str = Field(min_length=1)
    grid: str = Field(min_length=1)
    spacing: str = Field(min_length=1)
    content_width: str = Field(min_length=1)
    hierarchy: list[str]
    density: str = Field(min_length=1)
    responsive_behavior: list[str]
    rationale: str = Field(min_length=1)


class ComponentStrategy(StrictModel):
    shared_components: list[str]
    page_specific_components: dict[str, list[str]]
    component_states: list[str]
    composition_rules: list[str]
    reuse_rules: list[str]
    rationale: str = Field(min_length=1)


class TokenStrategy(StrictModel):
    color_roles: dict[str, str | None]
    typography_roles: dict[str, str]
    spacing_scale: list[str]
    radius_strategy: str
    elevation_strategy: str
    motion_strategy: str
    rationale: str = Field(min_length=1)


class ResponsiveStrategy(StrictModel):
    breakpoints: list[str]
    layout_changes: list[str]
    navigation_changes: list[str]
    content_priority_changes: list[str]
    interaction_changes: list[str]
    rationale: str = Field(min_length=1)


class AccessibilityStrategy(StrictModel):
    keyboard_navigation: list[str]
    focus_management: list[str]
    semantic_structure: list[str]
    contrast: list[str]
    motion_preferences: list[str]
    touch_targets: list[str]
    screen_reader_considerations: list[str]
    forms: list[str]
    errors: list[str]
    rationale: str = Field(min_length=1)


class InteractionStrategy(StrictModel):
    primary_interactions: list[str]
    feedback_patterns: list[str]
    loading_states: list[str]
    empty_states: list[str]
    error_states: list[str]
    success_states: list[str]
    motion_rules: list[str]
    rationale: str = Field(min_length=1)


class RequirementCoverage(str, Enum):
    COVERED = "covered"
    PARTIALLY_COVERED = "partially_covered"
    NOT_YET_ADDRESSED = "not_yet_addressed"


class RequirementMapping(StrictModel):
    requirement_id: str
    design_decision: str = Field(min_length=1)
    coverage: RequirementCoverage
    notes: str


class ResearchMapping(StrictModel):
    evidence_id: str
    design_decision: str = Field(min_length=1)
    influence: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


class Risk(StrictModel):
    description: str = Field(min_length=1)
    impact: str = Field(min_length=1)
    mitigation: str = Field(min_length=1)
    source: str = Field(min_length=1)


class Tradeoff(StrictModel):
    decision: str = Field(min_length=1)
    benefit: str = Field(min_length=1)
    cost: str = Field(min_length=1)
    affected_area: str = Field(min_length=1)


class DesignLawConsideration(StrictModel):
    id: str
    law: str = Field(min_length=1)
    consideration: str = Field(min_length=1)
    conflict: str = Field(min_length=1)


class UnresolvedQuestion(StrictModel):
    question_id: str
    impact: str
    effect: str = Field(min_length=1)


class DesignPlanOutput(StrictModel):
    project_context: dict[str, Any]
    information_architecture: InformationArchitecture
    pages: list[PagePlan]
    user_flows: list[UserFlowPlan]
    layout_strategy: LayoutStrategy
    component_strategy: ComponentStrategy
    design_token_strategy: TokenStrategy
    responsive_strategy: ResponsiveStrategy
    accessibility_strategy: AccessibilityStrategy
    interaction_strategy: InteractionStrategy
    content_strategy: dict[str, Any]
    requirements_mapping: list[RequirementMapping]
    research_mapping: list[ResearchMapping]
    design_laws_considered: list[DesignLawConsideration]
    assumptions: list[str]
    unresolved_questions: list[UnresolvedQuestion]
    risks: list[Risk]
    tradeoffs: list[Tradeoff]
    rationale: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


class DesignPlanCandidateResponse(StrictModel):
    run_id: uuid.UUID
    candidate_id: uuid.UUID | None
    status: str
    candidate: DesignPlanOutput | dict[str, Any] | None
    accepted: bool


class DesignPlanRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    project_id: uuid.UUID
    intent_id: uuid.UUID
    direction_id: uuid.UUID
    status: DesignPlanStatus
    plan: dict[str, Any]
    confidence: float
    provenance: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    approved_at: datetime | None
    approved_by: str | None


class SourceManifest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    intent: list[str]
    requirements: list[str]
    research: list[str]
    design_laws: list[str]
    questions: list[str]


class DesignReasoningContextRead(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    project_context: dict[str, Any]
    intent_revision_id: str
    direction_id: str
    intent: dict[str, Any]
    direction: dict[str, Any]
    requirements: list[dict[str, Any]]
    research: list[dict[str, Any]]
    design_laws: list[dict[str, Any]]
    open_questions: list[dict[str, Any]]
    source_manifest: SourceManifest
