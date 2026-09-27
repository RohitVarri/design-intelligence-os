"""BUILD 02 intelligence, research, direction, and operation foundation."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_intelligence_foundation"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

def _enum(name: str, *values: str) -> postgresql.ENUM:
    # Types are created explicitly in upgrade(); suppress implicit duplicate DDL from each table.
    return postgresql.ENUM(*values, name=name, create_type=False)

def upgrade() -> None:
    intent_status = _enum("intent_status", "draft", "needs_questions", "ready_for_research", "researched", "ready_for_direction", "approved")
    question_category = _enum("question_category", "goal", "audience", "content", "functionality", "platform", "branding", "visual", "UX", "accessibility", "technical", "business", "constraints", "references")
    question_priority = _enum("question_priority", "critical", "high", "medium", "low")
    question_status = _enum("question_status", "open", "answered", "skipped", "superseded")
    evidence_source_type = _enum("evidence_source_type", "research_paper", "design_publication", "design_gallery", "pattern_library", "accessibility_standard", "industry_report", "competitor", "website", "documentation", "community", "user_reference", "other")
    trend_stage = _enum("trend_stage", "emerging", "established", "saturated", "declining", "archived", "unknown")
    evidence_trust = _enum("evidence_trust", "authoritative", "reliable", "informational", "experimental", "untrusted")
    research_plan_status = _enum("research_plan_status", "draft", "queued", "running", "completed", "failed")
    research_query_status = _enum("research_query_status", "queued", "running", "completed", "failed", "skipped")
    research_query_priority = _enum("research_query_priority", "critical", "high", "medium", "low")
    requirement_category = _enum("requirement_category", "functional", "UX", "visual", "content", "technical", "accessibility", "performance", "business", "brand", "responsive")
    requirement_source = _enum("requirement_source", "user", "inferred", "research", "system")
    requirement_status = _enum("requirement_status", "proposed", "approved", "rejected", "superseded")
    direction_status = _enum("direction_status", "proposed", "selected", "rejected", "archived")
    assessment_criterion = _enum("assessment_criterion", "audience_fit", "goal_alignment", "brand_alignment", "usability", "differentiation", "accessibility", "performance", "scalability", "implementation_complexity")
    operation_type = _enum("operation_type", "create", "update", "delete", "move", "reorder", "replace", "select_direction", "update_requirement", "update_intent")
    operation_actor = _enum("operation_actor", "user", "ai", "system")
    operation_source = _enum("operation_source", "user_request", "user_answer", "ai_proposal", "research", "imported_reference", "system")
    operation_status = _enum("operation_status", "proposed", "validated", "previewed", "approved", "applied", "rejected")
    for enum in (intent_status, question_category, question_priority, question_status, evidence_source_type, trend_stage, evidence_trust, research_plan_status, research_query_status, research_query_priority, requirement_category, requirement_source, requirement_status, direction_status, assessment_criterion, operation_type, operation_actor, operation_source, operation_status):
        enum.create(op.get_bind(), checkfirst=True)

    op.add_column("design_memories", sa.Column("provenance", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.add_column("design_decisions", sa.Column("provenance", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")))

    op.create_table("project_intents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("raw_request", sa.Text(), nullable=False), sa.Column("project_type", sa.String(200)),
        sa.Column("business_or_product_goal", sa.Text()), sa.Column("primary_audience", sa.Text()), sa.Column("secondary_audience", sa.Text()),
        sa.Column("primary_user_tasks", postgresql.JSONB(), nullable=False), sa.Column("desired_user_action", sa.Text()),
        sa.Column("industry", sa.String(200)), sa.Column("platform", sa.String(100)),
        sa.Column("target_devices", postgresql.JSONB(), nullable=False), sa.Column("required_pages", postgresql.JSONB(), nullable=False),
        sa.Column("required_features", postgresql.JSONB(), nullable=False), sa.Column("content_requirements", postgresql.JSONB(), nullable=False),
        sa.Column("brand_requirements", postgresql.JSONB(), nullable=False), sa.Column("visual_preferences", postgresql.JSONB(), nullable=False),
        sa.Column("functional_requirements", postgresql.JSONB(), nullable=False), sa.Column("technical_requirements", postgresql.JSONB(), nullable=False),
        sa.Column("accessibility_requirements", postgresql.JSONB(), nullable=False), sa.Column("performance_requirements", postgresql.JSONB(), nullable=False),
        sa.Column("constraints", postgresql.JSONB(), nullable=False), sa.Column("references", postgresql.JSONB(), nullable=False),
        sa.Column("competitors", postgresql.JSONB(), nullable=False), sa.Column("success_criteria", postgresql.JSONB(), nullable=False),
        sa.Column("budget_or_resource_constraints", sa.Text()), sa.Column("timeline_constraints", sa.Text()),
        sa.Column("confidence", sa.Float(), nullable=False), sa.Column("completeness", sa.Float(), nullable=False),
        sa.Column("provenance", postgresql.JSONB(), nullable=False), sa.Column("status", intent_status, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_project_intents_project_id", "project_intents", ["project_id"])

    op.create_table("questions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("intent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("project_intents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("question", sa.Text(), nullable=False), sa.Column("category", question_category, nullable=False),
        sa.Column("priority", question_priority, nullable=False), sa.Column("impact", sa.Text(), nullable=False),
        sa.Column("impact_score", sa.Float(), nullable=False), sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("answer_type", sa.String(40), nullable=False), sa.Column("options", postgresql.JSONB(), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False), sa.Column("status", question_status, nullable=False),
        sa.Column("answer", postgresql.JSONB()), sa.Column("intent_field", sa.String(100)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("answered_at", sa.DateTime(timezone=True)))
    op.create_index("ix_questions_project_id", "questions", ["project_id"])
    op.create_index("ix_questions_intent_id", "questions", ["intent_id"])

    op.create_table("research_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("intent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("project_intents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", research_plan_status, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_research_plans_project_id", "research_plans", ["project_id"])
    op.create_index("ix_research_plans_intent_id", "research_plans", ["intent_id"])

    op.create_table("research_queries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("research_plans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("query", sa.Text(), nullable=False), sa.Column("research_area", sa.String(200), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False), sa.Column("priority", research_query_priority, nullable=False),
        sa.Column("status", research_query_status, nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_research_queries_plan_id", "research_queries", ["plan_id"])

    op.create_table("research_evidence",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("intent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("project_intents.id", ondelete="SET NULL")),
        sa.Column("title", sa.String(500), nullable=False), sa.Column("claim", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text()), sa.Column("source_name", sa.String(300)), sa.Column("source_type", evidence_source_type, nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)), sa.Column("retrieved_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("industry", sa.String(200)), sa.Column("audience", sa.Text()), sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("relevance", sa.Float()), sa.Column("confidence", sa.Float()), sa.Column("trend_stage", trend_stage, nullable=False),
        sa.Column("tags", postgresql.JSONB(), nullable=False), sa.Column("related_requirement", sa.Text()),
        sa.Column("provenance", postgresql.JSONB(), nullable=False), sa.Column("trust", evidence_trust, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_research_evidence_project_id", "research_evidence", ["project_id"])
    op.create_index("ix_research_evidence_intent_id", "research_evidence", ["intent_id"])

    op.create_table("design_requirements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("intent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("project_intents.id", ondelete="SET NULL")),
        sa.Column("requirement", sa.Text(), nullable=False), sa.Column("category", requirement_category, nullable=False),
        sa.Column("priority", sa.String(20), nullable=False), sa.Column("source", requirement_source, nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False), sa.Column("status", requirement_status, nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False), sa.Column("provenance", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_design_requirements_project_id", "design_requirements", ["project_id"])
    op.create_index("ix_design_requirements_intent_id", "design_requirements", ["intent_id"])

    op.create_table("design_directions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("intent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("project_intents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False), sa.Column("description", sa.Text(), nullable=False),
        sa.Column("visual_language", postgresql.JSONB(), nullable=False), sa.Column("typography_direction", sa.Text()),
        sa.Column("color_direction", sa.Text()), sa.Column("layout_direction", sa.Text()), sa.Column("navigation_direction", sa.Text()),
        sa.Column("imagery_direction", sa.Text()), sa.Column("motion_direction", sa.Text()), sa.Column("component_direction", sa.Text()),
        sa.Column("density", sa.String(80)), sa.Column("emotional_tone", postgresql.JSONB(), nullable=False),
        sa.Column("target_audience_fit", sa.Text()), sa.Column("strengths", postgresql.JSONB(), nullable=False),
        sa.Column("tradeoffs", postgresql.JSONB(), nullable=False), sa.Column("risks", postgresql.JSONB(), nullable=False),
        sa.Column("supporting_research_ids", postgresql.JSONB(), nullable=False), sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("provenance", postgresql.JSONB(), nullable=False), sa.Column("status", direction_status, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_design_directions_project_id", "design_directions", ["project_id"])
    op.create_index("ix_design_directions_intent_id", "design_directions", ["intent_id"])

    op.create_table("design_direction_assessments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("direction_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("design_directions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("criterion", assessment_criterion, nullable=False), sa.Column("observation", sa.Text(), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False), sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("tradeoff", sa.Text(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_design_direction_assessments_direction_id", "design_direction_assessments", ["direction_id"])

    op.create_table("design_operations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("operation_type", operation_type, nullable=False), sa.Column("actor", operation_actor, nullable=False),
        sa.Column("target", sa.String(500), nullable=False), sa.Column("property", sa.String(500)),
        sa.Column("old_value", postgresql.JSONB()), sa.Column("new_value", postgresql.JSONB()),
        sa.Column("scope", sa.String(100), nullable=False), sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("source", operation_source, nullable=False), sa.Column("status", operation_status, nullable=False),
        sa.Column("parent_operation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("design_operations.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_design_operations_project_id", "design_operations", ["project_id"])

def downgrade() -> None:
    for table in ("design_operations", "design_direction_assessments", "design_directions", "design_requirements", "research_evidence", "research_queries", "research_plans", "questions", "project_intents"):
        op.drop_table(table)
    op.drop_column("design_decisions", "provenance")
    op.drop_column("design_memories", "provenance")
    for name in ("operation_status", "operation_source", "operation_actor", "operation_type", "assessment_criterion", "direction_status", "requirement_status", "requirement_source", "requirement_category", "research_query_priority", "research_query_status", "research_plan_status", "evidence_trust", "trend_stage", "evidence_source_type", "question_status", "question_priority", "question_category", "intent_status"):
        _enum(name).drop(op.get_bind(), checkfirst=True)
