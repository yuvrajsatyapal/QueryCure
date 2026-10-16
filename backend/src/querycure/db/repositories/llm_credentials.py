"""BYOK credentials (migration 0015). Ciphertext never leaves this module except to the
decrypting caller in `llm.credentials`; listings carry the hint only."""

import datetime as dt
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from querycure.core.crypto import EncryptedSecret, SecretBox, secret_aad

TABLE = "llm_credentials"


class CredentialSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    provider: str
    key_hint: str
    default_model: str | None
    created_at: dt.datetime
    last_used_at: dt.datetime | None


_SUMMARY = "id, provider, key_hint, default_model, created_at, last_used_at"


def aad(row_id: uuid.UUID, user_id: uuid.UUID) -> bytes:
    return secret_aad(table=TABLE, row_id=str(row_id), user_id=str(user_id))


async def replace_credential(
    conn: AsyncConnection,
    *,
    box: SecretBox,
    user_id: uuid.UUID,
    provider: str,
    api_key: str,
    default_model: str | None,
) -> CredentialSummary:
    """One active credential per provider: the previous one is deleted and wiped first."""
    await wipe_for_provider(conn, user_id=user_id, provider=provider)
    row_id = uuid.uuid4()
    sealed = box.encrypt(api_key, aad=aad(row_id, user_id))
    row = (
        await conn.execute(
            text(
                f"INSERT INTO llm_credentials (id, user_id, provider, ciphertext, nonce, "  # noqa: S608
                "key_version, key_hint, default_model) VALUES (:id, :user, :provider, :ct, "
                f":nonce, :kv, :hint, :model) RETURNING {_SUMMARY}"
            ),
            {
                "id": row_id,
                "user": user_id,
                "provider": provider,
                "ct": sealed.ciphertext,
                "nonce": sealed.nonce,
                "kv": sealed.key_version,
                "hint": api_key[-4:],
                "model": default_model,
            },
        )
    ).one()
    return CredentialSummary.model_validate(row, from_attributes=True)


async def list_credentials(conn: AsyncConnection, user_id: uuid.UUID) -> list[CredentialSummary]:
    rows = await conn.execute(
        text(
            f"SELECT {_SUMMARY} FROM llm_credentials WHERE user_id = :user "  # noqa: S608
            "AND deleted_at IS NULL ORDER BY created_at DESC"
        ),
        {"user": user_id},
    )
    return [CredentialSummary.model_validate(r, from_attributes=True) for r in rows]


async def get_active(
    conn: AsyncConnection,
    *,
    user_id: uuid.UUID,
    credential_id: uuid.UUID | None = None,
    provider: str | None = None,
) -> CredentialSummary | None:
    row = (
        await conn.execute(
            text(
                f"SELECT {_SUMMARY} FROM llm_credentials WHERE user_id = :user "  # noqa: S608
                "AND deleted_at IS NULL AND (CAST(:id AS UUID) IS NULL OR id = :id) "
                "AND (CAST(:provider AS TEXT) IS NULL OR provider = :provider) "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"user": user_id, "id": credential_id, "provider": provider},
        )
    ).first()
    return None if row is None else CredentialSummary.model_validate(row, from_attributes=True)


async def sealed_secret(
    conn: AsyncConnection, *, user_id: uuid.UUID, credential_id: uuid.UUID
) -> tuple[CredentialSummary, EncryptedSecret] | None:
    row: Any = (
        await conn.execute(
            text(
                f"SELECT {_SUMMARY}, ciphertext, nonce, key_version FROM llm_credentials "  # noqa: S608
                "WHERE id = :id AND user_id = :user AND deleted_at IS NULL"
            ),
            {"id": credential_id, "user": user_id},
        )
    ).first()
    if row is None:
        return None
    summary = CredentialSummary.model_validate(row, from_attributes=True)
    sealed = EncryptedSecret(
        ciphertext=bytes(row.ciphertext), nonce=bytes(row.nonce), key_version=row.key_version
    )
    return summary, sealed


async def touch(conn: AsyncConnection, credential_id: uuid.UUID) -> None:
    await conn.execute(
        text("UPDATE llm_credentials SET last_used_at = now() WHERE id = :id"),
        {"id": credential_id},
    )


async def wipe(conn: AsyncConnection, *, user_id: uuid.UUID, credential_id: uuid.UUID) -> bool:
    """Soft delete and wipe the ciphertext in one statement. False if not the user's."""
    result = await conn.execute(
        text(
            "UPDATE llm_credentials SET deleted_at = now(), ciphertext = NULL, nonce = NULL "
            "WHERE id = :id AND user_id = :user AND deleted_at IS NULL"
        ),
        {"id": credential_id, "user": user_id},
    )
    return bool(result.rowcount)


async def wipe_for_provider(conn: AsyncConnection, *, user_id: uuid.UUID, provider: str) -> None:
    await conn.execute(
        text(
            "UPDATE llm_credentials SET deleted_at = now(), ciphertext = NULL, nonce = NULL "
            "WHERE user_id = :user AND provider = :provider AND deleted_at IS NULL"
        ),
        {"user": user_id, "provider": provider},
    )
