import datetime as dt
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from querycure.domain.users import User


async def create_session(
    conn: AsyncConnection,
    *,
    user_id: uuid.UUID,
    token_hash: str,
    expires_at: dt.datetime,
    user_agent: str | None,
) -> None:
    await conn.execute(
        text(
            "INSERT INTO sessions (user_id, token_hash, expires_at, user_agent) "
            "VALUES (:user_id, :token_hash, :expires_at, :user_agent)"
        ),
        {
            "user_id": user_id,
            "token_hash": token_hash,
            "expires_at": expires_at,
            "user_agent": user_agent,
        },
    )


async def get_session_user(conn: AsyncConnection, token_hash: str) -> User | None:
    """User for a live session; expired, deleted or orphaned sessions resolve to None."""
    row = (
        await conn.execute(
            text(
                "SELECT u.id, u.kind, u.display_name FROM sessions s "
                "JOIN users u ON u.id = s.user_id AND u.deleted_at IS NULL "
                "WHERE s.token_hash = :token_hash AND s.deleted_at IS NULL AND s.expires_at > now()"
            ),
            {"token_hash": token_hash},
        )
    ).one_or_none()
    return User.model_validate(row, from_attributes=True) if row is not None else None


async def revoke_session(conn: AsyncConnection, token_hash: str) -> None:
    """Logout: the session stops resolving at once (soft delete, kept for audit)."""
    await conn.execute(
        text(
            "UPDATE sessions SET deleted_at = now() WHERE token_hash = :token_hash "
            "AND deleted_at IS NULL"
        ),
        {"token_hash": token_hash},
    )
