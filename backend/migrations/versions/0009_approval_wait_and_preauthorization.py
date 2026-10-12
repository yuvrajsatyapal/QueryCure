"""Approval support: time spent waiting for a human is not run time; demo pre-authorization.

`investigation_runs.waiting_seconds` accumulates time spent in `awaiting_approval`; the
wall-clock budget measures `now() - started_at - waiting_seconds` (AGENT_SYSTEM §11).
`investigations.pre_authorize_sandbox` records the creator's opt-in to run sandbox
experiments on demo workloads without a per-round approval (AGENT_SYSTEM §8); an approval row
is still written for every round, decided by `pre_authorized`.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-12
"""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE investigation_runs ADD COLUMN waiting_seconds DOUBLE PRECISION NOT NULL "
        "DEFAULT 0 CHECK (waiting_seconds >= 0)"
    )
    op.execute(
        "ALTER TABLE investigations ADD COLUMN pre_authorize_sandbox BOOLEAN NOT NULL DEFAULT false"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE investigations DROP COLUMN pre_authorize_sandbox")
    op.execute("ALTER TABLE investigation_runs DROP COLUMN waiting_seconds")
