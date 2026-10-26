"""BUILD 06 proposal workflow for wireframe-bound visual design specifications."""
import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.actors import ActorContext, ActorType
from app.core.locking import lock_project
from app.models.ai_candidate import AIOutputCandidate
from app.models.ai_run import AIRun
from app.models.design_plan import DesignPlan, DesignPlanStatus
from app.models.design_state import DesignState
from app.models.direction import DesignDirection, DirectionStatus
from app.models.project import Project
from app.models.visual_design import VisualDesign
from app.models.wireframe import WireframeSet
from app.providers.contracts import TaskType
from app.providers.runtime import ProviderRuntime
from app.schemas.operation import OperationCreate
from app.schemas.visual_design import VisualDesignOutput, VisualDesignStatus
from app.services.design_reasoning import DesignReasoningService
from app.services.operation_executor import OperationExecutor


VISUAL_STATES = ("default", "hover", "focus", "active", "disabled", "loading", "error")


def stable_digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(raw).hexdigest()


class DeterministicVisualDesignEngine:
    """A reproducible, provider-free baseline for local runs and tests."""

    def generate(self, approved_plan: dict, approved_wireframe: dict) -> dict:
        component_refs = list(dict.fromkeys(
            ref
            for page in approved_wireframe.get("pages", [])
            for region in page.get("regions", [])
            for ref in region.get("component_refs", [])
        ))
        colors = {
            "ink": {"value": "#18212F", "role": "primary text", "rationale": "Strong text hierarchy."},
            "surface": {"value": "#FFFFFF", "role": "base surface", "rationale": "Clear neutral canvas."},
            "primary": {"value": "#315EFB", "role": "primary action", "rationale": "Consistent action emphasis."},
            "on_primary": {"value": "#FFFFFF", "role": "text on primary action", "rationale": "Readable action label."},
            "muted": {"value": "#64748B", "role": "secondary text", "rationale": "Subordinate supporting content."},
        }
        typography = {
            "display": {"font_family": "Inter, sans-serif", "size_px": 40.0, "weight": 700, "line_height": 1.15, "letter_spacing_px": -0.5},
            "body": {"font_family": "Inter, sans-serif", "size_px": 16.0, "weight": 400, "line_height": 1.5, "letter_spacing_px": 0.0},
            "label": {"font_family": "Inter, sans-serif", "size_px": 14.0, "weight": 600, "line_height": 1.35, "letter_spacing_px": 0.0},
        }
        pages = []
        for page in approved_wireframe.get("pages", []):
            regions = []
            for region in page.get("regions", []):
                regions.append({
                    "region_id": region["id"],
                    "treatment": f"Use a clear surface and preserve the {region['name']} hierarchy.",
                    "component_refs": list(region.get("component_refs", [])),
                    "token_refs": ["ink", "surface", "primary", "body"],
                })
            pages.append({
                "page_id": page["page_id"],
                "regions": regions,
                "responsive_behavior": list(page.get("responsive_notes") or ["Keep content readable and preserve region order at narrow widths."]),
                "accessibility_considerations": list(page.get("accessibility_notes") or ["Preserve keyboard access, visible focus, and semantic reading order."]),
            })
        components = [{
            "component_ref": ref,
            "name": ref,
            "variants": {"default": "Use the shared visual token system."},
            "states": {state: f"Provide a distinct, perceivable {state} treatment." for state in VISUAL_STATES},
            "token_refs": ["ink", "surface", "primary", "body"],
        } for ref in component_refs]
        return {
            "goals": ["Apply a consistent visual language while preserving the approved wireframe structure."],
            "rationale": "A conservative token-led treatment derived from the approved Design Plan and wireframe.",
            "pages": pages,
            "colors": colors,
            "typography": typography,
            "spacing_px": {"xs": 4.0, "sm": 8.0, "md": 16.0, "lg": 24.0, "xl": 32.0},
            "grid": "12-column desktop grid with fluid gutters and a single-column narrow layout.",
            "borders": {"subtle": "1px solid #E2E8F0"},
            "radii_px": {"control": 8.0, "card": 12.0, "pill": 999.0},
            "shadows": {"raised": "0 4px 16px rgba(15, 23, 42, 0.10)"},
            "elevation": {"raised": "Use for floating menus and dialogs only."},
            "components": components,
            "contrast_pairs": [
                {"foreground_token": "ink", "background_token": "surface", "text_size": "normal"},
                {"foreground_token": "on_primary", "background_token": "primary", "text_size": "normal"},
                {"foreground_token": "muted", "background_token": "surface", "text_size": "large"},
            ],
            "breakpoints": [
                {"name": "mobile", "min_width_px": 0, "max_width_px": 767, "behavior": "Stack regions and keep primary actions visible."},
                {"name": "tablet", "min_width_px": 768, "max_width_px": 1023, "behavior": "Use a compact grid and retain region order."},
                {"name": "desktop", "min_width_px": 1024, "max_width_px": None, "behavior": "Use the full grid and shared page shell."},
            ],
            "assets": [],
            "assumptions": ["Inter is available as a system or bundled font."],
            "unresolved_decisions": [],
            "risks": [],
            "confidence": 0.64,
        }


