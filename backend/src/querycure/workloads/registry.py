"""Deterministic demo workloads (BENCHMARK_ENGINE §11). Same ref ⇒ byte-identical tables.

Data is generated server-side from generate_series and integer arithmetic only. No random(),
now() or hashtext(): those change between runs or PostgreSQL versions and would break replay.
"""

import re
from collections.abc import Callable
from typing import Any

from psycopg import sql
from pydantic import BaseModel, ConfigDict

from querycure.core.errors import ValidationFailedError

Statement = sql.SQL | sql.Composed
EPOCH = sql.SQL("TIMESTAMPTZ '2026-01-01 00:00:00+00'")
_REF = re.compile(
    r"^(?P<name>[a-z_]+)@v(?P<version>\d+):sf=(?P<sf>\d+(\.\d{1,2})?):seed=(?P<seed>\d{1,9})$"
)
MIN_SF, MAX_SF = 0.01, 10.0


def mix(seed: int, salt: int, column: str = "g") -> sql.Composed:
    """Seeded 32-bit hash of the row number as a SQL expression.

    md5 is a fixed standard algorithm, so values are identical across PostgreSQL versions, and
    each salt gives an independent column. (A shifted multiplicative hash made salted columns
    correlated: "is this a hot order?" and "which hot customer?" moved in lockstep.)
    """
    return sql.SQL("(('x' || substr(md5({col} || {suffix}), 1, 8))::bit(32)::bigint)").format(
        col=sql.Identifier(column), suffix=sql.Literal(f":{seed}:{salt}")
    )


