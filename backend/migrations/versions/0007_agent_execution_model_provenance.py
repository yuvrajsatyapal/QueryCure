"""agent_executions records the requested model and the upstream provider that served it.

`model` holds the model that actually answered: a router such as openrouter/free picks one
per request (ADR-0016).

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-12
"""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE agent_executions ADD COLUMN requested_model TEXT, ADD COLUMN served_by TEXT"
    )
    # The daily free-request count scans recent executions.
    op.execute("CREATE INDEX idx_agent_executions_created_at ON agent_executions (created_at)")


def downgrade() -> None:
    op.execute("DROP INDEX idx_agent_executions_created_at")
    op.execute("ALTER TABLE agent_executions DROP COLUMN requested_model, DROP COLUMN served_by")
