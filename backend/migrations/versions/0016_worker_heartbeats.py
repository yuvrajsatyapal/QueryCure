"""Worker presence (OBSERVABILITY §5, 2026-10-18).

Job leases heartbeat only while a job runs, so an idle or dead worker left no trace until the
queue backed up. Each worker process upserts one row while it runs: which code it runs
(`source_digest`, SHA-256 of its installed Python sources), its measurement path, and when it
was last seen; a clean shutdown sets `stopped_at`. Bookkeeping only: the retention role
removes rows not seen for 30 days.

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-18
"""

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE worker_heartbeats (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ,
            deleted_at TIMESTAMPTZ,
            worker_id TEXT NOT NULL CHECK (char_length(worker_id) <= 100),
            hostname TEXT CHECK (char_length(hostname) <= 255),
            source_digest TEXT NOT NULL CHECK (source_digest ~ '^[0-9a-f]{64}$'),
            bench_path TEXT CHECK (char_length(bench_path) <= 40),
            started_at TIMESTAMPTZ NOT NULL,
            last_seen_at TIMESTAMPTZ NOT NULL,
            stopped_at TIMESTAMPTZ
        );
        CREATE UNIQUE INDEX idx_worker_heartbeats_worker_id_unique
            ON worker_heartbeats (worker_id) WHERE deleted_at IS NULL;
        CREATE INDEX idx_worker_heartbeats_last_seen_at
            ON worker_heartbeats (last_seen_at) WHERE deleted_at IS NULL;
        CREATE TRIGGER worker_heartbeats_set_updated_at BEFORE UPDATE ON worker_heartbeats
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON worker_heartbeats TO qc_app")
    op.execute("GRANT SELECT, DELETE ON worker_heartbeats TO qc_retention")


def downgrade() -> None:
    op.execute("DROP TABLE worker_heartbeats")
