"""BUILD 04 migration lineage and relational invariant checks."""
import importlib.util
from pathlib import Path

from app.models.design_plan import DesignPlan
from app.models.direction import DesignDirection
from app.models.operation import DesignOperation


MIGRATION_PATH = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "0004_design_reasoning.py"
SPEC = importlib.util.spec_from_file_location("build04_migration", MIGRATION_PATH)
migration = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(migration)


def test_build04_migration_follows_build03_and_adds_only_plan_status_labels():
    assert migration.revision == "0004_design_reasoning"
    assert migration.down_revision == "0003_intelligence_runtime"
    assert migration.BUILD04_ENUM_LABELS == ("proposed", "previewed", "approved", "rejected", "superseded")
    assert migration.BUILD04_TABLE == "design_plans"
    assert migration.BUILD04_OPERATION_COLUMNS == ("candidate_id", "direction_id")


def test_plan_and_operation_models_enforce_project_scoped_intent_and_direction_links():
    plan_constraints = {constraint.name for constraint in DesignPlan.__table__.constraints}
    operation_constraints = {constraint.name for constraint in DesignOperation.__table__.constraints}
    direction_constraints = {constraint.name for constraint in DesignDirection.__table__.constraints}
    assert "fk_design_plans_intent_revision" in plan_constraints
    assert "fk_design_plans_direction_project" in plan_constraints
    assert "fk_design_operations_direction_project" in operation_constraints
    assert "uq_design_direction_project_id" in direction_constraints
    assert {"candidate_id", "direction_id"} <= set(DesignOperation.__table__.columns.keys())


def test_plan_table_keeps_required_persistence_and_approval_fields():
    columns = set(DesignPlan.__table__.columns.keys())
    assert {
        "id", "project_id", "intent_id", "direction_id", "status", "plan", "confidence",
        "provenance", "created_at", "updated_at", "approved_at", "approved_by",
    } <= columns
