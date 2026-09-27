"""Persist Build 04 design-plan proposals and bind operations to their sources."""
from alembic import context, op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0004_design_reasoning"
down_revision = "0003_intelligence_runtime"
branch_labels = None
depends_on = None

BUILD04_ENUM_LABELS = ("proposed", "previewed", "approved", "rejected", "superseded")
BUILD04_TABLE = "design_plans"
BUILD04_OPERATION_COLUMNS = ("candidate_id", "direction_id")


def _status_enum():
    return postgresql.ENUM(
        *BUILD04_ENUM_LABELS,
        name="design_plan_status", create_type=False,
    )


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError("BUILD 04 migration requires PostgreSQL")
    plan_status = _status_enum()
    plan_status.create(bind, checkfirst=not context.is_offline_mode())

    op.create_unique_constraint("uq_design_direction_project_id", "design_directions", ["project_id", "id"])
    op.add_column("design_operations", sa.Column("candidate_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("design_operations", sa.Column("direction_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_index("ix_design_operations_candidate_id", "design_operations", ["candidate_id"])
    op.create_index("ix_design_operations_direction_id", "design_operations", ["direction_id"])
    op.create_foreign_key("fk_design_operations_candidate", "design_operations", "ai_output_candidates", ["candidate_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_design_operations_direction", "design_operations", "design_directions", ["direction_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_design_operations_direction_project", "design_operations", "design_directions", ["project_id", "direction_id"], ["project_id", "id"])

    op.create_table(
        BUILD04_TABLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("intent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("project_intents.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("direction_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("design_directions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("candidate_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ai_output_candidates.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", plan_status, nullable=False),
        sa.Column("plan", postgresql.JSONB(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("provenance", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("approved_by", sa.String(200)),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_design_plan_confidence_range"),
        sa.UniqueConstraint("candidate_id", name="uq_design_plan_candidate"),
        sa.ForeignKeyConstraint(["project_id", "intent_id"], ["project_intents.project_id", "project_intents.id"], name="fk_design_plans_intent_revision"),
        sa.ForeignKeyConstraint(["project_id", "direction_id"], ["design_directions.project_id", "design_directions.id"], name="fk_design_plans_direction_project"),
    )
    op.create_index("ix_design_plans_project_id", "design_plans", ["project_id"])
    op.create_index("ix_design_plans_intent_id", "design_plans", ["intent_id"])
    op.create_index("ix_design_plans_direction_id", "design_plans", ["direction_id"])
    op.create_index("ix_design_plans_candidate_id", "design_plans", ["candidate_id"])


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError("BUILD 04 downgrade requires PostgreSQL")
    op.drop_table(BUILD04_TABLE)
    op.drop_constraint("fk_design_operations_direction_project", "design_operations", type_="foreignkey")
    op.drop_constraint("fk_design_operations_direction", "design_operations", type_="foreignkey")
    op.drop_constraint("fk_design_operations_candidate", "design_operations", type_="foreignkey")
    op.drop_index("ix_design_operations_direction_id", table_name="design_operations")
    op.drop_index("ix_design_operations_candidate_id", table_name="design_operations")
    op.drop_column("design_operations", "direction_id")
    op.drop_column("design_operations", "candidate_id")
    op.drop_constraint("uq_design_direction_project_id", "design_directions", type_="unique")
    _status_enum().drop(bind, checkfirst=not context.is_offline_mode())
