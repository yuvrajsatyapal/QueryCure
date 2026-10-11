"""L1 (validator) evasion attempts. L3 (read-only transaction) is tested with T1.10."""

import pytest

from querycure.core.errors import SqlNotAllowedError, SqlParseError
from querycure.sql.validator import validate_select

REJECTED = (SqlNotAllowedError, SqlParseError)


@pytest.mark.parametrize(
    "sql",
    [
        "SeLeCt 1;dRoP TaBlE t",
        "SELECT 1;\nDELETE FROM t",
        "SELECT 1 /* harmless */; DROP TABLE t",
        "/* SELECT */ DELETE FROM t",
        "-- SELECT\nDELETE FROM t",
        "WITH x AS MATERIALIZED (DELETE FROM t RETURNING *) SELECT * FROM x",
        "WITH RECURSIVE r AS (SELECT 1 UNION ALL SELECT 1 FROM r) "
        "SELECT * FROM r, (WITH d AS (DELETE FROM t RETURNING *) SELECT 1 FROM d) z",
        "SELECT * FROM t WHERE 1 = (SELECT 1 FROM pg_catalog.pg_sleep(30))",
        'SELECT "pg_sleep"(5)',
        "SELECT PG_CATALOG.PG_SLEEP(5)",
        "SELECT 1 UNION SELECT pg_read_file('/etc/passwd')::int",
        "SELECT 1\x00; DROP TABLE t",
    ],
)
def test_evasion_attempts_are_rejected(sql: str) -> None:
    with pytest.raises(REJECTED):
        validate_select(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 'DROP TABLE t; DELETE FROM t' AS harmless_text",
        "SELECT $$; DROP TABLE t; $$ AS dollar_quoted_text",
        'SELECT "delete" FROM "insert"',
    ],
)
def test_keywords_inside_strings_or_identifiers_are_data(sql: str) -> None:
    validate_select(sql)
