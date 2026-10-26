"""Strict BUILD 06 visual design contracts."""
import uuid
from datetime import datetime
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class StrictVisualModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")


class ColorToken(StrictVisualModel):
    value: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    role: str = Field(min_length=1)
    rationale: str = Field(min_length=1)


class TypographyToken(StrictVisualModel):
    font_family: str = Field(min_length=1)
    size_px: float = Field(gt=0, le=256)
    weight: int = Field(ge=100, le=900)
    line_height: float = Field(gt=0, le=4)
    letter_spacing_px: float = Field(default=0, ge=-10, le=50)


class ContrastPair(StrictVisualModel):
    foreground_token: str = Field(min_length=1)
    background_token: str = Field(min_length=1)
    text_size: str = Field(pattern=r"^(normal|large|non_text)$")


class ComponentVisual(StrictVisualModel):
    component_ref: str = Field(min_length=1)
    name: str = Field(min_length=1)
    variants: dict[str, str] = Field(min_length=1)
    states: dict[str, str] = Field(min_length=1)
    token_refs: list[str]


class RegionVisual(StrictVisualModel):
    region_id: str = Field(min_length=1)
    treatment: str = Field(min_length=1)
    component_refs: list[str]
    token_refs: list[str]


class PageVisual(StrictVisualModel):
    page_id: str = Field(min_length=1)
    regions: list[RegionVisual] = Field(min_length=1)
    responsive_behavior: list[str] = Field(min_length=1)
    accessibility_considerations: list[str] = Field(min_length=1)


class Breakpoint(StrictVisualModel):
    name: str = Field(min_length=1)
    min_width_px: int = Field(ge=0, le=10000)
    max_width_px: int | None = Field(default=None, ge=1, le=10000)
    behavior: str = Field(min_length=1)


class AssetReference(StrictVisualModel):
    asset_ref: str = Field(min_length=1)
    role: str = Field(min_length=1)
    source: str = Field(min_length=1)
    trusted: bool = False


class VisualDesignOutput(StrictVisualModel):
    goals: list[str] = Field(min_length=1)
    rationale: str = Field(min_length=1)
    pages: list[PageVisual] = Field(min_length=1)
    colors: dict[str, ColorToken] = Field(min_length=1)
    typography: dict[str, TypographyToken] = Field(min_length=1)
    spacing_px: dict[str, Annotated[float, Field(gt=0, le=1000)]] = Field(min_length=1)
    grid: str = Field(min_length=1)
    borders: dict[str, str]
    radii_px: dict[str, Annotated[float, Field(ge=0, le=2000)]]
    shadows: dict[str, str]
    elevation: dict[str, str]
    components: list[ComponentVisual]
    contrast_pairs: list[ContrastPair] = Field(min_length=1)
    breakpoints: list[Breakpoint] = Field(min_length=1)
    assets: list[AssetReference]
    assumptions: list[str]
    unresolved_decisions: list[str]
    risks: list[str]
    confidence: float = Field(ge=0, le=1)


class VisualDesignStatus(str, Enum):
    PROPOSED = "proposed"
    PREVIEWED = "previewed"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class VisualDesignCandidateResponse(StrictVisualModel):
    run_id: uuid.UUID
    candidate_id: uuid.UUID | None
    status: str
    candidate: VisualDesignOutput | dict | None
    accepted: bool


class VisualDesignRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    project_id: uuid.UUID
    intent_id: uuid.UUID
    direction_id: uuid.UUID
    design_plan_id: uuid.UUID
    wireframe_set_id: uuid.UUID
    status: VisualDesignStatus
    visual_design: dict
    provenance: dict
    created_at: datetime
    updated_at: datetime
    approved_at: datetime | None
    approved_by: str | None
