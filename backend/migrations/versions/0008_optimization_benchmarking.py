"""Phase 3: optimization candidates, approval requests, experiments, benchmark runs.

`benchmark_runs` is append-only for qc_app (INSERT/SELECT, no UPDATE/DELETE/locks), like
artifacts and events (DATABASE_DESIGN §5). Rows carry a `phase` (`build`, `measure`, `plan`)
so build costs and plan captures share the idempotent resume key with measured blocks.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-12
"""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

STANDARD_TIMESTAMPS = """
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ,
    deleted_at TIMESTAMPTZ
"""
STANDARD_COLUMNS = f"id UUID PRIMARY KEY DEFAULT uuid_generate_v4(), {STANDARD_TIMESTAMPS}"
MUTABLE = ("optimization_candidates", "approval_requests", "experiments")
TABLES = (*MUTABLE, "benchmark_runs")
_OLD_KINDS = (
    "'query', 'param_sets', 'schema_snapshot', 'plan', 'plan_analyze', 'stats_snapshot', "
    "'workload_snapshot', 'experiment_config', 'agent_output', 'report_json', 'report_md', "
    "'environment', 'replay_manifest'"
)
KINDS = f"{_OLD_KINDS}, 'experiment_result'"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE optimization_candidates (
            {STANDARD_COLUMNS},
            run_id UUID NOT NULL,
            key TEXT NOT NULL CHECK (key ~ '^oc_[0-9a-f]{{12}}$'),
            round INT NOT NULL CHECK (round >= 0),
            kind TEXT NOT NULL CHECK (kind IN (
                'create_index', 'query_rewrite', 'analyze_statistics', 'extended_statistics')),
            addresses_hypotheses TEXT[] NOT NULL CHECK (cardinality(addresses_hypotheses) >= 1),
            ddl TEXT[] NOT NULL DEFAULT '{{}}',
            query_sql TEXT,
            sql_sha256 TEXT NOT NULL,
            rollback_sql TEXT,
            expected_benefit TEXT NOT NULL,
            risks TEXT[] NOT NULL DEFAULT '{{}}',
            estimated_cost JSONB NOT NULL,
            proposed_by TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'proposed' CHECK (status IN (
                'proposed', 'approved', 'declined', 'expired', 'benchmarked', 'verified',
                'rejected', 'inconclusive')),
            verdict_reasons JSONB,
            CHECK ((kind = 'query_rewrite') = (query_sql IS NOT NULL))
        );
        CREATE UNIQUE INDEX idx_optimization_candidates_run_key_unique
            ON optimization_candidates (run_id, key);

        CREATE TABLE approval_requests (
            {STANDARD_COLUMNS},
            run_id UUID NOT NULL,
            user_id UUID NOT NULL,
            round INT NOT NULL CHECK (round >= 0),
            kind TEXT NOT NULL CHECK (kind IN (
                'sandbox_execution', 'production_explain', 'budget_extension')),
            payload JSONB NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN (
                'pending', 'approved', 'partially_approved', 'declined', 'expired')),
            decided_by TEXT,
            decided_at TIMESTAMPTZ,
            expires_at TIMESTAMPTZ NOT NULL,
            decision JSONB,
            CHECK ((status = 'pending') = (decided_at IS NULL))
        );
        CREATE INDEX idx_approval_requests_pending ON approval_requests (run_id)
            WHERE status = 'pending';
        CREATE INDEX idx_approval_requests_expiry ON approval_requests (expires_at)
            WHERE status = 'pending';
        CREATE UNIQUE INDEX idx_approval_requests_run_round_kind_unique
            ON approval_requests (run_id, round, kind);
        CREATE INDEX idx_approval_requests_user_id ON approval_requests (user_id);

        CREATE TABLE experiments (
            {STANDARD_COLUMNS},
            run_id UUID NOT NULL,
            round INT NOT NULL CHECK (round >= 0),
            kind TEXT NOT NULL CHECK (kind IN ('single', 'tournament')),
            status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN (
                'pending', 'provisioning', 'running', 'completed', 'failed', 'cancelled')),
            approval_request_id UUID NOT NULL,
            config_artifact_id UUID NOT NULL,
            result_artifact_id UUID,
            environment JSONB,
            environment_digest TEXT,
            engine_version TEXT NOT NULL,
            row_profile TEXT NOT NULL,
            seed BIGINT NOT NULL,
            replay_of_experiment_id UUID,
            error JSONB,
            started_at TIMESTAMPTZ,
            finished_at TIMESTAMPTZ
        );
        CREATE UNIQUE INDEX idx_experiments_run_round_unique ON experiments (run_id, round)
            WHERE replay_of_experiment_id IS NULL;
        CREATE INDEX idx_experiments_approval_request_id ON experiments (approval_request_id);
        CREATE INDEX idx_experiments_config_artifact_id ON experiments (config_artifact_id);
        CREATE INDEX idx_experiments_result_artifact_id ON experiments (result_artifact_id);
        CREATE INDEX idx_experiments_replay_of ON experiments (replay_of_experiment_id);

        -- Append-only raw evidence. Samples are integer nanoseconds (REPLAY_ENGINE §2.1 rule 4).
        CREATE TABLE benchmark_runs (
            {STANDARD_COLUMNS},
            experiment_id UUID NOT NULL,
            candidate_id UUID,
            arm TEXT NOT NULL,
            param_set TEXT NOT NULL,
            phase TEXT NOT NULL CHECK (phase IN ('build', 'measure', 'plan')),
            block INT NOT NULL CHECK (block >= 0),
            latencies_ns JSONB NOT NULL DEFAULT '[]',
            sample_errors JSONB NOT NULL DEFAULT '[]',
            rows_returned BIGINT,
            result_fingerprint TEXT,
            ordered_fingerprint TEXT,
            truncated BOOLEAN NOT NULL DEFAULT false,
            plan_artifact_id UUID,
            buffers JSONB,
            index_size_bytes BIGINT,
            index_build_ns BIGINT,
            build_error JSONB,
            provenance TEXT NOT NULL CHECK (provenance IN ('measured', 'prerecorded'))
        );
        CREATE UNIQUE INDEX idx_benchmark_runs_block_unique
            ON benchmark_runs (experiment_id, arm, param_set, phase, block);
        CREATE INDEX idx_benchmark_runs_candidate_id ON benchmark_runs (candidate_id);
        CREATE INDEX idx_benchmark_runs_plan_artifact_id ON benchmark_runs (plan_artifact_id);
        """
    )
    # Experiment results (stats + rule verdicts) are stored as one canonical artifact.
    op.execute("ALTER TABLE artifacts DROP CONSTRAINT artifacts_kind_check")
    op.execute(
        f"ALTER TABLE artifacts ADD CONSTRAINT artifacts_kind_check CHECK (kind IN ({KINDS}))"
    )
    for table in MUTABLE:
        op.execute(
            f"CREATE TRIGGER {table}_set_updated_at BEFORE UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
        )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {', '.join(MUTABLE)} TO qc_app")
    op.execute("GRANT SELECT, INSERT ON benchmark_runs TO qc_app")
    op.execute(f"GRANT SELECT, DELETE ON {', '.join(TABLES)} TO qc_retention")


def downgrade() -> None:
    op.execute(f"DROP TABLE IF EXISTS {', '.join(reversed(TABLES))}")
    op.execute("ALTER TABLE artifacts DROP CONSTRAINT artifacts_kind_check")
    op.execute(
        f"ALTER TABLE artifacts ADD CONSTRAINT artifacts_kind_check CHECK (kind IN ({_OLD_KINDS}))"
    )
