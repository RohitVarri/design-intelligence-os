"""Focused checks for the BUILD 03 PostgreSQL enum downgrade strategy."""
import importlib.util
from pathlib import Path


MIGRATION_PATH = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "0003_intelligence_runtime.py"
SPEC = importlib.util.spec_from_file_location("build03_migration", MIGRATION_PATH)
migration = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(migration)


def test_build03_migration_extends_only_the_two_expected_build02_enums():
    assert migration.revision == "0003_intelligence_runtime"
    assert migration.down_revision == "0002_intelligence_foundation"
    assert migration.BUILD_02_EVIDENCE_TRUST == (
        "authoritative", "reliable", "informational", "experimental", "untrusted"
    )
    assert migration.BUILD_02_OPERATION_ACTOR == ("user", "ai", "system")
    assert migration.BUILD_03_ENUM_ADDITIONS == {
        "evidence_trust": "reviewed",
        "operation_actor": "fake_test_actor",
    }


def test_enum_restore_recreates_labels_casts_data_and_uses_restrict(monkeypatch):
    sql = []
    monkeypatch.setattr(migration.op, "execute", sql.append)

    migration._restore_enum(
        "evidence_trust", migration.BUILD_02_EVIDENCE_TRUST,
        "research_evidence", "trust", {"reviewed": "reliable"},
    )

    rendered = "\n".join(str(statement) for statement in sql)
    assert "ALTER TYPE evidence_trust RENAME TO evidence_trust_build03" in rendered
    assert "CREATE TYPE evidence_trust AS ENUM ('authoritative', 'reliable', 'informational', 'experimental', 'untrusted')" in rendered
    assert "WHEN 'reviewed' THEN 'reliable'" in rendered
    assert "ALTER TABLE research_evidence ALTER COLUMN trust TYPE evidence_trust" in rendered
    assert "DROP TYPE evidence_trust_build03 RESTRICT" in rendered


def test_operation_actor_restore_preserves_rows_with_build02_actor_label(monkeypatch):
    sql = []
    monkeypatch.setattr(migration.op, "execute", sql.append)

    migration._restore_enum(
        "operation_actor", migration.BUILD_02_OPERATION_ACTOR,
        "design_operations", "actor", {"fake_test_actor": "system"},
    )

    rendered = "\n".join(str(statement) for statement in sql)
    assert "WHEN 'fake_test_actor' THEN 'system'" in rendered
    assert "DROP TYPE operation_actor_build03 RESTRICT" in rendered
