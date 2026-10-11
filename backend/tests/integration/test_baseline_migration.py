import psycopg
import pytest

pytestmark = pytest.mark.integration

PHASE1_TABLES = {"users", "sessions", "database_connections", "artifacts", "run_artifacts"}


def test_baseline_creates_phase1_tables(owner: psycopg.Connection) -> None:
    rows = owner.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
    ).fetchall()

    assert {r[0] for r in rows} >= PHASE1_TABLES


def test_no_foreign_keys_and_no_varchar(owner: psycopg.Connection) -> None:
    fks = owner.execute(
        "SELECT count(*) FROM information_schema.table_constraints "
        "WHERE constraint_type = 'FOREIGN KEY' AND table_schema = 'public'"
    ).fetchone()
    varchars = owner.execute(
        "SELECT table_name, column_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND data_type = 'character varying' "
        # Library-managed bookkeeping table, outside ADR-0006 (like LangGraph's checkpoint tables).
        "AND table_name <> 'alembic_version'"
    ).fetchall()

    assert fks == (0,)
    assert varchars == []


def test_standard_columns_and_uuid_defaults(owner: psycopg.Connection) -> None:
    for table in PHASE1_TABLES:
        cols = {
            r[0]: (r[1], r[2])
            for r in owner.execute(
                "SELECT column_name, data_type, column_default FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = %s",
                (table,),
            )
        }
        assert cols["id"][0] == "uuid", table
        assert "uuid_generate_v4()" in (cols["id"][1] or ""), table
        for ts in ("created_at", "updated_at", "deleted_at"):
            assert cols[ts][0] == "timestamp with time zone", (table, ts)


def test_updated_at_trigger_sets_timestamp(owner: psycopg.Connection) -> None:
    user_id = owner.execute(
        "INSERT INTO users (kind, display_name) VALUES ('local', 'dev') RETURNING id"
    ).fetchone()[0]  # type: ignore[index]

    owner.execute("UPDATE users SET display_name = 'renamed' WHERE id = %s", (user_id,))
    updated_at = owner.execute("SELECT updated_at FROM users WHERE id = %s", (user_id,)).fetchone()

    assert updated_at is not None
    assert updated_at[0] is not None


def test_enum_checks_reject_unknown_values(owner: psycopg.Connection) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        owner.execute("INSERT INTO users (kind) VALUES ('admin')")


def test_artifacts_store_exact_bytes_with_profile_and_size_checks(
    owner: psycopg.Connection,
) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        owner.execute(
            "INSERT INTO artifacts (sha256, kind, media_type, content, canonicalization) "
            "VALUES (repeat('a', 64), 'query', 'text/sql', 'SELECT 1', 'json-c14n-v1')"
        )
    with pytest.raises(psycopg.errors.CheckViolation):
        owner.execute(
            "INSERT INTO artifacts (sha256, kind, media_type, content, canonicalization) "
            "VALUES ('not-a-digest', 'query', 'text/sql', 'SELECT 1', 'qc-raw-v1')"
        )


def test_roles_exist(owner: psycopg.Connection) -> None:
    roles = {r[0] for r in owner.execute("SELECT rolname FROM pg_roles WHERE rolname LIKE 'qc_%'")}

    assert {"qc_app", "qc_retention"} <= roles


def test_upgrade_is_idempotent_and_reaches_single_head(migrated_db: str) -> None:
    from pathlib import Path

    from alembic import command
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    backend = Path(__file__).parents[2]
    cfg = Config(str(backend / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend / "migrations"))
    cfg.set_main_option(
        "sqlalchemy.url", migrated_db.replace("postgresql://", "postgresql+psycopg://", 1)
    )

    command.upgrade(cfg, "head")

    assert len(ScriptDirectory.from_config(cfg).get_heads()) == 1
