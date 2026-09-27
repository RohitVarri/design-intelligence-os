"""BUILD 03 AI runtime, immutable intent revisions, and controlled operations."""
from alembic import op
from alembic import context
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003_intelligence_runtime"
down_revision = "0002_intelligence_foundation"
branch_labels = None
depends_on = None

BUILD_02_EVIDENCE_TRUST = ("authoritative", "reliable", "informational", "experimental", "untrusted")
BUILD_02_OPERATION_ACTOR = ("user", "ai", "system")
BUILD_03_ENUM_ADDITIONS = {"evidence_trust": "reviewed", "operation_actor": "fake_test_actor"}
BUILD_03_NEW_TABLES = frozenset({
    "ai_runs", "ai_output_candidates", "operation_previews", "operation_approvals",
    "audit_events", "research_runs", "research_attempts", "research_results",
})


def _restore_enum(enum_name: str, labels: tuple[str, ...], table: str, column: str,
                  downgraded_values: dict[str, str]) -> None:
    """Replace an enum with the BUILD 02 labels without dropping dependent data."""
    def literal(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    old_type = f"{enum_name}_build03"
    label_sql = ", ".join(literal(label) for label in labels)
    branches = " ".join(
        f"WHEN {literal(old)} THEN {literal(new)}"
        for old, new in downgraded_values.items()
    )
    op.execute(f"ALTER TYPE {enum_name} RENAME TO {old_type}")
    op.execute(f"CREATE TYPE {enum_name} AS ENUM ({label_sql})")
    op.execute(
        f"ALTER TABLE {table} ALTER COLUMN {column} TYPE {enum_name} "
        f"USING (CASE {column}::text {branches} ELSE {column}::text END)::{enum_name}"
    )
    # RESTRICT makes PostgreSQL refuse to drop the old type if any dependent
    # column or other database object was not converted above.
    op.execute(f"DROP TYPE {old_type} RESTRICT")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError("BUILD 03 migration requires PostgreSQL")
    for enum_name, label in BUILD_03_ENUM_ADDITIONS.items():
        op.execute(f"ALTER TYPE {enum_name} ADD VALUE IF NOT EXISTS '{label}'")

    op.add_column("projects", sa.Column("current_intent_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("project_intents", sa.Column("revision_number", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("project_intents", sa.Column("created_by", sa.String(100), nullable=False, server_default="user"))
    op.add_column("project_intents", sa.Column("superseded_by_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("design_operations", sa.Column("intent_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("design_operations", sa.Column("ai_run_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("design_operations", sa.Column("provenance", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.add_column("questions", sa.Column("dependencies", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.add_column("questions", sa.Column("suppression_reason", sa.Text(), nullable=True))
    op.add_column("questions", sa.Column("provenance", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.add_column("questions", sa.Column("confidence", sa.Float(), nullable=True))
    op.add_column("research_evidence", sa.Column("result_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("design_memories", sa.Column("source_operation_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.execute("UPDATE questions SET confidence = 1.0 WHERE confidence IS NULL")
    op.alter_column("questions", "confidence", nullable=False)

    # Register only newly introduced tables from the model metadata. This keeps the
    # initial and BUILD 02 migrations authoritative for their existing tables.
    from app.core.database import Base
    import app.models  # noqa: F401
    if context.is_offline_mode():
        # Offline SQL generation has no catalog to inspect. The revision's
        # explicit table inventory keeps generated DDL deterministic.
        new_tables = [table for table in Base.metadata.sorted_tables if table.name in BUILD_03_NEW_TABLES]
        for table in new_tables:
            table.create(bind=bind, checkfirst=False)
    else:
        existing = set(sa.inspect(bind).get_table_names())
        new_tables = [table for table in Base.metadata.sorted_tables if table.name not in existing]
        Base.metadata.create_all(bind=bind, tables=new_tables, checkfirst=True)

    op.execute("""WITH numbered AS (
        SELECT id, project_id, row_number() OVER (PARTITION BY project_id ORDER BY created_at, id) AS rn
        FROM project_intents
    ) UPDATE project_intents AS i SET revision_number = numbered.rn FROM numbered WHERE i.id = numbered.id""")
    op.execute("""WITH linked AS (
        SELECT id, lead(id) OVER (PARTITION BY project_id ORDER BY revision_number) AS next_id
        FROM project_intents
    ) UPDATE project_intents AS i SET superseded_by_id = linked.next_id FROM linked WHERE i.id = linked.id""")
    op.execute("""UPDATE projects p SET current_intent_id = (
        SELECT i.id FROM project_intents i WHERE i.project_id = p.id ORDER BY i.revision_number DESC LIMIT 1
    )""")
    op.create_unique_constraint("uq_project_intent_revision", "project_intents", ["project_id", "revision_number"])
    op.create_unique_constraint("uq_project_intent_project_id", "project_intents", ["project_id", "id"])
    op.create_check_constraint("ck_intent_revision_positive", "project_intents", "revision_number >= 1")
    op.create_check_constraint("ck_intent_confidence_range", "project_intents", "confidence >= 0 AND confidence <= 1")
    op.create_check_constraint("ck_intent_completeness_range", "project_intents", "completeness >= 0 AND completeness <= 1")
    op.create_check_constraint("ck_question_impact_range", "questions", "impact_score >= 0 AND impact_score <= 100")
    op.create_check_constraint("ck_question_confidence_range", "questions", "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)")
    op.create_foreign_key("fk_project_current_intent_revision", "projects", "project_intents", ["id", "current_intent_id"], ["project_id", "id"])
    op.create_foreign_key("fk_project_intents_superseded_by", "project_intents", "project_intents", ["superseded_by_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_design_operations_intent", "design_operations", "project_intents", ["intent_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_design_operations_intent_revision", "design_operations", "project_intents", ["project_id", "intent_id"], ["project_id", "id"])
    op.create_foreign_key("fk_design_operations_ai_run", "design_operations", "ai_runs", ["ai_run_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_questions_intent_revision", "questions", "project_intents", ["project_id", "intent_id"], ["project_id", "id"])
    op.create_foreign_key("fk_research_plans_intent_revision", "research_plans", "project_intents", ["project_id", "intent_id"], ["project_id", "id"])
    op.create_foreign_key("fk_research_evidence_intent_revision", "research_evidence", "project_intents", ["project_id", "intent_id"], ["project_id", "id"])
    op.create_foreign_key("fk_design_directions_intent_revision", "design_directions", "project_intents", ["project_id", "intent_id"], ["project_id", "id"])
    op.create_foreign_key("fk_design_requirements_intent_revision", "design_requirements", "project_intents", ["project_id", "intent_id"], ["project_id", "id"])
    op.create_foreign_key("fk_research_evidence_result", "research_evidence", "research_results", ["result_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_design_memories_source_operation", "design_memories", "design_operations", ["source_operation_id"], ["id"], ondelete="SET NULL")
    op.create_unique_constraint("uq_design_memory_source_operation", "design_memories", ["source_operation_id"])
    op.execute("""WITH ranked AS (SELECT id, row_number() OVER (PARTITION BY project_id ORDER BY created_at DESC, id DESC) AS rn
        FROM design_directions WHERE status = 'selected') UPDATE design_directions d SET status = 'archived' FROM ranked r WHERE d.id = r.id AND r.rn > 1""")
    op.create_index("uq_direction_one_selected_per_project", "design_directions", ["project_id"], unique=True, postgresql_where=sa.text("status = 'selected'"))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError("BUILD 03 downgrade requires PostgreSQL")
    op.drop_constraint("uq_design_memory_source_operation", "design_memories", type_="unique")
    op.drop_index("uq_direction_one_selected_per_project", table_name="design_directions")
    for name, table in (("fk_design_memories_source_operation", "design_memories"),
                        ("fk_research_evidence_result", "research_evidence"),
                        ("fk_design_operations_ai_run", "design_operations"),
                        ("fk_design_operations_intent", "design_operations"),
                        ("fk_design_operations_intent_revision", "design_operations"),
                        ("fk_questions_intent_revision", "questions"),
                        ("fk_research_plans_intent_revision", "research_plans"),
                        ("fk_research_evidence_intent_revision", "research_evidence"),
                        ("fk_design_directions_intent_revision", "design_directions"),
                        ("fk_design_requirements_intent_revision", "design_requirements"),
                        ("fk_project_current_intent_revision", "projects"),
                        ("fk_project_intents_superseded_by", "project_intents")):
        op.drop_constraint(name, table, type_="foreignkey")
    for table in ("research_results", "research_attempts", "research_runs", "ai_output_candidates",
                  "operation_approvals", "operation_previews", "audit_events", "ai_runs"):
        op.drop_table(table)
    op.drop_constraint("uq_project_intent_project_id", "project_intents", type_="unique")
    op.drop_constraint("uq_project_intent_revision", "project_intents", type_="unique")
    for name, table in (("ck_question_confidence_range", "questions"), ("ck_question_impact_range", "questions"),
                        ("ck_intent_completeness_range", "project_intents"), ("ck_intent_confidence_range", "project_intents"),
                        ("ck_intent_revision_positive", "project_intents")):
        op.drop_constraint(name, table, type_="check")
    for table, column in (("design_memories", "source_operation_id"), ("research_evidence", "result_id"),
                          ("questions", "confidence"), ("questions", "provenance"),
                          ("questions", "suppression_reason"), ("questions", "dependencies"),
                          ("design_operations", "provenance"), ("design_operations", "ai_run_id"),
                          ("design_operations", "intent_id"), ("project_intents", "superseded_by_id"),
                          ("project_intents", "created_by"), ("project_intents", "revision_number"),
                          ("projects", "current_intent_id")):
        op.drop_column(table, column)

    # PostgreSQL cannot remove enum labels in place. Recreate the two types
    # changed by this revision after converting their dependent columns. The
    # explicit USING casts preserve every row; BUILD 03-only values map to the
    # closest BUILD 02 value because that schema cannot represent them.
    # DROP TYPE RESTRICT deliberately fails (and rolls back the migration) if
    # any unhandled database object still depends on the old enum type.
    _restore_enum("evidence_trust", BUILD_02_EVIDENCE_TRUST, "research_evidence", "trust", {"reviewed": "reliable"})
    _restore_enum("operation_actor", BUILD_02_OPERATION_ACTOR, "design_operations", "actor", {"fake_test_actor": "system"})
