from querydoctor.sql.validator import validate_select


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
