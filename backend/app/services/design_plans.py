"""Deterministic, explicitly non-LLM design-planning candidate engine."""
import re
from collections import Counter
from typing import Any

from app.schemas.design_plan import DesignPlanOutput, RequirementCoverage


class DeterministicDesignPlanEngine:
    """Turn checked project context into a planning candidate without inventing visual facts."""

    ENGINE_NAME = "build04_deterministic_design_plan"

    def generate(self, context: dict[str, Any]) -> dict[str, Any]:
        intent = context["intent"]
        direction = context["direction"]
        requirements = context["requirements"]
        research = context["research"]
        laws = context["design_laws"]
        questions = context["open_questions"]
        action = intent.get("desired_user_action") or "Complete the primary task described in the project request"

        page_names = self._unique_strings(intent.get("required_pages", []))
        feature_pages = []
        for feature in intent.get("required_features", []):
            label = self._title(str(feature))
            if any(word in label.casefold() for word in ("checkout", "purchase", "payment")):
                feature_pages.append("Checkout")
            elif any(word in label.casefold() for word in ("product discovery", "product evaluation", "catalog")):
                feature_pages.append("Products")
            elif any(word in label.casefold() for word in ("sign-up", "signup", "registration", "onboarding")):
                feature_pages.append("Sign Up")
        page_names = self._unique_strings(page_names + feature_pages)
        if not page_names:
            page_names = ["Home"]

        req_ids = [item["id"] for item in requirements]
        evidence_ids = [item["id"] for item in research]
        page_requirements = {name: [] for name in page_names}
        for idx, item in enumerate(requirements):
            target = page_names[idx % len(page_names)]
            page_requirements[target].append(item["id"])

        pages = []
        for idx, name in enumerate(page_names):
            is_primary = idx == 0
            pages.append({
                "id": self._slug(name),
                "name": name,
                "purpose": f"Support {intent.get('business_or_product_goal') or 'the project goal'} through a clear {name.casefold()} experience.",
                "primary_user_goal": intent.get("primary_audience") and f"Help {intent['primary_audience']} use {name.casefold()} to {action.casefold()}" or f"Help users use {name.casefold()} to {action.casefold()}",
                "primary_action": action if is_primary else f"Continue toward: {action}",
                "sections": ["Orientation", "Primary task content", "Next step"],
                "requirements": page_requirements[name],
                "research_evidence": evidence_ids,
                "responsive_notes": ["Preserve task order and essential content across viewport sizes; validate breakpoint behavior during wireframing."],
                "accessibility_notes": ["Use semantic landmarks and headings; requires keyboard and screen-reader validation."],
                "rationale": f"Included from the current intent or its required features. Direction '{direction['name']}' informs the page's information hierarchy.",
            })

        nav = self._unique_strings(page_names)
        flow_steps = ["Enter through a relevant page", "Review the information needed to decide", f"Take the primary action: {action}"]
        user_flows = [{
            "id": "primary-user-action",
            "name": "Primary user action",
            "goal": action,
            "entry_points": nav[:3],
            "steps": flow_steps,
            "success_state": f"The user can confirm completion of: {action}.",
            "failure_states": ["Required information is missing", "The primary action cannot be completed", "A dependent service is unavailable"],
            "edge_cases": ["Keyboard-only use", "Small viewport", "Empty or invalid input", "Interrupted task and return"],
            "requirements": req_ids,
            "rationale": "Centers the primary action while exposing likely failure and recovery points for later design validation.",
        }]

        count_by_category = Counter(item["category"] for item in requirements)
        shared = ["Primary navigation", "Page heading", "Primary action", "Feedback message"]
        if len(page_names) > 1:
            shared.extend(["Breadcrumb or location indicator", "Consistent page footer"])
        color_roles = {role: None for role in ("color.background", "color.surface", "color.text.primary", "color.text.secondary", "color.border", "color.accent")}
        supplied_visual = " ".join(intent.get("visual_preferences", []))
        if supplied_visual:
            color_roles["color.accent"] = f"Resolve from user-stated visual direction: {supplied_visual}"

        laws_considered = [{"id": law["id"], "law": law["rule"], "consideration": "Preserve as an authoritative constraint during detailed design.", "conflict": "No conflict can be determined at the planning stage; review against the eventual wireframe."} for law in laws]
        mappings = []
        for item in requirements:
            mappings.append({
                "requirement_id": item["id"],
                "design_decision": f"Allocate '{item['requirement']}' to the page and flow plan for later validation.",
                "coverage": RequirementCoverage.PARTIALLY_COVERED,
                "notes": "Planning-level mapping only; no wireframe or interaction has been validated.",
            })
        research_mapping = [{
            "evidence_id": item["id"],
            "design_decision": "Keep the cited finding available when reviewing page structure and user-flow assumptions.",
            "influence": item["claim"],
            "confidence": float(item.get("confidence") if item.get("confidence") is not None else 0.5),
        } for item in research]

        risks = []
        if not intent.get("primary_audience"):
            risks.append(self._risk("Primary audience is unresolved", "Audience needs may change navigation and content priority", "Ask the user to confirm the audience before wireframing", "intent.primary_audience"))
        if not intent.get("content_requirements"):
            risks.append(self._risk("Content requirements are incomplete", "Page sections may require rework when real content is known", "Confirm required content and assets during wireframe review", "intent.content_requirements"))
        if not intent.get("desired_user_action"):
            risks.append(self._risk("Primary user action is unclear", "Flow and call-to-action decisions may be provisional", "Clarify the intended outcome before approving a plan", "intent.desired_user_action"))
        if not research:
            risks.append(self._risk("No trusted research evidence is available", "Planning choices rely on the user brief and direction only", "Add and review relevant evidence before treating assumptions as validated", "research"))
        for law in laws:
            text = (law["rule"] + " " + direction.get("description", "")).casefold()
            if any(term in text for term in ("no navigation", "without navigation", "no text")):
                risks.append(self._risk(f"Potential design-law conflict: {law['title']}", "A constraint may conflict with basic wayfinding or legibility", "Keep the law unchanged and resolve the conflict with the user", f"design_law:{law['id']}"))

        unresolved = [{
            "question_id": item["id"],
            "impact": item["priority"],
            "effect": f"{item['question']} may affect page structure, content order, or the primary flow.",
        } for item in questions]
        assumptions = []
        if not research:
            assumptions.append("No research findings are treated as evidence; the plan remains a structured hypothesis.")
        if not intent.get("required_pages"):
            assumptions.append("Pages are an initial information-architecture proposal inferred from stated features and action.")

        output = {
            "project_context": {**context["project_context"], "project_type": intent.get("project_type"), "primary_audience": intent.get("primary_audience")},
            "information_architecture": {
                "primary_navigation": nav,
                "secondary_navigation": [],
                "pages": page_names,
                "hierarchy": ["Primary user goal", "Required information", "Supporting detail", "Next action"],
                "content_groups": self._unique_strings(intent.get("content_requirements", []) + intent.get("required_features", [])),
                "rationale": f"The proposed structure supports the active intent revision and selected '{direction['name']}' direction.",
            },
            "pages": pages,
            "user_flows": user_flows,
            "layout_strategy": {
                "page_shell": direction.get("layout_direction") or "Use a consistent page shell; refine geometry during wireframing.",
                "grid": "Use a flexible content grid; exact columns remain unresolved until content and viewport needs are reviewed.",
                "spacing": "Use a consistent semantic spacing scale; exact values remain unresolved.",
                "content_width": "Constrain reading content for legibility; verify with representative content.",
                "hierarchy": ["Page purpose", "Primary content", "Primary action", "Supporting content"],
                "density": direction.get("visual_language", {}).get("density", "Unresolved; derive from content and direction review."),
                "responsive_behavior": ["Reflow content without hiding required tasks", "Validate navigation and reading order at narrow widths"],
                "rationale": "Defines planning principles without specifying rendered layouts.",
            },
            "component_strategy": {
                "shared_components": shared,
                "page_specific_components": {page["name"]: ["Page-specific content sections", "Contextual primary action"] for page in pages},
                "component_states": ["default", "focus", "disabled", "loading", "success", "error", "empty"],
                "composition_rules": ["Keep the primary action visually and semantically clear", "Keep content structure consistent across pages"],
                "reuse_rules": [f"Share components repeated across {len(page_names)} planned pages"],
                "rationale": f"Categories are inferred from repeated needs; requirement category counts: {dict(count_by_category)}.",
            },
            "design_token_strategy": {
                "color_roles": color_roles,
                "typography_roles": {"type.display": "Unresolved", "type.heading": "Unresolved", "type.body": "Unresolved", "type.label": "Unresolved"},
                "spacing_scale": ["space.1", "space.2", "space.3", "space.4", "space.6", "space.8"],
                "radius_strategy": "Use semantic radius roles; values remain unresolved pending the selected direction and component review.",
                "elevation_strategy": "Use elevation only when it clarifies hierarchy; verify contrast and layering.",
                "motion_strategy": "Prefer purposeful, brief transitions and honor reduced-motion preferences.",
                "rationale": "Only semantic roles are proposed. No unsupported brand colors or token values are invented.",
            },
            "responsive_strategy": {
                "breakpoints": ["Content-driven breakpoints to be selected after representative content review"],
                "layout_changes": ["Reflow columns and sections based on available width", "Keep essential content visible"],
                "navigation_changes": [direction.get("navigation_direction") or "Select a compact navigation pattern after testing task priorities"],
                "content_priority_changes": ["Preserve primary task and required content before secondary material"],
                "interaction_changes": ["Adapt pointer interactions to keyboard and touch without losing functionality"],
                "rationale": "No device-specific assumptions are made beyond responsive behavior requiring validation.",
            },
            "accessibility_strategy": {
                "keyboard_navigation": ["All actions require keyboard validation", "Provide visible focus indication"],
                "focus_management": ["Keep focus order aligned with visual and semantic order", "Manage focus after navigation and errors"],
                "semantic_structure": ["Use landmarks, headings, labels, and native controls"],
                "contrast": ["Requires contrast verification for final colors and states"],
                "motion_preferences": ["Honor reduced-motion preferences"],
                "touch_targets": ["Requires touch-target validation at intended viewport sizes"],
                "screen_reader_considerations": ["Requires screen-reader validation of names, roles, states, and reading order"],
                "forms": ["Associate labels and instructions with fields", "Identify required fields before submission"],
                "errors": ["Describe errors in text and associate them with affected fields"],
                "rationale": "These are baseline planning considerations, not a claim of WCAG conformance.",
            },
            "interaction_strategy": {
                "primary_interactions": [action],
                "feedback_patterns": ["Confirm completed actions", "Explain changes and next steps"],
                "loading_states": ["Explain long-running work and preserve user context"],
                "empty_states": ["Explain why no content is present and offer a relevant next step"],
                "error_states": ["Explain the issue and offer a recovery path"],
                "success_states": ["Confirm success and make the resulting state clear"],
                "motion_rules": ["Do not rely on motion alone to communicate state", "Honor reduced-motion settings"],
                "rationale": "Interaction states make the primary journey and recovery behavior inspectable before wireframing.",
            },
            "content_strategy": {
                "known_content_requirements": intent.get("content_requirements", []),
                "brand_requirements": intent.get("brand_requirements", []),
                "content_gaps": [] if intent.get("content_requirements") else ["Confirm required copy, imagery, and other assets"],
                "guidance": "Keep labels, help text, and content aligned with the user's terminology; validate with actual content.",
            },
            "requirements_mapping": mappings,
            "research_mapping": research_mapping,
            "design_laws_considered": laws_considered,
            "assumptions": assumptions,
            "unresolved_questions": unresolved,
            "risks": risks,
            "tradeoffs": [{"decision": decision, "benefit": benefit, "cost": cost, "affected_area": area} for decision, benefit, cost, area in [
                ("Keep layout geometry unresolved", "Avoid inventing unsupported visual constraints", "Requires later wireframe exploration", "layout"),
                ("Prioritize the primary action in the initial flow", "Makes the stated user outcome explicit", "Secondary tasks may need a separate flow", "user_flows"),
            ]],
            "rationale": "This deterministic planning candidate maps the current intent, selected direction, current requirements, reviewed research, laws, and unresolved questions. It is not an AI-generated or validated visual design.",
            "confidence": max(0.0, min(1.0, 0.35 + (float(intent.get("completeness") or 0.0) * 0.4) + (0.1 if research else 0.0))),
        }
        return DesignPlanOutput.model_validate(output, strict=True).model_dump(mode="json")

    @staticmethod
    def _unique_strings(values: list[Any]) -> list[str]:
        seen = set()
        result = []
        for value in values:
            text = str(value).strip()
            if text and text.casefold() not in seen:
                seen.add(text.casefold())
                result.append(text)
        return result

    @staticmethod
    def _title(text: str) -> str:
        return " ".join(word.capitalize() for word in re.split(r"[\s_-]+", text.strip()) if word)

    @staticmethod
    def _slug(text: str) -> str:
        return re.sub(r"[^a-z0-9]+", "-", text.casefold()).strip("-") or "page"

    @staticmethod
    def _risk(description: str, impact: str, mitigation: str, source: str) -> dict[str, str]:
        return {"description": description, "impact": impact, "mitigation": mitigation, "source": source}
