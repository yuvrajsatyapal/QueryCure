from querydoctor.sql.validator import validate_select


def fp(sql: str) -> str:
    return validate_select(sql).fingerprint.digest


def test_fingerprint_ignores_whitespace_case_and_literal_values() -> None:
    a = fp("SELECT * FROM orders WHERE customer_id = 1024 LIMIT 20")
    b = fp("select *\n  from ORDERS\n where customer_id = 7   limit 5")

    assert a == b


def test_fingerprint_ignores_comments() -> None:
    assert fp("SELECT a FROM t -- note") == fp("SELECT a FROM t")


def test_fingerprint_differs_for_different_predicates_or_tables() -> None:
    base = fp("SELECT * FROM orders WHERE customer_id = 1")

    assert base != fp("SELECT * FROM orders WHERE status = 1")
    assert base != fp("SELECT * FROM invoices WHERE customer_id = 1")


def test_string_literals_are_normalized_too() -> None:
    assert fp("SELECT * FROM t WHERE s = 'a'") == fp("SELECT * FROM t WHERE s = 'bbb'")


def test_normalized_text_hides_literal_values() -> None:
    q = validate_select("SELECT * FROM t WHERE email = 'alice@example.com'")

    assert "alice@example.com" not in q.fingerprint.normalized_sql
    assert len(q.fingerprint.digest) == 64
