from querycure.sql.validator import validate_select


def test_extracts_tables_columns_order_and_limit() -> None:
    q = validate_select(
        "SELECT o.id, o.total FROM public.orders o "
        "WHERE o.customer_id = $1 ORDER BY o.created_at DESC LIMIT 20"
    )

    assert q.statement_type == "select"
    assert [(t.schema_name, t.name) for t in q.metadata.tables] == [("public", "orders")]
    assert {c.name for c in q.metadata.columns} == {"id", "total", "customer_id", "created_at"}
    assert q.metadata.order_by == ["o.created_at DESC"]
    assert q.metadata.limit == 20
    assert q.metadata.parameter_count == 1


def test_cte_names_are_not_reported_as_tables() -> None:
    q = validate_select("WITH r AS (SELECT * FROM orders) SELECT * FROM r JOIN customers c ON true")

    assert sorted(t.name for t in q.metadata.tables) == ["customers", "orders"]


def test_set_operation_statement_type() -> None:
    q = validate_select("SELECT 1 UNION SELECT 2")

    assert q.statement_type == "set_operation"
    assert q.metadata.limit is None


def test_original_text_is_preserved_byte_for_byte() -> None:
    sql = "SELECT  1  -- keep me"

    assert validate_select(sql).sql == sql


def test_unrecognized_unqualified_functions_are_listed_for_database_resolution() -> None:
    q = validate_select("SELECT lower(name), myfn(id), public_fn(1), pg_catalog.length('x') FROM t")

    # SQLGlot knows lower/length; myfn and public_fn must be resolved against pg_proc (T1.10).
    assert q.metadata.functions_to_resolve == ["myfn", "public_fn"]


def test_no_functions_to_resolve_for_plain_queries() -> None:
    assert validate_select("SELECT id FROM t").metadata.functions_to_resolve == []


def test_unquoted_identifiers_fold_to_lowercase_like_postgres() -> None:
    q = validate_select('SELECT * FROM Sales.Orders JOIN "MixedCase" m ON true')

    assert [(t.schema_name, t.name) for t in q.metadata.tables] == [
        (None, "MixedCase"),
        ("sales", "orders"),
    ]
