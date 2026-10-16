"""Rate-limit buckets and per-user upload records (Phase 5, T5.3 and SECURITY §5 hardening).

`rate_limit_buckets`: one token bucket per (limit name, subject), where the subject is a user
id or a SHA-256 of the client IP, never the raw address. Mutable by design (it is a counter,
not evidence), so `qc_app` may UPDATE it; the retention role may delete stale buckets.

`user_uploads`: who uploaded which content-addressed artifact through `/inspect/plan` or
`/inspect/schema`. Artifacts stay deduplicated and ownerless (ADR-0010); this table is what
makes an uploaded digest usable only by the users who uploaded it, closing the "digest as a
capability" gap recorded in SECURITY §5. Append-only for `qc_app`.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-16
"""

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

STANDARD_TIMESTAMPS = """
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ,
    deleted_at TIMESTAMPTZ
"""
STANDARD_COLUMNS = f"id UUID PRIMARY KEY DEFAULT uuid_generate_v4(), {STANDARD_TIMESTAMPS}"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE rate_limit_buckets (
            {STANDARD_COLUMNS},
            bucket_key TEXT NOT NULL,
            tokens DOUBLE PRECISION NOT NULL,
            refilled_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE UNIQUE INDEX idx_rate_limit_buckets_bucket_key_unique
            ON rate_limit_buckets (bucket_key);
        CREATE INDEX idx_rate_limit_buckets_refilled_at ON rate_limit_buckets (refilled_at);
        CREATE TRIGGER rate_limit_buckets_set_updated_at BEFORE UPDATE ON rate_limit_buckets
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();

        CREATE TABLE user_uploads (
            {STANDARD_COLUMNS},
            user_id UUID NOT NULL,
            artifact_id UUID NOT NULL,
            kind TEXT NOT NULL
        );
        CREATE UNIQUE INDEX idx_user_uploads_user_artifact_unique
            ON user_uploads (user_id, artifact_id);
        CREATE INDEX idx_user_uploads_artifact_id ON user_uploads (artifact_id);
        """
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON rate_limit_buckets TO qc_app")
    op.execute("GRANT SELECT, INSERT ON user_uploads TO qc_app")
    op.execute("GRANT SELECT, DELETE ON rate_limit_buckets, user_uploads TO qc_retention")


def downgrade() -> None:
    op.execute("DROP TABLE user_uploads")
    op.execute("DROP TABLE rate_limit_buckets")
