"""Phase 2: investigations, runs, events, agent/tool executions, evidence, findings, hypotheses, jobs.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-11
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

STANDARD_TIMESTAMPS = """
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ,
    deleted_at TIMESTAMPTZ
"""
STANDARD_COLUMNS = f"id UUID PRIMARY KEY DEFAULT uuid_generate_v4(), {STANDARD_TIMESTAMPS}"

TABLES = (
    "investigations",
    "investigation_runs",
    "investigation_events",
    "agent_executions",
    "tool_executions",
    "evidence",
    "findings",
    "hypotheses",
    "jobs",
)


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE investigations (
            {STANDARD_COLUMNS},
            user_id UUID NOT NULL,
            title TEXT NOT NULL CHECK (char_length(title) BETWEEN 1 AND 200),
            objective TEXT NOT NULL CHECK (char_length(objective) <= 2000),
            modes TEXT[] NOT NULL CHECK (
                cardinality(modes) >= 1
                AND modes <@ ARRAY['offline', 'live_inspection', 'sandbox_benchmark']),
            connection_id UUID,
            workload_id TEXT,
            query_artifact_id UUID,
            latest_run_id UUID,
            latest_outcome TEXT
        );
        CREATE INDEX idx_investigations_user_created ON investigations (user_id, created_at DESC, id DESC)
            WHERE deleted_at IS NULL;
        CREATE INDEX idx_investigations_connection_id ON investigations (connection_id);
        CREATE INDEX idx_investigations_query_artifact_id ON investigations (query_artifact_id);
        CREATE INDEX idx_investigations_latest_run_id ON investigations (latest_run_id);

        CREATE TABLE investigation_runs (
            {STANDARD_COLUMNS},
            investigation_id UUID NOT NULL,
            run_number INT NOT NULL CHECK (run_number >= 1),
            kind TEXT NOT NULL CHECK (kind IN ('initial', 'reinvestigation', 'experiment_replay')),
            parent_run_id UUID,
            status TEXT NOT NULL CHECK (status IN (
                'queued', 'running', 'awaiting_approval', 'cancelling', 'completed', 'failed',
                'cancelled')),
            outcome TEXT CHECK (outcome IN (
                'verified_recommendation', 'unverified_recommendations', 'no_action_needed',
                'inconclusive')),
            llm_provider TEXT,
            llm_model TEXT,
            budget JSONB NOT NULL,
            usage JSONB NOT NULL,
            cancel_requested_at TIMESTAMPTZ,
            started_at TIMESTAMPTZ,
            finished_at TIMESTAMPTZ,
            error JSONB,
            idempotency_key TEXT,
            idempotency_request_hash TEXT,
            last_event_seq INT NOT NULL DEFAULT 0 CHECK (last_event_seq >= 0),
            finalized_at TIMESTAMPTZ,
            events_cutoff_seq INT,
            CHECK ((outcome IS NULL) OR (status = 'completed')),
            CHECK ((idempotency_key IS NULL) = (idempotency_request_hash IS NULL))
        );
        CREATE UNIQUE INDEX idx_investigation_runs_number_unique
            ON investigation_runs (investigation_id, run_number);
        CREATE INDEX idx_investigation_runs_active ON investigation_runs (status)
            WHERE status IN ('queued', 'running', 'awaiting_approval', 'cancelling');
        CREATE UNIQUE INDEX idx_investigation_runs_idempotency_key_unique
            ON investigation_runs (idempotency_key) WHERE idempotency_key IS NOT NULL;
        CREATE INDEX idx_investigation_runs_parent_run_id ON investigation_runs (parent_run_id);

        -- Append-only event log. seq is assigned under the run row lock (DATABASE_DESIGN §4).
        CREATE TABLE investigation_events (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            {STANDARD_TIMESTAMPS},
            run_id UUID NOT NULL,
            seq INT NOT NULL CHECK (seq >= 1),
            type TEXT NOT NULL CHECK (type ~ '^[a-z_]+(\\.[a-z_]+)?$'),
            payload JSONB NOT NULL
        );
        CREATE UNIQUE INDEX idx_investigation_events_run_seq_unique ON investigation_events (run_id, seq);

        CREATE TABLE agent_executions (
            {STANDARD_COLUMNS},
            run_id UUID NOT NULL,
            agent TEXT NOT NULL,
            node TEXT NOT NULL,
            invocation_key TEXT NOT NULL,
            attempt INT NOT NULL CHECK (attempt >= 1),
            prompt_version TEXT NOT NULL,
            model TEXT NOT NULL,
            input_tokens INT,
            output_tokens INT,
            latency_ms INT,
            status TEXT NOT NULL CHECK (status IN ('succeeded', 'failed', 'invalid_output')),
            output_artifact_id UUID,
            error JSONB
        );
        CREATE INDEX idx_agent_executions_run_id ON agent_executions (run_id);
        CREATE INDEX idx_agent_executions_output_artifact_id ON agent_executions (output_artifact_id);
        -- At most one successful execution per invocation: a node re-run after a crash reuses it
        -- instead of calling the LLM again (AGENT_SYSTEM §7 idempotency).
        CREATE UNIQUE INDEX idx_agent_executions_succeeded_unique
            ON agent_executions (run_id, invocation_key) WHERE status = 'succeeded';

        CREATE TABLE tool_executions (
            {STANDARD_COLUMNS},
            agent_execution_id UUID NOT NULL,
            run_id UUID NOT NULL,
            tool TEXT NOT NULL,
            args JSONB NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('ok', 'error', 'refused')),
            latency_ms INT,
            evidence_ids TEXT[] NOT NULL DEFAULT '{{}}',
            error JSONB
        );
        CREATE INDEX idx_tool_executions_run_id ON tool_executions (run_id);
        CREATE INDEX idx_tool_executions_agent_execution_id ON tool_executions (agent_execution_id);

        CREATE TABLE evidence (
            id TEXT NOT NULL CHECK (id ~ '^ev_[0-9a-f]{{12}}$'),
            {STANDARD_TIMESTAMPS},
            run_id UUID NOT NULL,
            kind TEXT NOT NULL CHECK (kind IN (
                'plan_node', 'plan_summary', 'table_stat', 'column_stat', 'index_def',
                'schema_fact', 'query_fact', 'workload_stat', 'lock_sample', 'benchmark_metric',
                'correctness_check', 'tool_error', 'user_input')),
            artifact_id UUID,
            locator TEXT NOT NULL,
            summary TEXT NOT NULL CHECK (char_length(summary) <= 300),
            data JSONB NOT NULL,
            provenance TEXT NOT NULL CHECK (provenance IN ('measured', 'prerecorded', 'imported', 'derived')),
            PRIMARY KEY (run_id, id)
        );
        CREATE INDEX idx_evidence_artifact_id ON evidence (artifact_id);

        CREATE TABLE findings (
            {STANDARD_COLUMNS},
            run_id UUID NOT NULL,
            key TEXT NOT NULL CHECK (key ~ '^fd_[0-9a-f]{{12}}$'),
            agent TEXT NOT NULL,
            title TEXT NOT NULL,
            detail TEXT NOT NULL,
            severity TEXT NOT NULL CHECK (severity IN ('info', 'low', 'medium', 'high')),
            evidence_ids TEXT[] NOT NULL CHECK (cardinality(evidence_ids) >= 1)
        );
        CREATE UNIQUE INDEX idx_findings_run_key_unique ON findings (run_id, key);

        CREATE TABLE hypotheses (
            {STANDARD_COLUMNS},
            run_id UUID NOT NULL,
            key TEXT NOT NULL CHECK (key ~ '^hy_[0-9a-f]{{12}}$'),
            round INT NOT NULL DEFAULT 0 CHECK (round >= 0),
            rank INT NOT NULL CHECK (rank >= 1),
            statement TEXT NOT NULL,
            category TEXT NOT NULL CHECK (category IN (
                'missing_index', 'poor_index_order', 'cardinality_misestimate', 'stale_statistics',
                'inefficient_sort', 'join_strategy', 'query_shape', 'lock_contention',
                'io_pressure', 'workload_change', 'other')),
            supporting_evidence TEXT[] NOT NULL CHECK (cardinality(supporting_evidence) >= 1),
            contradicting_evidence TEXT[] NOT NULL DEFAULT '{{}}',
            confidence TEXT NOT NULL CHECK (confidence IN ('low', 'medium', 'high')),
            uncertainty_notes TEXT NOT NULL,
            verification_method TEXT NOT NULL CHECK (verification_method IN (
                'benchmark', 'explain_compare', 'stats_refresh', 'workload_observation',
                'not_verifiable')),
            proposed_by TEXT[] NOT NULL,
            status TEXT NOT NULL DEFAULT 'proposed' CHECK (status IN (
                'proposed', 'approved', 'declined', 'benchmarked', 'verified', 'rejected',
                'inconclusive'))
        );
        CREATE UNIQUE INDEX idx_hypotheses_run_key_unique ON hypotheses (run_id, key);

        CREATE TABLE jobs (
            {STANDARD_COLUMNS},
            kind TEXT NOT NULL CHECK (kind IN ('run_start', 'run_resume', 'experiment_replay', 'retention_sweep')),
            run_id UUID,
            payload JSONB NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'running', 'done', 'failed', 'dead')),
            attempts INT NOT NULL DEFAULT 0 CHECK (attempts >= 0),
            max_attempts INT NOT NULL DEFAULT 3 CHECK (max_attempts >= 1),
            run_after TIMESTAMPTZ NOT NULL DEFAULT now(),
            locked_by TEXT,
            locked_until TIMESTAMPTZ,
            dedupe_key TEXT,
            last_error JSONB
        );
        CREATE INDEX idx_jobs_pending ON jobs (run_after) WHERE status = 'pending';
        CREATE INDEX idx_jobs_running_lease ON jobs (locked_until) WHERE status = 'running';
        CREATE INDEX idx_jobs_run_id ON jobs (run_id);
        CREATE UNIQUE INDEX idx_jobs_dedupe_key_unique ON jobs (dedupe_key) WHERE dedupe_key IS NOT NULL;
        """
    )
    for table in TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_set_updated_at BEFORE UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
        )

    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON investigations, investigation_runs, hypotheses, jobs "
        "TO qc_app"
    )
    # Append-only for the app: no UPDATE, so no DELETE and no row locks either.
    op.execute(
        "GRANT SELECT, INSERT ON investigation_events, agent_executions, tool_executions, "
        "evidence, findings TO qc_app"
    )
    op.execute("GRANT USAGE ON SEQUENCE investigation_events_id_seq TO qc_app")
    op.execute(f"GRANT SELECT, DELETE ON {', '.join(TABLES)} TO qc_retention")


def downgrade() -> None:
    op.execute(f"DROP TABLE IF EXISTS {', '.join(reversed(TABLES))}")
