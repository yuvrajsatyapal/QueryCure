import pytest

from querycure.core.errors import SandboxPolicyError
from querycure.sql.ddl_allowlist import validate_candidate, validate_ddl

TABLES = {"orders", "customers"}


@pytest.mark.parametrize(
    ("statement", "kind", "table", "columns"),
    [
        ("CREATE INDEX ON orders (customer_id, created_at DESC)", "create_index", "orders",
         ["customer_id", "created_at"]),
        ("create index if not exists orders_cust_idx on orders using btree (customer_id) "
         "include (total) where status = 'paid';", "create_index", "orders", ["customer_id"]),
        ("CREATE INDEX ON public.orders (lower(status))", "create_index", "orders", []),
        ('CREATE INDEX "Odd Name" ON "orders" ("customer_id" NULLS LAST)', "create_index",
         "orders", ["customer_id"]),
        ("CREATE STATISTICS s1 (dependencies, ndistinct) ON customer_id, status FROM orders",
         "create_statistics", "orders", ["customer_id", "status"]),
        ("ANALYZE orders", "analyze", "orders", []),
        ("ANALYZE customers (region)", "analyze", "customers", ["region"]),
    ],
)  # fmt: skip
def test_allowed_forms(statement: str, kind: str, table: str, columns: list[str]) -> None:
    ddl = validate_ddl(statement, allowed_tables=TABLES)

    assert (ddl.kind, ddl.table, ddl.columns) == (kind, table, columns)
    assert not ddl.statement.endswith(";")


@pytest.mark.parametrize(
    ("statement", "reason"),
    [
        ("DROP TABLE orders", "statement"),
        ("CREATE TABLE x (id int)", "statement"),
        ("CREATE UNIQUE INDEX ON orders (id)", "UNIQUE"),
        ("CREATE INDEX CONCURRENTLY ON orders (id)", "CONCURRENTLY"),
        ("CREATE INDEX ON accounts (id)", "not referenced"),
        ("CREATE INDEX ON other.orders (id)", "schema"),
        ("CREATE INDEX ON orders USING spgist_custom (id)", "method"),
        ("CREATE INDEX ON orders (id); DROP TABLE orders", "single statement"),
        ("CREATE INDEX ON orders (id) -- comment", "comment"),
        ("CREATE INDEX ON orders (id) /* x */", "comment"),
        ("CREATE INDEX ON orders ((pg_sleep(1)::int))", "function"),
        ("CREATE INDEX ON orders (id) WHERE pg_sleep(1) IS NOT NULL", "function"),
        ("CREATE INDEX ON orders (id) WHERE id IN (SELECT 1 FROM pg_authid)", "predicate"),
        ("CREATE INDEX ON orders (id) WITH (fillfactor = 10)", "unexpected"),
        ("CREATE INDEX ON orders (id) TABLESPACE pg_default", "unexpected"),
        ("CREATE INDEX ON ONLY orders (id)", "ONLY"),
        ("CREATE INDEX ON orders ()", "empty"),
        ("CREATE INDEX ON orders (id", "parenthes"),
        ("CREATE INDEX ON orders (id) WHERE x = $$a$$", "dollar"),
        ("CREATE INDEX ON orders (id) WHERE status = E'\\x41'", "escape"),
        ("CREATE STATISTICS s (evil) ON a, b FROM orders", "statistics kind"),
        ("CREATE STATISTICS s ON a FROM orders", "two columns"),
        ("ANALYZE", "table"),
        ("ANALYZE VERBOSE orders", "VERBOSE"),
        ("ANALYZE orders, customers", "unexpected"),
        ("VACUUM orders", "statement"),
        ("SET work_mem = '1GB'", "statement"),
        ("", "empty"),
    ],
)
def test_refused_forms(statement: str, reason: str) -> None:
    with pytest.raises(SandboxPolicyError, match=f"(?i){reason}"):
        validate_ddl(statement, allowed_tables=TABLES)


QUERY = "SELECT * FROM orders WHERE customer_id = $1 ORDER BY created_at DESC LIMIT 20"


def test_index_candidate_must_be_all_index_ddl() -> None:
    with pytest.raises(SandboxPolicyError, match="create_index"):
        validate_candidate(kind="create_index", ddl=["ANALYZE orders"], query=None, baseline=QUERY)


def test_rewrite_candidate_is_a_validated_select_without_ddl() -> None:
    validated = validate_candidate(
        kind="query_rewrite",
        ddl=[],
        query="SELECT * FROM orders WHERE customer_id = $1 ORDER BY created_at DESC, id LIMIT 20",
        baseline=QUERY,
    )

    assert validated.ddl == []

    with pytest.raises(SandboxPolicyError, match="SELECT"):
        validate_candidate(kind="query_rewrite", ddl=[], query="DELETE FROM orders", baseline=QUERY)
    with pytest.raises(SandboxPolicyError, match="parameters"):
        validate_candidate(
            kind="query_rewrite", ddl=[], query="SELECT * FROM orders", baseline=QUERY
        )


def test_extended_statistics_needs_an_analyze_to_take_effect() -> None:
    with pytest.raises(SandboxPolicyError, match="ANALYZE"):
        validate_candidate(
            kind="extended_statistics",
            ddl=["CREATE STATISTICS s ON customer_id, status FROM orders"],
            query=None,
            baseline=QUERY,
        )
    ok = validate_candidate(
        kind="extended_statistics",
        ddl=["CREATE STATISTICS s ON customer_id, status FROM orders", "ANALYZE orders"],
        query=None,
        baseline=QUERY,
    )
    assert [d.kind for d in ok.ddl] == ["create_statistics", "analyze"]


def test_candidates_are_bounded() -> None:
    with pytest.raises(SandboxPolicyError, match="at most"):
        validate_candidate(
            kind="create_index",
            ddl=[f"CREATE INDEX ON orders (c{i})" for i in range(5)],
            query=None,
            baseline=QUERY,
        )
    with pytest.raises(SandboxPolicyError, match="no DDL"):
        validate_candidate(kind="create_index", ddl=[], query=None, baseline=QUERY)
