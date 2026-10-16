"""Idempotency-Key for experiment replay (API_DESIGN §1, Phase 5).

`POST /experiments/{id}/replay` starts expensive sandbox work. A retried request (network
timeout, double click, browser retry) must return the original attempt instead of queueing a
second benchmark. The key is scoped to the user and the operation (`kind`): the same UUID
from another user, or for report replay, is a different key. The unique index makes
concurrent duplicates converge on one attempt: the losing transaction rolls back its replay
run, approval and job together with its attempt row.

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-16
"""

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE replay_attempts
            ADD COLUMN idempotency_key TEXT,
            ADD COLUMN idempotency_request_hash TEXT,
            ADD CONSTRAINT replay_attempts_idempotency_pair
                CHECK ((idempotency_key IS NULL) = (idempotency_request_hash IS NULL));
        CREATE UNIQUE INDEX idx_replay_attempts_idempotency_unique
            ON replay_attempts (user_id, kind, idempotency_key)
            WHERE idempotency_key IS NOT NULL;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX idx_replay_attempts_idempotency_unique;
        ALTER TABLE replay_attempts
            DROP CONSTRAINT replay_attempts_idempotency_pair,
            DROP COLUMN idempotency_request_hash,
            DROP COLUMN idempotency_key;
        """
    )
