"""Phase 1 baseline: extension, roles, updated_at trigger, users, sessions, connections, artifacts.

Revision ID: 0001
Revises:
Create Date: 2026-10-11
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# Conventions: ADR-0006 (UUID, TEXT, TIMESTAMPTZ, soft delete, no FK constraints).
# Grants: DATABASE_DESIGN §5 — each table's grants ship with the migration that creates it.

STANDARD_COLUMNS = """
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ,
    deleted_at TIMESTAMPTZ
"""


def _updated_at_trigger(table: str) -> str:
    return (
        f"CREATE TRIGGER {table}_set_updated_at BEFORE UPDATE ON {table} "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
    )


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')

    # Production operators pre-create these as LOGIN roles; locally the compose init script does.
    # Creating them NOLOGIN here keeps fresh databases (tests, CI) consistent without passwords.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'qc_app') THEN
                CREATE ROLE qc_app NOLOGIN;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'qc_retention') THEN
                CREATE ROLE qc_retention NOLOGIN;
            END IF;
        END $$;
        """
    )
    op.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
    op.execute("GRANT USAGE ON SCHEMA public TO qc_app, qc_retention")

    op.execute(
        """
        CREATE FUNCTION set_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END $$;
        """
    )

    op.execute(
        f"""
        CREATE TABLE users (
            {STANDARD_COLUMNS},
            kind TEXT NOT NULL CHECK (kind IN ('local', 'anonymous', 'oauth')),
            auth_provider TEXT,
            auth_subject TEXT,
            display_name TEXT,
            email TEXT,
            last_seen_at TIMESTAMPTZ
        );
        CREATE UNIQUE INDEX idx_users_auth_subject_unique ON users (auth_provider, auth_subject)
            WHERE deleted_at IS NULL AND auth_provider IS NOT NULL;
        CREATE INDEX idx_users_last_seen_anonymous ON users (last_seen_at)
            WHERE kind = 'anonymous' AND deleted_at IS NULL;

        CREATE TABLE sessions (
            {STANDARD_COLUMNS},
            user_id UUID NOT NULL,
            token_hash TEXT NOT NULL CHECK (token_hash ~ '^[0-9a-f]{{64}}$'),
            expires_at TIMESTAMPTZ NOT NULL,
            ip_hash TEXT,
            user_agent TEXT
        );
        CREATE UNIQUE INDEX idx_sessions_token_hash_unique ON sessions (token_hash);
        CREATE INDEX idx_sessions_user_id ON sessions (user_id) WHERE deleted_at IS NULL;
        CREATE INDEX idx_sessions_expires_at ON sessions (expires_at);

        CREATE TABLE database_connections (
            {STANDARD_COLUMNS},
            user_id UUID NOT NULL,
            name TEXT NOT NULL,
            host TEXT NOT NULL,
            port INT NOT NULL CHECK (port BETWEEN 1 AND 65535),
            dbname TEXT NOT NULL,
            username TEXT NOT NULL,
            password_ciphertext BYTEA,
            password_nonce BYTEA,
            key_version INT,
            sslmode TEXT NOT NULL CHECK (sslmode IN ('disable', 'require', 'verify-ca', 'verify-full')),
            environment TEXT NOT NULL CHECK (environment IN ('development', 'staging', 'production')),
            purpose TEXT NOT NULL CHECK (purpose IN ('inspection', 'sandbox')),
            capabilities JSONB,
            last_tested_at TIMESTAMPTZ,
            last_test_status TEXT,
            CHECK ((password_ciphertext IS NULL) = (password_nonce IS NULL))
        );
        CREATE INDEX idx_database_connections_user_id ON database_connections (user_id)
            WHERE deleted_at IS NULL;

        -- Exact canonical bytes (not JSONB/TEXT): JSONB reorders keys, normalizes numbers and
        -- rejects \\u0000; TEXT rejects NUL. Either could break digest verification (REPLAY_ENGINE §2).
        CREATE TABLE artifacts (
            {STANDARD_COLUMNS},
            sha256 TEXT NOT NULL CHECK (sha256 ~ '^[0-9a-f]{{64}}$'),
            kind TEXT NOT NULL CHECK (kind IN (
                'query', 'param_sets', 'schema_snapshot', 'plan', 'plan_analyze', 'stats_snapshot',
                'workload_snapshot', 'experiment_config', 'agent_output', 'report_json', 'report_md',
                'environment', 'replay_manifest')),
            media_type TEXT NOT NULL CHECK (media_type IN ('application/json', 'text/sql', 'text/markdown')),
            content BYTEA NOT NULL CHECK (octet_length(content) <= 5242880),
            canonicalization TEXT NOT NULL CHECK (canonicalization IN ('qc-json-v1', 'qc-text-v1', 'qc-raw-v1'))
        );
        CREATE UNIQUE INDEX idx_artifacts_sha256_unique ON artifacts (sha256);

        CREATE TABLE run_artifacts (
            {STANDARD_COLUMNS},
            run_id UUID NOT NULL,
            artifact_id UUID NOT NULL,
            role TEXT NOT NULL,
            produced_by TEXT
        );
        CREATE UNIQUE INDEX idx_run_artifacts_unique ON run_artifacts (run_id, artifact_id, role);
        CREATE INDEX idx_run_artifacts_artifact_id ON run_artifacts (artifact_id);
        """
    )
    for table in ("users", "sessions", "database_connections", "artifacts", "run_artifacts"):
        op.execute(_updated_at_trigger(table))

    # Mutable tables: app soft-deletes (UPDATE), never hard-deletes. Sessions expire via retention.
    op.execute("GRANT SELECT, INSERT, UPDATE ON users, sessions, database_connections TO qc_app")
    # Append-only: no UPDATE/DELETE for the app role; locking clauses therefore also fail.
    op.execute("GRANT SELECT, INSERT ON artifacts, run_artifacts TO qc_app")
    op.execute(
        "GRANT SELECT, DELETE ON users, sessions, database_connections, artifacts, run_artifacts "
        "TO qc_retention"
    )


def downgrade() -> None:
    op.execute(
        "DROP TABLE IF EXISTS run_artifacts, artifacts, database_connections, sessions, users"
    )
    op.execute("DROP FUNCTION IF EXISTS set_updated_at()")