class ParamSet(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    values: list[Any]


class ExampleQuery(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    sql: str
    param_sets: list[ParamSet]


class WorkloadSpec(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    name: str
    version: int
    description: str
    injected_problem: str
    tables: list[str]
    example_queries: list[ExampleQuery]
    build: Callable[[float, int], list[Statement]]


class WorkloadRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    version: int
    scale_factor: float
    seed: int

    @classmethod
    def parse(cls, text: str) -> "WorkloadRef":
        match = _REF.match(text)
        if match is None:
            raise _invalid(text, "expected name@vN:sf=X:seed=N")
        ref = cls(
            name=match["name"],
            version=int(match["version"]),
            scale_factor=float(match["sf"]),
            seed=int(match["seed"]),
        )
        spec = WORKLOADS.get(ref.name)
        if spec is None or spec.version != ref.version:
            raise _invalid(text, "unknown workload or version")
        if not MIN_SF <= ref.scale_factor <= MAX_SF:
            raise _invalid(text, f"scale factor must be between {MIN_SF} and {MAX_SF}")
        return ref

    def __str__(self) -> str:
        return f"{self.name}@v{self.version}:sf={self.scale_factor:g}:seed={self.seed}"


def _invalid(text: str, reason: str) -> ValidationFailedError:
    return ValidationFailedError(
        "Invalid workload reference.", details=[{"field": "workload_id", "message": f"{reason}"}]
    )


def _orders_ecommerce(sf: float, seed: int) -> list[Statement]:
    customers, orders = round(200_000 * sf), round(1_000_000 * sf)
    m = {f"m{i}": mix(seed, i) for i in range(1, 9)}
    return [
        sql.SQL(
            "CREATE TABLE customers (id bigint PRIMARY KEY, email text NOT NULL, "
            "region smallint NOT NULL, created_at timestamptz NOT NULL)"
        ),
        sql.SQL(
            "INSERT INTO customers SELECT g, 'customer-' || g || '@example.test', {m1} % 8, "
            "{epoch} - ({m2} % 3650) * interval '1 day' FROM generate_series(1, {n}) g"
        ).format(epoch=EPOCH, n=sql.Literal(customers), **m),
        sql.SQL(
            "CREATE TABLE orders (id bigint PRIMARY KEY, customer_id bigint NOT NULL, "
            "status text NOT NULL, total numeric(10, 2) NOT NULL, created_at timestamptz NOT NULL)"
        ),
        # 10% of orders go to ten hot customers (1020-1029) so parameter sets can differ sharply.
        sql.SQL(
            "INSERT INTO orders SELECT g, "
            "CASE WHEN {m3} % 10 = 0 THEN 1020 + {m4} % 10 ELSE 1 + {m5} % {customers} END, "
            "(ARRAY['pending','paid','shipped','delivered','cancelled'])[1 + {m6} % 5], "
            "({m7} % 50000) / 100.0, "
            "{epoch} - ({m8} % 525600) * interval '1 minute' "
            "FROM generate_series(1, {n}) g"
        ).format(epoch=EPOCH, customers=sql.Literal(customers), n=sql.Literal(orders), **m),
        sql.SQL("ANALYZE customers"),
        sql.SQL("ANALYZE orders"),
    ]


def _rewrite_trap(sf: float, seed: int) -> list[Statement]:
    accounts = round(100_000 * sf)
    return [
        sql.SQL(
            "CREATE TABLE accounts "
            "(id bigint PRIMARY KEY, region_code int NOT NULL, name text NOT NULL)"
        ),
        sql.SQL(
            "INSERT INTO accounts SELECT g, {m1} % 50, 'account-' || g "
            "FROM generate_series(1, {n}) g"
        ).format(m1=mix(seed, 1), n=sql.Literal(accounts)),
        sql.SQL("CREATE TABLE closed_regions (region_code int)"),
        # The NULL row is the trap: NOT IN with a NULL in the subquery matches no rows at all.
        sql.SQL(
            "INSERT INTO closed_regions SELECT g FROM generate_series(0, 9) g UNION ALL SELECT NULL"
        ),
        sql.SQL("ANALYZE accounts"),
        sql.SQL("ANALYZE closed_regions"),
    ]


def _no_benefit(sf: float, seed: int) -> list[Statement]:
    rows = max(10, round(50 * sf))
    return [
        sql.SQL("CREATE TABLE app_settings (key text PRIMARY KEY, value text NOT NULL)"),
        sql.SQL(
            "INSERT INTO app_settings SELECT 'feature_' || g, 'value-' || {m1} % 1000 "
            "FROM generate_series(1, {n}) g"
        ).format(m1=mix(seed, 1), n=sql.Literal(rows)),
        sql.SQL("ANALYZE app_settings"),
    ]


WORKLOADS: dict[str, WorkloadSpec] = {
    spec.name: spec
    for spec in (
        WorkloadSpec(
            name="orders_ecommerce",
            version=1,
            description="Orders per customer, newest first. Ten hot customers own 10% of orders.",
            injected_problem="No index on orders(customer_id, created_at): sequential scan + sort.",
            tables=["customers", "orders"],
            example_queries=[
                ExampleQuery(
                    name="recent_orders_for_customer",
                    sql=(
                        "SELECT * FROM orders WHERE customer_id = $1 "
                        "ORDER BY created_at DESC LIMIT 20"
                    ),
                    param_sets=[
                        ParamSet(name="hot_customer", values=[1024]),
                        ParamSet(name="regular_customer", values=[7]),
                    ],
                )
            ],
            build=_orders_ecommerce,
        ),
        WorkloadSpec(
            name="rewrite_trap",
            version=1,
            description="Accounts outside closed regions; the closed list contains a NULL.",
            injected_problem="NOT IN over a nullable column: a NOT EXISTS rewrite changes results.",
            tables=["accounts", "closed_regions"],
            example_queries=[
                ExampleQuery(
                    name="open_region_accounts",
                    sql="SELECT count(*) FROM accounts "
                    "WHERE region_code NOT IN (SELECT region_code FROM closed_regions)",
                    param_sets=[ParamSet(name="default", values=[])],
                )
            ],
            build=_rewrite_trap,
        ),
        WorkloadSpec(
            name="no_benefit",
            version=1,
            description="Small settings table read by primary key.",
            injected_problem="None: the query is already optimal; no candidate should be verified.",
            tables=["app_settings"],
            example_queries=[
                ExampleQuery(
                    name="setting_by_key",
                    sql="SELECT value FROM app_settings WHERE key = $1",
                    param_sets=[ParamSet(name="existing_key", values=["feature_17"])],
                )
            ],
            build=_no_benefit,
        ),
    )
}


def build_statements(ref: WorkloadRef) -> list[Statement]:
    return WORKLOADS[ref.name].build(ref.scale_factor, ref.seed)
