import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from querycure.domain.users import User, UserKind


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
                "SELECT id, kind, display_name, email FROM users "
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
                "RETURNING id, kind, display_name, email"
            ),
            {"kind": UserKind.ANONYMOUS.value},
        )
    ).one()
    return _user(row)


async def get_user(conn: AsyncConnection, user_id: uuid.UUID) -> User | None:
    row = (
        await conn.execute(
            text(
                "SELECT id, kind, display_name, email FROM users "
                "WHERE id = :id AND deleted_at IS NULL"
            ),
            {"id": user_id},
        )
    ).one_or_none()
    return _user(row) if row is not None else None


async def find_oauth_user(conn: AsyncConnection, *, provider: str, subject: str) -> User | None:
    row = (
        await conn.execute(
            text(
                "SELECT id, kind, display_name, email FROM users WHERE auth_provider = :p "
                "AND auth_subject = :s AND deleted_at IS NULL"
            ),
            {"p": provider, "s": subject},
        )
    ).one_or_none()
    return _user(row) if row is not None else None


async def convert_to_oauth(
    conn: AsyncConnection, *, user_id: uuid.UUID, provider: str, subject: str, display_name: str
) -> User:
    """An anonymous user signs in for the first time: the same row, so all its data stays."""
    row = (
        await conn.execute(
            text(
                "UPDATE users SET kind = 'oauth', auth_provider = :p, auth_subject = :s, "
                "display_name = :name, last_seen_at = now() WHERE id = :id "
                "RETURNING id, kind, display_name, email"
            ),
            {"id": user_id, "p": provider, "s": subject, "name": display_name},
        )
    ).one()
    return _user(row)


async def create_oauth_user(
    conn: AsyncConnection,
    *,
    provider: str,
    subject: str,
    display_name: str,
    email: str | None = None,
) -> User:
    row = (
        await conn.execute(
            text(
                "INSERT INTO users (kind, auth_provider, auth_subject, display_name, email, "
                "last_seen_at) VALUES ('oauth', :p, :s, :name, :email, now()) "
                "RETURNING id, kind, display_name, email"
            ),
            {"p": provider, "s": subject, "name": display_name, "email": email},
        )
    ).one()
    return _user(row)


async def touch_oauth_user(
    conn: AsyncConnection, user_id: uuid.UUID, display_name: str, email: str | None = None
) -> User:
    """Refreshes the profile at sign-in. `email` is the approved address while access is
    restricted (ADR-0031); None keeps whatever is stored."""
    row = (
        await conn.execute(
            text(
                "UPDATE users SET display_name = :name, email = COALESCE(:email, email), "
                "last_seen_at = now() WHERE id = :id RETURNING id, kind, display_name, email"
            ),
            {"id": user_id, "name": display_name, "email": email},
        )
    ).one()
    return _user(row)


# Tables whose rows belong to a user through `user_id` (DATABASE_DESIGN). llm_credentials and
# user_uploads are handled separately: credentials are bound to their user by AEAD associated
# data, and upload records are unique per (user, artifact).
_OWNED = ("investigations", "database_connections", "replay_attempts", "approval_requests")


async def merge_user_data(
    conn: AsyncConnection, *, from_user: uuid.UUID, to_user: uuid.UUID
) -> None:
    """Moves an anonymous user's data to the account it signed in to, then retires it.
    Caller handles credentials (re-encryption) first. Runs in the caller's transaction."""
    for table in _OWNED:
        await conn.execute(
            text(f"UPDATE {table} SET user_id = :to WHERE user_id = :from"),  # noqa: S608
            {"to": to_user, "from": from_user},
        )
    await conn.execute(
        text(
            "INSERT INTO user_uploads (user_id, artifact_id, kind) SELECT :to, artifact_id, kind "
            "FROM user_uploads WHERE user_id = :from AND deleted_at IS NULL "
            "ON CONFLICT (user_id, artifact_id) DO NOTHING"
        ),
        {"to": to_user, "from": from_user},
    )
    await conn.execute(
        text("UPDATE sessions SET deleted_at = now() WHERE user_id = :from AND deleted_at IS NULL"),
        {"from": from_user},
    )
    await conn.execute(
        text("UPDATE users SET deleted_at = now() WHERE id = :from"), {"from": from_user}
    )
