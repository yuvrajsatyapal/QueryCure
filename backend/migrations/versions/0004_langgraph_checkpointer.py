"""LangGraph Postgres checkpointer tables in schema `langgraph`, created by the owner.

The checkpointer's own setup() runs DDL, which the restricted app role cannot do. We run the
library's migration list here as the owner instead, and the app gets DML only. A future
langgraph-checkpoint-postgres release that adds migrations needs a new revision calling
_apply_checkpointer_migrations() again (it resumes from checkpoint_migrations).

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-11
"""

from alembic import op
from langgraph.checkpoint.postgres import PostgresSaver

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def _apply_checkpointer_migrations() -> None:
    bind = op.get_bind()
    # CREATE INDEX CONCURRENTLY cannot run inside a transaction.
    with op.get_context().autocommit_block():
        bind.exec_driver_sql("CREATE SCHEMA IF NOT EXISTS langgraph")
        bind.exec_driver_sql("SET search_path TO langgraph")
        try:
            migrations = PostgresSaver.MIGRATIONS
            bind.exec_driver_sql(migrations[0])
            row = bind.exec_driver_sql(
                "SELECT v FROM checkpoint_migrations ORDER BY v DESC LIMIT 1"
            ).fetchone()
            current = -1 if row is None else int(row[0])
            for version in range(current + 1, len(migrations)):
                bind.exec_driver_sql(migrations[version])
                bind.exec_driver_sql(
                    "INSERT INTO checkpoint_migrations (v) VALUES (%s)", (version,)
                )
        finally:
            bind.exec_driver_sql("RESET search_path")


def upgrade() -> None:
    _apply_checkpointer_migrations()
    op.execute("REVOKE CREATE ON SCHEMA langgraph FROM PUBLIC")
    op.execute("GRANT USAGE ON SCHEMA langgraph TO qc_app, qc_retention")
    # Upserts need UPDATE; deleting threads is the retention job's work only.
    op.execute("GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA langgraph TO qc_app")
    op.execute("REVOKE INSERT, UPDATE ON langgraph.checkpoint_migrations FROM qc_app")
    op.execute("GRANT SELECT, DELETE ON ALL TABLES IN SCHEMA langgraph TO qc_retention")


def downgrade() -> None:
    op.execute("DROP SCHEMA IF EXISTS langgraph CASCADE")
