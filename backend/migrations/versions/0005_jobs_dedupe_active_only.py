"""Job dedupe applies to active jobs only, so a finished resume job does not block the next one.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-12
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP INDEX idx_jobs_dedupe_key_unique")
    op.execute(
        "CREATE UNIQUE INDEX idx_jobs_dedupe_key_active_unique ON jobs (dedupe_key) "
        "WHERE dedupe_key IS NOT NULL AND status IN ('pending', 'running')"
    )


def downgrade() -> None:
    op.execute("DROP INDEX idx_jobs_dedupe_key_active_unique")
    op.execute(
        "CREATE UNIQUE INDEX idx_jobs_dedupe_key_unique ON jobs (dedupe_key) "
        "WHERE dedupe_key IS NOT NULL"
    )
