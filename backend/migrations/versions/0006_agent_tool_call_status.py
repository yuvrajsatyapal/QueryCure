"""agent_executions.status gains 'tool_call': a turn in which the agent asked for a tool.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-12
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE agent_executions DROP CONSTRAINT agent_executions_status_check")
    op.execute(
        "ALTER TABLE agent_executions ADD CONSTRAINT agent_executions_status_check "
        "CHECK (status IN ('succeeded', 'failed', 'invalid_output', 'tool_call'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE agent_executions DROP CONSTRAINT agent_executions_status_check")
    op.execute(
        "ALTER TABLE agent_executions ADD CONSTRAINT agent_executions_status_check "
        "CHECK (status IN ('succeeded', 'failed', 'invalid_output'))"
    )
