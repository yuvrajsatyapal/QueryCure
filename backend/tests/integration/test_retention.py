"""Retention sweep (Phase 5): runs as qc_retention and removes only bookkeeping rows."""

import psycopg
import pytest

from querycure.db.engine import make_engine
from querycure.ops.retention import sweep

pytestmark = pytest.mark.integration


async def test_sweep_removes_only_stale_bookkeeping(
    migrated_db: str, owner: psycopg.Connection
) -> None:
    user = owner.execute("INSERT INTO users (kind) VALUES ('anonymous') RETURNING id").fetchone()
    assert user is not None
    owner.execute(
        "INSERT INTO sessions (user_id, token_hash, expires_at) VALUES "
        "(%s, repeat('a', 64), now() - interval '30 days'), "
        "(%s, repeat('b', 64), now() + interval '1 day')",
        (user[0], user[0]),
    )
    owner.execute(
        "INSERT INTO rate_limit_buckets (bucket_key, tokens, refilled_at) VALUES "
        "('idle', 1, now() - interval '3 days'), ('busy', 1, now())"
    )
    owner.execute(
        "INSERT INTO investigations (user_id, title, objective, modes) "
        "VALUES (%s, 'kept', 'o', ARRAY['offline'])",
        (user[0],),
    )
    engine = make_engine(migrated_db, set_role="qc_retention")
    try:
        result = await sweep(engine)
    finally:
        await engine.dispose()
    assert result.sessions >= 1
    assert result.rate_limit_buckets >= 1
    tokens = {r[0] for r in owner.execute("SELECT token_hash FROM sessions")}
    assert "b" * 64 in tokens
    assert "a" * 64 not in tokens
    keys = {r[0] for r in owner.execute("SELECT bucket_key FROM rate_limit_buckets")}
    assert "busy" in keys
    assert "idle" not in keys
    assert owner.execute("SELECT count(*) FROM investigations WHERE title = 'kept'").fetchone() == (
        1,
    )
