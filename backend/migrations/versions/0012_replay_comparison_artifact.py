"""Artifact kind `replay_comparison` (REPLAY_ENGINE §9).

The original-vs-replay comparison of an experiment replay is content of the replay run, so
the replay run's report can be rebuilt from its records like any other report.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-13
"""

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

_OLD_KINDS = (
    "'query', 'param_sets', 'schema_snapshot', 'plan', 'plan_analyze', 'stats_snapshot', "
    "'workload_snapshot', 'experiment_config', 'agent_output', 'report_json', 'report_md', "
    "'environment', 'replay_manifest', 'experiment_result', 'replication_result'"
)
KINDS = f"{_OLD_KINDS}, 'replay_comparison'"


def _kind_check(values: str) -> None:
    op.execute("ALTER TABLE artifacts DROP CONSTRAINT artifacts_kind_check")
    op.execute(
        f"ALTER TABLE artifacts ADD CONSTRAINT artifacts_kind_check CHECK (kind IN ({values}))"
    )


def upgrade() -> None:
    _kind_check(KINDS)


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM artifacts WHERE kind = 'replay_comparison') THEN
                RAISE EXCEPTION 'replay comparisons exist; refusing to downgrade 0012';
            END IF;
        END $$;
        """
    )
    _kind_check(_OLD_KINDS)
