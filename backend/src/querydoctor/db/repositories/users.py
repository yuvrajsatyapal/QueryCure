import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from querydoctor.domain.users import User, UserKind


def _user(row: object) -> User:
    return User.model_validate(row, from_attributes=True)


async def get_or_create_local_user(conn: AsyncConnection) -> User:
    # The partial unique index (migration 0002) makes concurrent first logins converge on one row.
    await conn.execute(
        text(
            "INSERT INTO users (kind, display_name) VALUES ('local', 'Local developer') "
            "ON CONFLICT (kind) WHERE kind = 'local' AND deleted_at IS NULL DO NOTHING"
        )
    )
    row = (
        await conn.execute(
            text(
                "SELECT id, kind, display_name FROM users "
                "WHERE kind = 'local' AND deleted_at IS NULL"
            )
        )
    ).one()
    return _user(row)


async def create_anonymous_user(conn: AsyncConnection) -> User:
    row = (
        await conn.execute(
            text(
                "INSERT INTO users (kind, last_seen_at) VALUES (:kind, now()) "
                "RETURNING id, kind, display_name"
            ),
            {"kind": UserKind.ANONYMOUS.value},
        )
    ).one()
    return _user(row)


async def get_user(conn: AsyncConnection, user_id: uuid.UUID) -> User | None:
    row = (
        await conn.execute(
            text("SELECT id, kind, display_name FROM users WHERE id = :id AND deleted_at IS NULL"),
            {"id": user_id},
        )
    ).one_or_none()
    return _user(row) if row is not None else None
