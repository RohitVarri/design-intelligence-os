"""Persist BUILD 05 wireframe candidates and their approved artifacts."""
from alembic import context, op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0005_wireframe_intelligence"
down_revision = "0004_design_reasoning"
branch_labels = None
depends_on = None

WIREFRAME_STATUSES = ("proposed", "previewed", "approved", "rejected", "superseded")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError("BUILD 05 migration requires PostgreSQL")
    status = postgresql.ENUM(*WIREFRAME_STATUSES, name="wireframe_set_status", create_type=False)
    status.create(bind, checkfirst=not context.is_offline_mode())
    op.create_unique_constraint("uq_design_plan_project_id", "design_plans", ["project_id", "id"])
    op.create_table(
        "wireframe_sets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("design_plan_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("design_plans.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("intent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("project_intents.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("direction_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("design_directions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("candidate_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ai_output_candidates.id", ondelete="SET NULL")),
        sa.Column("status", status, nullable=False),
        sa.Column("wireframe", postgresql.JSONB(), nullable=False),
        sa.Column("provenance", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("approved_by", sa.String(200)),
        sa.ForeignKeyConstraint(["project_id", "design_plan_id"], ["design_plans.project_id", "design_plans.id"], name="fk_wireframe_sets_plan_project"),
        sa.ForeignKeyConstraint(["project_id", "intent_id"], ["project_intents.project_id", "project_intents.id"], name="fk_wireframe_sets_intent_revision"),
        sa.ForeignKeyConstraint(["project_id", "direction_id"], ["design_directions.project_id", "design_directions.id"], name="fk_wireframe_sets_direction_project"),
        sa.UniqueConstraint("candidate_id", name="uq_wireframe_set_candidate"),
    )
    for column in ("project_id", "design_plan_id", "intent_id", "direction_id", "candidate_id"):
        op.create_index(f"ix_wireframe_sets_{column}", "wireframe_sets", [column])


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError("BUILD 05 downgrade requires PostgreSQL")
    op.drop_table("wireframe_sets")
    op.drop_constraint("uq_design_plan_project_id", "design_plans", type_="unique")
    status = postgresql.ENUM(*WIREFRAME_STATUSES, name="wireframe_set_status", create_type=False)
    status.drop(bind, checkfirst=not context.is_offline_mode())
