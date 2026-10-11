import pytest

from querycure.core.errors import SqlNotAllowedError, SqlParseError
from querycure.sql.validator import SqlPolicy, validate_select

CANONICAL = "SELECT * FROM orders WHERE customer_id = $1 ORDER BY created_at DESC LIMIT 20"


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1",
        CANONICAL,
        "WITH recent AS (SELECT * FROM orders WHERE created_at > now() - interval '1 day') "
        "SELECT count(*) FROM recent",
        "SELECT id FROM a UNION ALL SELECT id FROM b",
        "SELECT id FROM a INTERSECT SELECT id FROM b",
        "SELECT o.id, c.name FROM orders o JOIN customers c ON c.id = o.customer_id",
        "select lower(name), date_trunc('day', created_at) from users",
        "SELECT * FROM generate_series(1, 10)",
        "SELECT pg_catalog.lower('X')",
        "SELECT 1 -- trailing comment",
        "SELECT 1;",
    ],
)
def test_allows_read_only_selects(sql: str) -> None:
    validate_select(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO t VALUES (1)",
        "UPDATE t SET a = 1",
        "DELETE FROM t",
        "MERGE INTO t USING s ON t.id = s.id WHEN MATCHED THEN DELETE",
        "CREATE TABLE t (a int)",
        "CREATE INDEX i ON t (a)",
        "DROP TABLE t",
        "ALTER TABLE t ADD COLUMN b int",
        "TRUNCATE t",
        "COPY t TO PROGRAM 'curl evil'",
        "SET search_path = evil",
        "DO $$ BEGIN PERFORM 1; END $$",
        "VACUUM t",
        "CALL p()",
        "BEGIN",
        "EXPLAIN ANALYZE SELECT 1",
        "VALUES (1)",
        "TABLE t",
    ],
)
def test_rejects_non_select_statements(sql: str) -> None:
    with pytest.raises(SqlNotAllowedError):
        validate_select(sql)


def reason(exc: pytest.ExceptionInfo[SqlNotAllowedError]) -> str:
    return str(exc.value.details[0]["message"])


def test_rejects_data_modifying_cte_hidden_behind_select_root() -> None:
    with pytest.raises(SqlNotAllowedError) as info:
        validate_select("WITH d AS (DELETE FROM t RETURNING *) SELECT * FROM d")

    assert "DELETE" in reason(info)


@pytest.mark.parametrize(
    "sql",
    [
        "WITH i AS (INSERT INTO t VALUES (1) RETURNING id) SELECT * FROM i",
        "WITH u AS (UPDATE t SET a = 1 RETURNING id) SELECT * FROM u",
        "SELECT * FROM (WITH d AS (DELETE FROM t RETURNING *) SELECT * FROM d) x",
    ],
)
def test_rejects_nested_writes(sql: str) -> None:
    with pytest.raises(SqlNotAllowedError):
        validate_select(sql)


def test_rejects_select_into() -> None:
    with pytest.raises(SqlNotAllowedError, match="INTO"):
        validate_select("SELECT * INTO new_table FROM t")


@pytest.mark.parametrize("lock", ["FOR UPDATE", "FOR SHARE", "FOR NO KEY UPDATE", "FOR KEY SHARE"])
def test_rejects_row_locking(lock: str) -> None:
    with pytest.raises(SqlNotAllowedError, match="lock"):
        validate_select(f"SELECT * FROM t {lock}")


def test_rejects_multiple_statements() -> None:
    with pytest.raises(SqlNotAllowedError, match="single"):
        validate_select("SELECT 1; DROP TABLE t")


@pytest.mark.parametrize(
    "call",
    [
        "pg_sleep(10)",
        "pg_catalog.pg_sleep(10)",
        "PG_SLEEP(10)",
        "pg_sleep_for('1 day')",
        "dblink('host=evil', 'select 1')",
        "dblink_exec('x', 'drop table t')",
        "lo_import('/etc/passwd')",
        "pg_read_file('/etc/passwd')",
        "pg_read_binary_file('/etc/passwd')",
        "pg_ls_dir('.')",
        "set_config('search_path', 'evil', false)",
        "nextval('s')",
        "setval('s', 1)",
        "pg_terminate_backend(1)",
        "pg_cancel_backend(1)",
        "pg_advisory_lock(1)",
        "query_to_xml('delete from t', true, true, '')",
        "pg_notify('c', 'x')",
        "pg_reload_conf()",
    ],
)
def test_rejects_dangerous_functions(call: str) -> None:
    with pytest.raises(SqlNotAllowedError, match="function"):
        validate_select(f"SELECT {call}")


def test_dangerous_function_inside_where_and_subquery_is_found() -> None:
    with pytest.raises(SqlNotAllowedError):
        validate_select("SELECT * FROM t WHERE id IN (SELECT 1 WHERE pg_sleep(5) IS NOT NULL)")


def test_rejects_schema_qualified_user_function_by_default() -> None:
    with pytest.raises(SqlNotAllowedError) as info:
        validate_select("SELECT myschema.myfn(1)")

    assert reason(info) == "function myschema.myfn"


def test_user_function_allowed_with_explicit_opt_in() -> None:
    validate_select("SELECT myschema.myfn(1)", SqlPolicy(allow_user_functions=True))


def test_opt_in_never_unlocks_denylisted_functions() -> None:
    with pytest.raises(SqlNotAllowedError):
        validate_select("SELECT pg_sleep(1)", SqlPolicy(allow_user_functions=True))


@pytest.mark.parametrize("sql", ["", "   ", "\n\t", "-- only a comment"])
def test_empty_input_fails_closed(sql: str) -> None:
    with pytest.raises(SqlParseError):
        validate_select(sql)


@pytest.mark.parametrize(
    "sql", ["SELEC 1", "SELECT FROM WHERE", "SELECT (1", "SELECT 'unterminated"]
)
def test_unparseable_input_fails_closed(sql: str) -> None:
    with pytest.raises(SqlParseError):
        validate_select(sql)


def test_oversize_input_is_rejected_before_parsing() -> None:
    sql = "SELECT 1 " + " " * 100_001

    with pytest.raises(SqlNotAllowedError) as info:
        validate_select(sql)

    assert "100000" in reason(info)


def test_excessive_nesting_is_rejected() -> None:
    sql = "SELECT " + "(" * 300 + "1" + ")" * 300

    with pytest.raises((SqlNotAllowedError, SqlParseError)):
        validate_select(sql)


def test_rejection_details_name_the_query_field() -> None:
    with pytest.raises(SqlNotAllowedError) as info:
        validate_select("DELETE FROM t")

    assert info.value.details[0]["field"] == "query"