def _contrast_ratio(left: str, right: str) -> float:
    def luminance(color: str) -> float:
        channels = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in channels]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
    first, second = sorted((luminance(left), luminance(right)), reverse=True)
    return (first + 0.05) / (second + 0.05)


class VisualDesignWorkflow:
    def __init__(self, reasoning: DesignReasoningService | None = None):
        self.reasoning = reasoning or DesignReasoningService()

    def _current_sources(self, db: Session, project_id: uuid.UUID):
        project = db.get(Project, project_id)
        if project is None:
            raise HTTPException(404, "Project not found")
        state = db.get(DesignState, project_id)
        state_value = state.state if state else {}
        try:
            plan_id = uuid.UUID(str((state_value.get("design_plan") or {}).get("record_id")))
            wireframe_id = uuid.UUID(str((state_value.get("wireframes") or {}).get("record_id")))
        except (ValueError, TypeError, AttributeError) as exc:
            raise HTTPException(409, "A current approved Design Plan and wireframe are required") from exc
        plan = db.scalar(select(DesignPlan).where(
            DesignPlan.id == plan_id, DesignPlan.project_id == project_id,
            DesignPlan.status == DesignPlanStatus.APPROVED,
        ))
        wireframe = db.scalar(select(WireframeSet).where(
            WireframeSet.id == wireframe_id, WireframeSet.project_id == project_id,
        ))
        context = self.reasoning.build_context(db, project_id)
        if not plan or not wireframe or wireframe.status.value != "approved":
            raise HTTPException(409, "Approved Design Plan and wireframe records are required")
        if plan.intent_id != project.current_intent_id or wireframe.intent_id != project.current_intent_id:
            raise HTTPException(409, "Visual design sources use a stale intent revision")
        if plan.direction_id != wireframe.direction_id or str(plan.direction_id) != context["direction_id"]:
            raise HTTPException(409, "Visual design sources use a stale direction")
        if wireframe.design_plan_id != plan.id:
            raise HTTPException(409, "Wireframe does not belong to the current approved Design Plan")
        source_digest = context["source_manifest"]["content_digest"]
        if (plan.provenance.get("source_manifest") or {}).get("content_digest") != source_digest:
            raise HTTPException(409, "Approved Design Plan is stale for current requirements, laws, research, or questions")
        if wireframe.provenance.get("source_context_digest") != source_digest:
            raise HTTPException(409, "Approved wireframe is stale for current reasoning sources")
        plan_digest = stable_digest(plan.plan)
        if wireframe.provenance.get("design_plan_digest") != plan_digest:
            raise HTTPException(409, "Approved wireframe is stale for current Design Plan content")
        refs = {
            "design_plan_id": str(plan.id),
            "design_plan_digest": plan_digest,
            "wireframe_set_id": str(wireframe.id),
            "wireframe_digest": stable_digest(wireframe.wireframe),
            "source_context_digest": context["source_manifest"]["content_digest"],
            "source_manifest": context["source_manifest"],
        }
        return project, plan, wireframe, context, refs

    @staticmethod
    def validate_semantics(plan: DesignPlan, wireframe: WireframeSet, output: dict) -> dict:
        expected_pages = [str(item["id"]) for item in plan.plan.get("pages", [])]
        wire_pages = wireframe.wireframe.get("pages", [])
        expected_wire_pages = [str(item["page_id"]) for item in wire_pages]
        received_pages = [str(item["page_id"]) for item in output.get("pages", [])]
        if received_pages != expected_pages or expected_wire_pages != expected_pages:
            raise HTTPException(422, "Visual design must preserve approved plan and wireframe page order exactly")
        component_refs = {
            str(ref)
            for page in wire_pages for region in page.get("regions", [])
            for ref in region.get("component_refs", [])
        }
        components = output.get("components", [])
        component_ids = [str(item.get("component_ref")) for item in components]
        if len(component_ids) != len(set(component_ids)) or set(component_ids) != component_refs:
            raise HTTPException(422, "Visual component definitions must cover current wireframe components exactly once")
        color_tokens = output.get("colors", {})
        typography_tokens = output.get("typography", {})
        token_ids = set(color_tokens) | set(typography_tokens) | {f"space.{key}" for key in output.get("spacing_px", {})}
        expected_regions = {str(page["page_id"]): [str(region["id"]) for region in page.get("regions", [])] for page in wire_pages}
        seen_component_ids = set(component_ids)
        for page in output.get("pages", []):
            wire_page = next(item for item in wire_pages if str(item["page_id"]) == str(page["page_id"]))
            received_regions = [str(region["region_id"]) for region in page.get("regions", [])]
            if received_regions != expected_regions[str(page["page_id"])]:
                raise HTTPException(422, "Visual design must preserve every wireframe region and its order")
            for region, source_region in zip(page["regions"], wire_page["regions"]):
                if set(region.get("component_refs", [])) != set(source_region.get("component_refs", [])):
                    raise HTTPException(422, "Visual design cannot change wireframe component placement")
                if not set(region.get("token_refs", [])).issubset(token_ids):
                    raise HTTPException(422, "Visual design references an undefined token")
        for component in components:
            if not set(component.get("token_refs", [])).issubset(token_ids):
                raise HTTPException(422, "Component references an undefined token")
        required_states = set(VISUAL_STATES)
        for component in components:
            if not required_states.issubset(set(component.get("states", {}))):
                raise HTTPException(422, "Component visual states are incomplete")
        breakpoints = output.get("breakpoints", [])
        if not breakpoints or [item["min_width_px"] for item in breakpoints] != sorted(item["min_width_px"] for item in breakpoints):
            raise HTTPException(422, "Responsive breakpoints must be ordered by minimum width")
        if len({item["name"] for item in breakpoints}) != len(breakpoints):
            raise HTTPException(422, "Responsive breakpoint names must be unique")
        for item in breakpoints:
            if item.get("max_width_px") is not None and item["max_width_px"] < item["min_width_px"]:
                raise HTTPException(422, "Responsive breakpoint range has an invalid maximum width")
        for current, following in zip(breakpoints, breakpoints[1:]):
            if current.get("max_width_px") is None or current["max_width_px"] >= following["min_width_px"]:
                raise HTTPException(422, "Responsive breakpoint ranges must not overlap")
        contrast_results = []
        thresholds = {"normal": 4.5, "large": 3.0, "non_text": 3.0}
        for pair in output.get("contrast_pairs", []):
            foreground = pair["foreground_token"]
            background = pair["background_token"]
            if foreground not in color_tokens or background not in color_tokens:
                raise HTTPException(422, "Contrast pair references an undefined color token")
            ratio = _contrast_ratio(color_tokens[foreground]["value"], color_tokens[background]["value"])
            threshold = thresholds[pair["text_size"]]
            contrast_results.append({
                "foreground_token": foreground, "background_token": background,
                "ratio": round(ratio, 2), "threshold": threshold, "passed": ratio >= threshold,
            })
        failures = [item for item in contrast_results if not item["passed"]]
        if failures:
            raise HTTPException(422, "One or more declared color contrast pairs fail their configured threshold")
        return {"page_count": len(expected_pages), "region_count": sum(map(len, expected_regions.values())),
                "component_count": len(seen_component_ids), "contrast_pairs": contrast_results}

    def propose(self, db: Session, project_id: uuid.UUID, runtime: ProviderRuntime) -> dict:
        _, plan, wireframe, context, refs = self._current_sources(db, project_id)
        result = runtime.execute_sync(
            db, project_id=project_id, intent_id=plan.intent_id,
            task=TaskType.VISUAL_DESIGN_GENERATION,
            payload={"approved_plan": plan.plan, "approved_wireframe": wireframe.wireframe, "reasoning_context": context},
            output_schema=VisualDesignOutput,
            actor=ActorContext(ActorType.AI, actor_id="visual-design-runtime", trusted=True),
            context_references=refs,
        )
        candidate = result.candidate
        if result.accepted and candidate is not None:
            output = VisualDesignOutput.model_validate(candidate.payload, strict=True).model_dump(mode="json")
            try:
                self.validate_semantics(plan, wireframe, output)
            except HTTPException:
                candidate.validation_status = "quarantined"
                candidate.validation_error = "Visual design semantic validation failed"
                result.run.status = result.run.status.__class__.MALFORMED
                result.run.error = "visual design semantic validation failed"
                result.run.completed_at = datetime.now(timezone.utc)
                db.flush()
                return {"run_id": result.run.id, "candidate_id": candidate.id, "status": result.run.status.value,
                        "candidate": None, "accepted": False}
            db.add(VisualDesign(
                project_id=project_id, intent_id=plan.intent_id, direction_id=plan.direction_id,
                design_plan_id=plan.id, wireframe_set_id=wireframe.id, candidate_id=candidate.id,
                status=VisualDesignStatus.PROPOSED, visual_design=output,
                provenance={"source_type": "ai_visual_design_intelligence", **refs,
                            "ai_run_id": str(result.run.id), "candidate_id": str(candidate.id)},
            ))
            db.flush()
        return {"run_id": result.run.id, "candidate_id": candidate.id if candidate else None,
                "status": result.run.status.value, "candidate": candidate.payload if candidate else None,
                "accepted": result.accepted}

    def create_operation(self, db: Session, project_id: uuid.UUID, candidate_id: uuid.UUID,
                         actor: ActorContext, executor: OperationExecutor):
        lock_project(db, project_id)
        _, plan, wireframe, _, refs = self._current_sources(db, project_id)
        candidate = db.scalar(select(AIOutputCandidate).where(
            AIOutputCandidate.id == candidate_id, AIOutputCandidate.project_id == project_id,
            AIOutputCandidate.candidate_type == TaskType.VISUAL_DESIGN_GENERATION.value,
            AIOutputCandidate.validation_status == "valid",
        ))
        record = db.scalar(select(VisualDesign).where(
            VisualDesign.candidate_id == candidate_id, VisualDesign.project_id == project_id,
        ))
        run = db.get(AIRun, candidate.run_id) if candidate else None
        if not candidate or not record or not run or run.status.value != "succeeded":
            raise HTTPException(404, "Validated visual design candidate not found")
        if record.status != VisualDesignStatus.PROPOSED:
            raise HTTPException(409, "Visual design candidate is no longer eligible")
        if record.design_plan_id != plan.id or record.wireframe_set_id != wireframe.id:
            raise HTTPException(409, "Visual design candidate sources are stale")
        if any(record.provenance.get(key) != value for key, value in refs.items()):
            raise HTTPException(409, "Visual design source content changed; generate a new candidate")
        value = {"visual_design": record.visual_design, **refs, "visual_design_id": str(record.id),
                 "intent_revision_id": str(record.intent_id), "direction_id": str(record.direction_id)}
        data = OperationCreate(
            operation_type="create", actor="ai", target="metadata.visual_design", property="metadata.visual_design",
            new_value=value, reason=f"Propose visual design derived from approved wireframe {wireframe.id}.",
            source="ai_proposal", intent_id=plan.intent_id, ai_run_id=run.id, candidate_id=candidate.id,
            direction_id=plan.direction_id, provenance=dict(record.provenance),
        )
        return executor.propose(db, project_id, data, ActorContext(ActorType.AI, actor_id="visual-design-runtime", trusted=True))


def read_approved_visual_design(db: Session, project_id: uuid.UUID) -> VisualDesign:
    state = db.get(DesignState, project_id)
    record_id = ((state.state if state else {}).get("visual_design") or {}).get("record_id")
    try:
        visual_id = uuid.UUID(str(record_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(404, "Approved visual design not found") from exc
    row = db.scalar(select(VisualDesign).where(
        VisualDesign.id == visual_id, VisualDesign.project_id == project_id,
        VisualDesign.status == VisualDesignStatus.APPROVED,
    ))
    if not row:
        raise HTTPException(404, "Approved visual design not found")
    return row
