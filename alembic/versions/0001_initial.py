"""Initial DesignOS foundation tables."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table("projects",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False), sa.Column("description", sa.String(2000)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_table("design_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("parent_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("design_versions.id", ondelete="SET NULL")),
        sa.Column("state", postgresql.JSONB(), nullable=False), sa.Column("change_summary", sa.String(2000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("project_id", "version_number", name="uq_project_version_number"))
    op.create_index("ix_design_versions_project_id", "design_versions", ["project_id"])
    op.create_table("design_states",
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("state", postgresql.JSONB(), nullable=False),
        sa.Column("current_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("design_versions.id", name="fk_design_state_current_version", ondelete="SET NULL")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_table("design_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", sa.Enum("user", "ai", "research", "imported_reference", "system", name="decision_source", values_callable=lambda e: [x.value for x in e]), nullable=False),
        sa.Column("title", sa.String(300), nullable=False), sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_design_decisions_project_id", "design_decisions", ["project_id"])
    op.create_table("design_laws",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(300), nullable=False), sa.Column("rule", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_design_laws_project_id", "design_laws", ["project_id"])
    op.create_table("design_memories",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category", sa.String(100), nullable=False), sa.Column("content", sa.Text(), nullable=False),
        sa.Column("trust", sa.Enum("user_approved", "ai_suggestion", "imported_untrusted", name="memory_trust", values_callable=lambda e: [x.value for x in e]), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_design_memories_project_id", "design_memories", ["project_id"])

def downgrade() -> None:
    for table in ("design_memories", "design_laws", "design_decisions", "design_states", "design_versions"):
        op.drop_table(table)
    op.drop_table("projects")
    sa.Enum(name="memory_trust").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="decision_source").drop(op.get_bind(), checkfirst=True)
