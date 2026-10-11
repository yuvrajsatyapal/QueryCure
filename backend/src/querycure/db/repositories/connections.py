import datetime as dt
import json
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from querycure.core.crypto import EncryptedSecret


class ConnectionRecord(BaseModel):
    """Internal row shape; the sealed password never leaves the backend."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    user_id: uuid.UUID
    name: str
    host: str
    port: int
    dbname: str
    username: str
    sslmode: str
    environment: str
    purpose: str
    password_ciphertext: bytes | None
    password_nonce: bytes | None
    key_version: int | None
    capabilities: dict[str, Any] | None
    last_tested_at: dt.datetime | None
    last_test_status: str | None
    created_at: dt.datetime

    def sealed_password(self) -> EncryptedSecret | None:
        if self.password_ciphertext is None or self.password_nonce is None:
            return None
        return EncryptedSecret(
            ciphertext=self.password_ciphertext,
            nonce=self.password_nonce,
            key_version=self.key_version or 1,
        )


_SELECT = (
    "SELECT id, user_id, name, host, port, dbname, username, sslmode, environment, purpose, "
    "password_ciphertext, password_nonce, key_version, capabilities, last_tested_at, "
    "last_test_status, created_at FROM database_connections "
)


def _record(row: object) -> ConnectionRecord:
    return ConnectionRecord.model_validate(row, from_attributes=True)


async def insert_connection(
    conn: AsyncConnection,
    *,
    id: uuid.UUID,
    user_id: uuid.UUID,
    fields: dict[str, Any],
    sealed: EncryptedSecret,
) -> ConnectionRecord:
    row = (
        await conn.execute(
            text(
                "INSERT INTO database_connections (id, user_id, name, host, port, dbname, "
                "username, sslmode, environment, purpose, password_ciphertext, password_nonce, "
                "key_version) "
                "VALUES (:id, :user_id, :name, :host, :port, :dbname, :username, :sslmode, "
                ":environment, :purpose, :ciphertext, :nonce, :key_version) RETURNING id"
            ),
            {
                **fields,
                "id": id,
                "user_id": user_id,
                "ciphertext": sealed.ciphertext,
                "nonce": sealed.nonce,
                "key_version": sealed.key_version,
            },
        )
    ).one()
    record = await get_connection(conn, user_id=user_id, connection_id=row.id)
    if record is None:
        raise RuntimeError("inserted connection not readable")
    return record


async def list_connections(conn: AsyncConnection, *, user_id: uuid.UUID) -> list[ConnectionRecord]:
    rows = await conn.execute(
        text(_SELECT + "WHERE user_id = :user_id AND deleted_at IS NULL ORDER BY created_at DESC"),
        {"user_id": user_id},
    )
    return [_record(r) for r in rows]


async def get_connection(
    conn: AsyncConnection, *, user_id: uuid.UUID, connection_id: uuid.UUID
) -> ConnectionRecord | None:
    # Scoped by user: another user's id is indistinguishable from a missing one (404, not 403).
    row = (
        await conn.execute(
            text(_SELECT + "WHERE id = :id AND user_id = :user_id AND deleted_at IS NULL"),
            {"id": connection_id, "user_id": user_id},
        )
    ).one_or_none()
    return _record(row) if row is not None else None


async def record_test(
    conn: AsyncConnection,
    *,
    user_id: uuid.UUID,
    connection_id: uuid.UUID,
    status: str,
    capabilities: dict[str, Any] | None,
) -> None:
    await conn.execute(
        text(
            "UPDATE database_connections SET last_test_status = :status, last_tested_at = now(), "
            "capabilities = CAST(:capabilities AS jsonb) "
            "WHERE id = :id AND user_id = :user_id AND deleted_at IS NULL"
        ),
        {
            "status": status,
            "capabilities": json.dumps(capabilities) if capabilities is not None else None,
            "id": connection_id,
            "user_id": user_id,
        },
    )


async def soft_delete(
    conn: AsyncConnection, *, user_id: uuid.UUID, connection_id: uuid.UUID
) -> bool:
    """Soft delete the row but wipe the secret immediately (DATABASE_DESIGN §6)."""
    result = await conn.execute(
        text(
            "UPDATE database_connections SET deleted_at = now(), password_ciphertext = NULL, "
            "password_nonce = NULL WHERE id = :id AND user_id = :user_id AND deleted_at IS NULL"
        ),
        {"id": connection_id, "user_id": user_id},
    )
    return bool(result.rowcount)
