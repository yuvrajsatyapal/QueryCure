"""bench@2 replicates (ADR-0019): independent re-measurements of a noisy round.

Expand-only:
- `experiments.replicate` (0 = the approved experiment; existing rows stay 0) and the
  round uniqueness moves to (run_id, round, replicate);
- `experiments.replication_artifact_id` on the replicate-0 row points at the replication
  verdicts;
- candidate status gains `verified_with_noise_warning`;
- artifact kind gains `replication_result`.
The downgrade refuses to run while any new value is present.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-12
"""

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

_OLD_KINDS = (
    "'query', 'param_sets', 'schema_snapshot', 'plan', 'plan_analyze', 'stats_snapshot', "
    "'workload_snapshot', 'experiment_config', 'agent_output', 'report_json', 'report_md', "
    "'environment', 'replay_manifest', 'experiment_result'"
)
KINDS = f"{_OLD_KINDS}, 'replication_result'"
_OLD_STATUSES = (
    "'proposed', 'approved', 'declined', 'expired', 'benchmarked', 'verified', 'rejected', "
    "'inconclusive'"
)
STATUSES = f"{_OLD_STATUSES}, 'verified_with_noise_warning'"


def _status_check(values: str) -> None:
    op.execute(
        "ALTER TABLE optimization_candidates DROP CONSTRAINT optimization_candidates_status_check"
    )
    op.execute(
        "ALTER TABLE optimization_candidates ADD CONSTRAINT optimization_candidates_status_check "
        f"CHECK (status IN ({values}))"
    )


def _kind_check(values: str) -> None:
    op.execute("ALTER TABLE artifacts DROP CONSTRAINT artifacts_kind_check")
    op.execute(
        f"ALTER TABLE artifacts ADD CONSTRAINT artifacts_kind_check CHECK (kind IN ({values}))"
    )


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE experiments
            ADD COLUMN replicate INT NOT NULL DEFAULT 0 CHECK (replicate >= 0),
            ADD COLUMN replication_artifact_id UUID;
        DROP INDEX idx_experiments_run_round_unique;
        CREATE UNIQUE INDEX idx_experiments_run_round_replicate_unique
            ON experiments (run_id, round, replicate) WHERE replay_of_experiment_id IS NULL;
        CREATE INDEX idx_experiments_replication_artifact_id
            ON experiments (replication_artifact_id);
        """
    )
    _status_check(STATUSES)
    _kind_check(KINDS)


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM experiments WHERE replicate > 0
                                                  OR replication_artifact_id IS NOT NULL)
               OR EXISTS (SELECT 1 FROM optimization_candidates
                          WHERE status = 'verified_with_noise_warning')
               OR EXISTS (SELECT 1 FROM artifacts WHERE kind = 'replication_result') THEN
                RAISE EXCEPTION 'bench@2 replicates exist; refusing to downgrade 0010';
            END IF;
        END $$;
        """
    )
    _kind_check(_OLD_KINDS)
    _status_check(_OLD_STATUSES)
    op.execute(
        """
        DROP INDEX idx_experiments_replication_artifact_id;
        DROP INDEX idx_experiments_run_round_replicate_unique;
        CREATE UNIQUE INDEX idx_experiments_run_round_unique ON experiments (run_id, round)
            WHERE replay_of_experiment_id IS NULL;
        ALTER TABLE experiments DROP COLUMN replication_artifact_id, DROP COLUMN replicate;
        """
    )
