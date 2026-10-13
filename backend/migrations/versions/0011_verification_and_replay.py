"""Phase 4: verification results, reports, replay manifests, replay attempts (T4.1).

- `verification_results`: one row per (experiment, candidate), written once by the Benchmark
  Auditor. `engine_verdict` is the deterministic verdict (rules, or replication for bench@2);
  `verdict` is the audited one. A CHECK makes the auditor downgrade-only (ADR-0009): the
  verdict either equals the engine verdict or is `inconclusive` after a `verified` /
  `verified_with_noise_warning` engine verdict.
- `investigation_reports` and `replay_manifests`: written once inside `finalize_run`
  (REPLAY_ENGINE §5).
- These three are append-only for qc_app (INSERT/SELECT, so no UPDATE, DELETE or row locks),
  like artifacts, events and benchmark runs. `replay_attempts` is mutable: it carries a state
  machine (REPLAY_ENGINE §8).

`investigation_runs.finalized_at` / `events_cutoff_seq` already exist (migration 0003).

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-13
"""

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

STANDARD_TIMESTAMPS = """
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ,
    deleted_at TIMESTAMPTZ
"""
STANDARD_COLUMNS = f"id UUID PRIMARY KEY DEFAULT uuid_generate_v4(), {STANDARD_TIMESTAMPS}"
APPEND_ONLY = ("verification_results", "investigation_reports", "replay_manifests")
TABLES = (*APPEND_ONLY, "replay_attempts")
VERDICTS = "'verified', 'verified_with_noise_warning', 'rejected', 'inconclusive'"
REPORT_STATUSES = (
    "'verifying', 'verified', 'verified_stored_only', 'not_replayable', 'integrity_failed', 'error'"
)
EXPERIMENT_STATUSES = (
    "'checking', 'not_replayable', 'queued', 'running', 'comparing', 'reproduced', "
    "'reproduced_with_drift', 'not_reproduced', 'inconclusive', 'failed', 'cancelled'"
)


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE verification_results (
            {STANDARD_COLUMNS},
            run_id UUID NOT NULL,
            experiment_id UUID NOT NULL,
            candidate_id UUID NOT NULL,
            candidate_key TEXT NOT NULL CHECK (candidate_key ~ '^oc_[0-9a-f]{{12}}$'),
            round INT NOT NULL CHECK (round >= 0),
            engine_verdict TEXT NOT NULL CHECK (engine_verdict IN ({VERDICTS})),
            verdict TEXT NOT NULL CHECK (verdict IN ({VERDICTS})),
            reasons JSONB NOT NULL DEFAULT '[]',
            stats JSONB NOT NULL DEFAULT '[]',
            checks JSONB NOT NULL DEFAULT '[]',
            auditor_status TEXT NOT NULL CHECK (auditor_status IN (
                'completed', 'deterministic_only')),
            auditor_notes TEXT,
            auditor_concerns JSONB NOT NULL DEFAULT '[]',
            auditor_prompt_version TEXT,
            auditor_downgraded BOOLEAN NOT NULL,
            -- ADR-0009: the auditor can only move a verified result to inconclusive.
            CONSTRAINT verification_results_downgrade_only CHECK (
                verdict = engine_verdict
                OR (engine_verdict IN ('verified', 'verified_with_noise_warning')
                    AND verdict = 'inconclusive')),
            CONSTRAINT verification_results_downgraded_flag CHECK (
                auditor_downgraded = (verdict <> engine_verdict))
        );
        CREATE UNIQUE INDEX idx_verification_results_experiment_candidate_unique
            ON verification_results (experiment_id, candidate_id);
        CREATE INDEX idx_verification_results_run_id ON verification_results (run_id);
        CREATE INDEX idx_verification_results_candidate_id
            ON verification_results (candidate_id);

        CREATE TABLE investigation_reports (
            {STANDARD_COLUMNS},
            run_id UUID NOT NULL,
            report_json_artifact_id UUID NOT NULL,
            report_md_artifact_id UUID NOT NULL,
            report_json_sha256 TEXT NOT NULL,
            report_md_sha256 TEXT NOT NULL,
            final_status TEXT NOT NULL CHECK (final_status IN ('completed', 'failed', 'cancelled')),
            outcome TEXT CHECK (outcome IN (
                'verified_recommendation', 'unverified_recommendations', 'no_action_needed',
                'inconclusive')),
            report_schema_version INT NOT NULL CHECK (report_schema_version >= 1),
            builder_version TEXT NOT NULL,
            md_renderer_version TEXT NOT NULL,
            CHECK ((outcome IS NULL) OR (final_status = 'completed'))
        );
        CREATE UNIQUE INDEX idx_investigation_reports_run_unique ON investigation_reports (run_id);
        CREATE INDEX idx_investigation_reports_json_artifact
            ON investigation_reports (report_json_artifact_id);
        CREATE INDEX idx_investigation_reports_md_artifact
            ON investigation_reports (report_md_artifact_id);

        CREATE TABLE replay_manifests (
            {STANDARD_COLUMNS},
            run_id UUID NOT NULL,
            manifest_artifact_id UUID NOT NULL,
            manifest_sha256 TEXT NOT NULL,
            manifest_schema_version INT NOT NULL CHECK (manifest_schema_version >= 1),
            events_cutoff_seq INT NOT NULL CHECK (events_cutoff_seq >= 0),
            events_digest TEXT NOT NULL
        );
        CREATE UNIQUE INDEX idx_replay_manifests_run_unique ON replay_manifests (run_id);
        CREATE INDEX idx_replay_manifests_manifest_artifact
            ON replay_manifests (manifest_artifact_id);

        CREATE TABLE replay_attempts (
            {STANDARD_COLUMNS},
            user_id UUID NOT NULL,
            kind TEXT NOT NULL CHECK (kind IN ('report', 'experiment')),
            source_run_id UUID NOT NULL,
            source_experiment_id UUID,
            replay_run_id UUID,
            replay_experiment_id UUID,
            approval_request_id UUID,
            status TEXT NOT NULL,
            failure_code TEXT,
            warnings TEXT[] NOT NULL DEFAULT '{{}}',
            result JSONB NOT NULL DEFAULT '{{}}',
            started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            finished_at TIMESTAMPTZ,
            CHECK (
                (kind = 'report' AND status IN ({REPORT_STATUSES})
                 AND source_experiment_id IS NULL AND replay_run_id IS NULL)
                OR (kind = 'experiment' AND status IN ({EXPERIMENT_STATUSES})
                    AND source_experiment_id IS NOT NULL))
        );
        CREATE INDEX idx_replay_attempts_source_run ON replay_attempts (source_run_id, created_at DESC);
        CREATE INDEX idx_replay_attempts_active ON replay_attempts (status)
            WHERE status IN ('checking', 'queued', 'running', 'comparing');
        CREATE INDEX idx_replay_attempts_replay_run_id ON replay_attempts (replay_run_id);
        CREATE INDEX idx_replay_attempts_user_id ON replay_attempts (user_id);
        CREATE INDEX idx_replay_attempts_source_experiment_id
            ON replay_attempts (source_experiment_id);
        """
    )
    op.execute(
        "CREATE TRIGGER replay_attempts_set_updated_at BEFORE UPDATE ON replay_attempts "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
    )
    op.execute(f"GRANT SELECT, INSERT ON {', '.join(APPEND_ONLY)} TO qc_app")
    op.execute("GRANT SELECT, INSERT, UPDATE ON replay_attempts TO qc_app")
    op.execute(f"GRANT SELECT, DELETE ON {', '.join(TABLES)} TO qc_retention")


def downgrade() -> None:
    op.execute(f"DROP TABLE IF EXISTS {', '.join(reversed(TABLES))}")
