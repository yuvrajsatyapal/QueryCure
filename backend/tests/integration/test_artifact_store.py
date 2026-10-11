"""Artifact store under the restricted qd_app role (TESTING_STRATEGY §3)."""

import asyncio
import uuid
from collections.abc import AsyncIterator

import psycopg
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from querydoctor.core.errors import ArtifactConflictError, PayloadTooLargeError
from querydoctor.db.engine import make_engine
from querydoctor.replay import artifact_store as store
from querydoctor.replay.canonical import canonical_json
from querydoctor.replay.digest import digest

pytestmark = pytest.mark.integration


@pytest.fixture
async def app_engine(migrated_db: str) -> AsyncIterator[AsyncEngine]:
    engine = make_engine(migrated_db, set_role="qd_app")
    yield engine
    await engine.dispose()


async def test_store_json_canonicalizes_and_returns_digest(app_engine: AsyncEngine) -> None:
    async with app_engine.begin() as conn:
        art = await store.store_json(conn, kind="plan", value={"b": 1, "a": [1.0, "x"]})

    assert art.content == b'{"a":[1,"x"],"b":1}'
    assert art.sha256 == digest("qd-json-v1", art.content)
    assert (art.kind, art.media_type, art.canonicalization) == (
        "plan",
        "application/json",
        "qd-json-v1",
    )


async def test_duplicate_content_dedupes_to_the_same_row(app_engine: AsyncEngine) -> None:
    async with app_engine.begin() as conn:
        first = await store.store_json(conn, kind="schema_snapshot", value={"t": [1, 2]})
        second = await store.store_json(conn, kind="schema_snapshot", value={"t": [1, 2]})

    assert first.id == second.id


async def test_concurrent_inserts_of_same_digest_produce_one_row(
    app_engine: AsyncEngine, owner: psycopg.Connection
) -> None:
    value = {"concurrent": str(uuid.uuid4())}

    async def put() -> uuid.UUID:
        async with app_engine.begin() as conn:
            return (await store.store_json(conn, kind="agent_output", value=value)).id

    ids = await asyncio.gather(*(put() for _ in range(8)))

    sha = digest("qd-json-v1", canonical_json(value))
    count = owner.execute("SELECT count(*) FROM artifacts WHERE sha256 = %s", (sha,)).fetchone()
    assert len(set(ids)) == 1
    assert count == (1,)


async def test_raw_sql_is_stored_byte_for_byte(app_engine: AsyncEngine) -> None:
    sql = "SELECT *  FROM orders -- keep\r\nWHERE id = 1"
    async with app_engine.begin() as conn:
        art = await store.store_raw_sql(conn, sql)
        fetched = await store.get_artifact(conn, art.sha256)

    assert fetched is not None
    assert fetched.content == sql.encode()
    assert fetched.media_type == "text/sql"


async def test_nul_characters_survive_storage(app_engine: AsyncEngine) -> None:
    async with app_engine.begin() as conn:
        art = await store.store_json(conn, kind="agent_output", value={"s": "a\u0000b"})
        fetched = await store.get_artifact(conn, art.sha256)

    assert fetched is not None
    assert fetched.content == b'{"s":"a\\u0000b"}'


async def test_text_artifacts_use_text_profile(app_engine: AsyncEngine) -> None:
    async with app_engine.begin() as conn:
        art = await store.store_text(conn, kind="report_md", text="# Report\r\n\r\n")

    assert art.content == b"# Report\n"
    assert art.canonicalization == "qd-text-v1"


async def test_get_verifies_digest_and_detects_corruption(
    app_engine: AsyncEngine, owner: psycopg.Connection
) -> None:
    async with app_engine.begin() as conn:
        art = await store.store_json(conn, kind="plan", value={"tamper": str(uuid.uuid4())})
    owner.execute("UPDATE artifacts SET content = %s WHERE id = %s", (b'{"tamper":"x"}', art.id))

    async with app_engine.begin() as conn:
        with pytest.raises(store.ArtifactIntegrityError):
            await store.get_artifact(conn, art.sha256)


async def test_missing_artifact_returns_none(app_engine: AsyncEngine) -> None:
    async with app_engine.begin() as conn:
        assert await store.get_artifact(conn, "0" * 64) is None


async def test_same_digest_with_different_profile_is_a_conflict(
    app_engine: AsyncEngine, owner: psycopg.Connection
) -> None:
    content = b'"x"'
    sha = digest("qd-json-v1", content)
    owner.execute(
        "INSERT INTO artifacts (sha256, kind, media_type, content, canonicalization) "
        "VALUES (%s, 'query', 'text/sql', %s, 'qd-raw-v1')",
        (sha, content),
    )

    async with app_engine.begin() as conn:
        with pytest.raises(ArtifactConflictError):
            await store.store_json(conn, kind="plan", value="x")


async def test_oversize_artifacts_are_rejected(app_engine: AsyncEngine) -> None:
    async with app_engine.begin() as conn:
        with pytest.raises(PayloadTooLargeError):
            await store.store_text(conn, kind="report_md", text="x" * (5 * 1024 * 1024 + 1))


async def test_link_to_run_is_idempotent(
    app_engine: AsyncEngine, owner: psycopg.Connection
) -> None:
    run_id = uuid.uuid4()
    async with app_engine.begin() as conn:
        art = await store.store_raw_sql(conn, "SELECT 1")
        await store.link(
            conn, run_id=run_id, artifact_id=art.id, role="input.query", produced_by="intake"
        )
        await store.link(
            conn, run_id=run_id, artifact_id=art.id, role="input.query", produced_by="intake"
        )

    rows = owner.execute(
        "SELECT count(*) FROM run_artifacts WHERE run_id = %s", (run_id,)
    ).fetchone()
    assert rows == (1,)
