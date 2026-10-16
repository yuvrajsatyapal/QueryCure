"""BYOK model credentials (T5.2, ADR-0012) and the credential a run uses.

`llm_credentials` holds the user's own provider key as AES-256-GCM ciphertext; the associated
data binds it to its table, row and user, so a ciphertext copied elsewhere does not decrypt.
Only `key_hint` (the last 4 characters) is ever shown. Deleting a credential soft-deletes the
row and wipes the ciphertext and nonce in the same statement (the CHECK makes a deleted row
with ciphertext impossible to leave behind). At most one active credential per provider and
user.

`investigation_runs.llm_credential_id` records which credential a run was started with, so the
worker resolves the user's own key per run (references only in graph state, as before).

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-16
"""

from alembic import op

revision = "0015"
down_revision = "0014"
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
        CREATE TABLE llm_credentials (
            {STANDARD_COLUMNS},
            user_id UUID NOT NULL,
            provider TEXT NOT NULL CHECK (provider IN ('gemini', 'openrouter')),
            ciphertext BYTEA,
            nonce BYTEA,
            key_version INT NOT NULL,
            key_hint TEXT NOT NULL CHECK (char_length(key_hint) <= 4),
            default_model TEXT,
            last_used_at TIMESTAMPTZ,
            CHECK ((ciphertext IS NULL) = (nonce IS NULL)),
            CHECK (deleted_at IS NOT NULL OR ciphertext IS NOT NULL),
            CHECK (deleted_at IS NULL OR ciphertext IS NULL)
        );
        CREATE UNIQUE INDEX idx_llm_credentials_user_provider_unique
            ON llm_credentials (user_id, provider) WHERE deleted_at IS NULL;
        CREATE INDEX idx_llm_credentials_user_id ON llm_credentials (user_id);
        CREATE TRIGGER llm_credentials_set_updated_at BEFORE UPDATE ON llm_credentials
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();

        ALTER TABLE investigation_runs ADD COLUMN llm_credential_id UUID;
        CREATE INDEX idx_investigation_runs_llm_credential_id
            ON investigation_runs (llm_credential_id) WHERE llm_credential_id IS NOT NULL;
        """
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON llm_credentials TO qc_app")
    op.execute("GRANT SELECT, DELETE ON llm_credentials TO qc_retention")


def downgrade() -> None:
    op.execute("ALTER TABLE investigation_runs DROP COLUMN llm_credential_id")
    op.execute("DROP TABLE llm_credentials")
