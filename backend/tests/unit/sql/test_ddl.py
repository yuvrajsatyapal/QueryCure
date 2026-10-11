import pytest

from querydoctor.core.errors import PayloadTooLargeError, SqlParseError
from querydoctor.sql.ddl import parse_ddl

PG_DUMP_STYLE = """
SET statement_timeout = 0;
CREATE TABLE public.orders (
  id bigint NOT NULL,
  customer_id integer NOT NULL,
  created_at timestamp with time zone DEFAULT now() NOT NULL,
  total numeric(10,2),
  CONSTRAINT orders_total_check CHECK (total >= 0)
);
CREATE TABLE customers (id serial PRIMARY KEY, email varchar(255) UNIQUE);
ALTER TABLE ONLY public.orders ADD CONSTRAINT orders_pkey PRIMARY KEY (id);
CREATE INDEX orders_customer_idx ON public.orders USING btree (customer_id, created_at DESC);
CREATE UNIQUE INDEX customers_email_lower ON customers (lower(email)) WHERE email IS NOT NULL;
COMMENT ON TABLE public.orders IS 'orders';
"""


def test_tables_columns_and_constraints() -> None:
    schema = parse_ddl(PG_DUMP_STYLE)

    orders = next(t for t in schema.tables if t.name == "orders")
    assert orders.schema_name == "public"
    assert [c.name for c in orders.columns] == ["id", "customer_id", "created_at", "total"]
    assert [c.not_null for c in orders.columns] == [True, True, True, False]
    assert orders.primary_key == ["id"]
    customers = next(t for t in schema.tables if t.name == "customers")
    assert customers.schema_name is None
    assert customers.primary_key == ["id"]


def test_indexes_keep_column_order_direction_uniqueness_and_predicate() -> None:
    schema = parse_ddl(PG_DUMP_STYLE)

    by_name = {i.name: i for i in schema.indexes}
    assert by_name["orders_customer_idx"].columns == ["customer_id", "created_at DESC"]
    assert by_name["orders_customer_idx"].method == "btree"
    assert by_name["orders_customer_idx"].table == "public.orders"
    assert by_name["customers_email_lower"].unique is True
    assert by_name["customers_email_lower"].predicate == "email IS NOT NULL"


def test_irrelevant_statements_become_warnings_not_errors() -> None:
    schema = parse_ddl(PG_DUMP_STYLE)

    assert any("SET" in w for w in schema.warnings)
    assert any("COMMENT" in w for w in schema.warnings)


def test_data_statements_are_skipped_never_interpreted() -> None:
    schema = parse_ddl("CREATE TABLE t (a int); INSERT INTO t VALUES (1); DROP TABLE t;")

    assert [t.name for t in schema.tables] == ["t"]
    assert len(schema.warnings) == 2


def test_unparseable_ddl_fails_closed() -> None:
    with pytest.raises(SqlParseError):
        parse_ddl("CREATE TABLE (")


def test_empty_ddl_is_an_error() -> None:
    with pytest.raises(SqlParseError):
        parse_ddl("  -- nothing here\n")


def test_ddl_size_limit() -> None:
    with pytest.raises(PayloadTooLargeError):
        parse_ddl("CREATE TABLE t (a int);" + " " * (1024 * 1024))
