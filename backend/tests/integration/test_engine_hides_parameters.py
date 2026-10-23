"""Bound parameters (user SQL text, ciphertext, token hashes) must never reach a log line
through an exception message. SQLAlchemy puts them into `str(exc)` unless the engine hides
them, and the API logs tracebacks of unexpected errors (`unhandled_error`, `sse_stream_failed`).

Not covered, by nature: PostgreSQL's own message can quote an input value ("invalid input syntax
for type integer: ..."); that text comes from the server, not from SQLAlchemy."""

import pytest
from sqlalchemy import exc, text

from querycure.db.engine import make_engine

pytestmark = pytest.mark.integration

MARKER = "parameter-that-must-not-be-logged"


async def test_statement_errors_do_not_carry_parameter_values(migrated_db: str) -> None:
    engine = make_engine(migrated_db, set_role="qc_app")
    try:
        async with engine.connect() as conn:
            with pytest.raises(exc.DBAPIError) as caught:
                await conn.execute(text("SELECT CAST(:v AS TEXT), 1 / 0"), {"v": MARKER})
        assert MARKER not in str(caught.value)
        assert "division by zero" in str(caught.value)
        assert "SELECT CAST" in str(caught.value)  # the statement itself stays for debugging
    finally:
        await engine.dispose()
