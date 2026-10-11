"""One active local user (concurrent POST /session cannot create two); readiness grant.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-11
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE UNIQUE INDEX idx_users_single_local_unique ON users (kind) "
        "WHERE kind = 'local' AND deleted_at IS NULL"
    )
    # /readyz compares the applied revision with head while connected as the restricted app role.
    op.execute("GRANT SELECT ON alembic_version TO qc_app")


def downgrade() -> None:
    op.execute("REVOKE SELECT ON alembic_version FROM qc_app")
    op.execute("DROP INDEX IF EXISTS idx_users_single_local_unique")
