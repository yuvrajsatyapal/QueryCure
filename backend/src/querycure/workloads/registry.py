"""Deterministic demo workloads (BENCHMARK_ENGINE §11). Same ref ⇒ byte-identical tables.

Data is generated server-side from generate_series and integer arithmetic only. No random(),
now() or hashtext(): those change between runs or PostgreSQL versions and would break replay.
"""

import re
from collections.abc import Callable
from typing import Any, Self

from psycopg import sql
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from querycure.core.errors import ValidationFailedError

Statement = sql.SQL | sql.Composed
EPOCH = sql.SQL("TIMESTAMPTZ '2026-01-01 00:00:00+00'")
_REF = re.compile(
    r"^(?P<name>[a-z_]+)@v(?P<version>\d+):sf=(?P<sf>\d+(\.\d{1,2})?):seed=(?P<seed>\d{1,9})$"
)
# A fixed dataset is named by its content: `name@vN:data=<first 12 hex of the CSV's SHA-256>`.
# fullmatch, not `$`: a trailing newline must not slip through.
_FIXED_REF = re.compile(r"(?P<name>[a-z_]+)@v(?P<version>\d+):data=(?P<data>[0-9a-f]{12})")
DATA_ID_LENGTH = 12
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
    edge_case: bool = False


class ExampleQuery(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    sql: str
    param_sets: list[ParamSet]


class Reconciliation(BaseModel):
    """Facts about the source file that the loaded table must reproduce exactly."""

    model_config = ConfigDict(frozen=True)

    rows: int
    sum_quantity: int
    sum_quantity_times_price: str  # exact decimal text, compared as numeric
    null_customers: int
    null_descriptions: int


class FixedDataset(BaseModel):
    """A real data set loaded from a local file instead of generated (BENCHMARK_ENGINE §11)."""

    model_config = ConfigDict(frozen=True)

    csv_sha256: str
    csv_bytes: int
    folder: str  # under the operator's datasets directory (loader.default_csv_path)
    filename: str
    table: str
    columns: list[str]
    reconciliation: Reconciliation
    source_url: str
    licence: str
    citation: str

    @field_validator("csv_sha256")
    @classmethod
    def _full_lowercase_digest(cls, value: str) -> str:
        if re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise ValueError("csv_sha256 must be 64 lowercase hex digits")
        return value

    @property
    def data_id(self) -> str:
        return self.csv_sha256[:DATA_ID_LENGTH]


class WorkloadSpec(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    name: str
    version: int
    description: str
    injected_problem: str
    tables: list[str]
    example_queries: list[ExampleQuery]
    build: Callable[[float, int], list[Statement]] | None = None
    fixed: FixedDataset | None = None

    @model_validator(mode="after")
    def _generated_or_fixed(self) -> Self:
        if (self.build is None) == (self.fixed is None):
            raise ValueError("a workload is either generated (build) or fixed (fixed)")
        return self


class WorkloadRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    version: int
    scale_factor: float | None = None
    seed: int | None = None
    data_id: str | None = None

    @model_validator(mode="after")
    def _generated_or_fixed(self) -> Self:
        generated = self.scale_factor is not None and self.seed is not None
        partial = (self.scale_factor is None) != (self.seed is None)
        if partial or generated == (self.data_id is not None):
            raise ValueError("a ref is either sf+seed (generated) or data_id (fixed)")
        return self

    @classmethod
    def parse(cls, text: str) -> "WorkloadRef":
        if ":data=" in text:
            return cls._parse_fixed(text)
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
        if spec.fixed is not None:
            raise _invalid(text, "this workload is a fixed dataset: use name@vN:data=<id>")
        if ref.scale_factor is None or not MIN_SF <= ref.scale_factor <= MAX_SF:
            raise _invalid(text, f"scale factor must be between {MIN_SF} and {MAX_SF}")
        return ref

    @classmethod
    def _parse_fixed(cls, text: str) -> "WorkloadRef":
        match = _FIXED_REF.fullmatch(text)
        if match is None:
            raise _invalid(text, "expected name@vN:data=<12 lowercase hex digits>")
        spec = WORKLOADS.get(match["name"])
        if spec is None or spec.version != int(match["version"]):
            raise _invalid(text, "unknown workload or version")
        if spec.fixed is None:
            raise _invalid(text, "this workload is generated: use name@vN:sf=X:seed=N")
        if spec.fixed.data_id != match["data"]:
            raise _invalid(text, "the data id does not match the pinned dataset")
        return cls(name=spec.name, version=spec.version, data_id=match["data"])

    def __str__(self) -> str:
        if self.data_id is not None:
            return f"{self.name}@v{self.version}:data={self.data_id}"
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


def _join_fanout(sf: float, seed: int) -> list[Statement]:
    authors, posts = max(500, round(20_000 * sf)), round(500_000 * sf)
    m = {f"m{i}": mix(seed, 20 + i) for i in range(1, 6)}
    return [
        # tier is a function of country, so `country = $1 AND tier = $2` is estimated as two
        # independent predicates and the matching authors are underestimated (misestimate).
        sql.SQL(
            "CREATE TABLE authors (id bigint PRIMARY KEY, country smallint NOT NULL, "
            "tier smallint NOT NULL, handle text NOT NULL)"
        ),
        sql.SQL(
            "INSERT INTO authors SELECT g, {m1} % 50, ({m1} % 50) % 3, 'author-' || g "
            "FROM generate_series(1, {n}) g"
        ).format(n=sql.Literal(authors), **m),
        # posts.author_id is a foreign key by meaning but has no index (the injected problem).
        sql.SQL(
            "CREATE TABLE posts (id bigint PRIMARY KEY, author_id bigint NOT NULL, "
            "words int NOT NULL, published_at timestamptz NOT NULL)"
        ),
        sql.SQL(
            "INSERT INTO posts SELECT g, 1 + {m2} % {authors}, 50 + {m3} % 2000, "
            "{epoch} - ({m4} % 525600) * interval '1 minute' FROM generate_series(1, {n}) g"
        ).format(epoch=EPOCH, authors=sql.Literal(authors), n=sql.Literal(posts), **m),
        sql.SQL("ANALYZE authors"),
        sql.SQL("ANALYZE posts"),
    ]


def _stale_stats(sf: float, seed: int) -> list[Statement]:
    accounts, events = max(500, round(50_000 * sf)), round(200_000 * sf)
    m = {f"m{i}": mix(seed, 40 + i) for i in range(1, 5)}
    return [
        sql.SQL("CREATE TABLE accounts (id bigint PRIMARY KEY, plan text NOT NULL)"),
        sql.SQL(
            "INSERT INTO accounts SELECT g, (ARRAY['free','pro','team'])[1 + {m1} % 3] "
            "FROM generate_series(1, {n}) g"
        ).format(n=sql.Literal(accounts), **m),
        sql.SQL(
            "CREATE TABLE events (id bigint PRIMARY KEY, account_id bigint NOT NULL, "
            "kind text NOT NULL, amount int NOT NULL)"
        ),
        sql.SQL("CREATE INDEX events_kind_idx ON events (kind)"),
        sql.SQL(
            "INSERT INTO events SELECT g, 1 + {m2} % {accounts}, 'view', {m3} % 100 "
            "FROM generate_series(1, {n}) g"
        ).format(accounts=sql.Literal(accounts), n=sql.Literal(events), **m),
        sql.SQL("ANALYZE accounts"),
        sql.SQL("ANALYZE events"),
        # The injected problem: a bulk load after ANALYZE. Statistics say every event is a
        # 'view', so 'purchase' is estimated at ~1 row although half the table now matches.
        sql.SQL(
            "INSERT INTO events SELECT {base} + g, 1 + {m4} % {accounts}, 'purchase', "
            "{m3} % 500 FROM generate_series(1, {n}) g"
        ).format(
            base=sql.Literal(events), accounts=sql.Literal(accounts), n=sql.Literal(events), **m
        ),
    ]


def _index_regression(sf: float, seed: int) -> list[Statement]:
    tickets = round(300_000 * sf)
    m = {f"m{i}": mix(seed, 60 + i) for i in range(1, 4)}
    return [
        sql.SQL(
            "CREATE TABLE tickets (id bigint PRIMARY KEY, status text NOT NULL, "
            "priority smallint NOT NULL, opened_at timestamptz NOT NULL)"
        ),
        # Rows are inserted in hash order, so opened_at order is unrelated to heap order.
        # 'escalated' (1%) exists only among the newest 1% of tickets: an index on opened_at
        # finds 10 'open' tickets at once but walks ~99% of the index for 'escalated'.
        sql.SQL(
            "INSERT INTO tickets SELECT g, "
            "CASE WHEN t >= {late} THEN 'escalated' "
            "WHEN {m1} % 10 < 3 THEN 'open' ELSE 'closed' END, {m2} % 5, "
            "{epoch} - interval '400 days' + t * interval '1 minute' "
            "FROM (SELECT g, ({m3} % {n}) AS t FROM generate_series(1, {n}) g) s"
        ).format(
            epoch=EPOCH, late=sql.Literal(tickets - tickets // 100), n=sql.Literal(tickets), **m
        ),
        sql.SQL("ANALYZE tickets"),
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
        WorkloadSpec(
            name="join_fanout",
            version=1,
            description="Posts by authors from one country and tier; posts.author_id is "
            "unindexed and tier depends on country.",
            injected_problem="Join on an unindexed foreign-key column, with a correlated "
            "predicate pair the planner underestimates.",
            tables=["authors", "posts"],
            example_queries=[
                ExampleQuery(
                    name="posts_by_country_tier",
                    sql=(
                        "SELECT p.id, p.words FROM authors a JOIN posts p ON p.author_id = a.id "
                        "WHERE a.country = $1 AND a.tier = $2"
                    ),
                    param_sets=[
                        ParamSet(name="country_7", values=[7, 1]),
                        ParamSet(name="country_42", values=[42, 0]),
                        ParamSet(name="no_match", values=[7, 2], edge_case=True),
                    ],
                )
            ],
            build=_join_fanout,
        ),
        WorkloadSpec(
            name="stale_stats",
            version=1,
            description="Events joined to accounts; half the events were loaded after the "
            "last ANALYZE with a kind the statistics have never seen.",
            injected_problem="Stale statistics: 'purchase' is estimated at ~1 row, so the "
            "planner picks a nested loop over ~half the table.",
            tables=["accounts", "events"],
            example_queries=[
                ExampleQuery(
                    name="revenue_by_kind",
                    sql=(
                        "SELECT count(*), sum(e.amount) FROM events e "
                        "JOIN accounts a ON a.id = e.account_id WHERE e.kind = $1"
                    ),
                    param_sets=[
                        ParamSet(name="purchases", values=["purchase"]),
                        ParamSet(name="views", values=["view"]),
                    ],
                )
            ],
            build=_stale_stats,
        ),
        WorkloadSpec(
            name="index_regression",
            version=1,
            description="Oldest tickets with a status; 'escalated' tickets are all recent.",
            injected_problem="An index on opened_at helps common statuses but walks almost "
            "the whole index for 'escalated' (ORDER BY ... LIMIT trap).",
            tables=["tickets"],
            example_queries=[
                ExampleQuery(
                    name="oldest_by_status",
                    sql="SELECT * FROM tickets WHERE status = $1 ORDER BY opened_at, id LIMIT 10",
                    param_sets=[
                        ParamSet(name="open", values=["open"]),
                        ParamSet(name="escalated", values=["escalated"]),
                    ],
                )
            ],
            build=_index_regression,
        ),
        WorkloadSpec(
            name="online_retail_ii",
            version=1,
            description="Real UK online-retail invoice lines, December 2009 to December 2011 "
            "(UCI Online Retail II). Loaded as published: duplicates, cancellations, negative "
            "quantities and missing customer ids are kept.",
            injected_problem="None injected: the data is real. The primary query reads one "
            "customer's newest lines and has no supporting index.",
            tables=["retail_lines"],
            example_queries=[
                ExampleQuery(
                    name="recent_lines_for_customer",
                    sql=(
                        "SELECT invoice_no, invoice_date, stock_code, quantity, unit_price "
                        "FROM retail_lines WHERE customer_id = $1 "
                        "ORDER BY invoice_date DESC, line_id DESC LIMIT 50"
                    ),
                    param_sets=[
                        ParamSet(name="heaviest_customer", values=[17841]),
                        ParamSet(name="median_customer", values=[12413]),
                        ParamSet(name="single_line_customer", values=[12382]),
                        ParamSet(name="nonexistent_customer", values=[18288], edge_case=True),
                    ],
                ),
                ExampleQuery(
                    name="lines_of_invoice",
                    sql="SELECT * FROM retail_lines WHERE invoice_no = $1 ORDER BY line_id",
                    param_sets=[
                        ParamSet(name="typical_invoice", values=["489450"]),
                        ParamSet(name="largest_invoice", values=["537434"]),
                        ParamSet(name="cancellation_invoice", values=["C489449"]),
                        ParamSet(name="missing_invoice", values=["999999"], edge_case=True),
                    ],
                ),
                ExampleQuery(
                    name="customer_totals_in_window",
                    sql=(
                        "SELECT customer_id, count(*), sum(quantity * unit_price) "
                        "FROM retail_lines WHERE invoice_date >= $1 AND invoice_date < $2 "
                        "AND customer_id IS NOT NULL GROUP BY customer_id"
                    ),
                    param_sets=[
                        ParamSet(
                            name="one_day", values=["2010-12-01 00:00:00", "2010-12-02 00:00:00"]
                        ),
                        ParamSet(
                            name="one_month", values=["2010-12-01 00:00:00", "2011-01-01 00:00:00"]
                        ),
                        ParamSet(
                            name="full_range", values=["2009-12-01 00:00:00", "2011-12-10 00:00:00"]
                        ),
                    ],
                ),
            ],
            fixed=FixedDataset(
                csv_sha256="b3471c34b27325f6f68aa58184689a076669885e27d15ebde92dcb198efd9840",
                csv_bytes=132_964_983,
                folder="online-retail-ii",
                filename="online_retail_ii.csv",
                table="retail_lines",
                columns=[
                    "line_id",
                    "source_sheet",
                    "source_row",
                    "invoice_no",
                    "stock_code",
                    "description",
                    "quantity",
                    "invoice_date",
                    "unit_price",
                    "customer_id",
                    "country",
                ],
                reconciliation=Reconciliation(
                    rows=1_067_371,
                    sum_quantity=10_608_492,
                    sum_quantity_times_price="19287250.568",
                    null_customers=243_007,
                    null_descriptions=4_382,
                ),
                source_url="https://archive.ics.uci.edu/dataset/502/online+retail+ii",
                licence="CC BY 4.0",
                citation=(
                    "Chen, D. (2012). Online Retail II [Dataset]. UCI Machine Learning "
                    "Repository. https://doi.org/10.24432/C5CG6D"
                ),
            ),
        ),
    )
}


def build_statements(ref: WorkloadRef) -> list[Statement]:
    spec = WORKLOADS[ref.name]
    if spec.build is None or ref.scale_factor is None or ref.seed is None:
        raise ValueError(f"{ref.name} is a fixed dataset: it is loaded from a file, not generated")
    return spec.build(ref.scale_factor, ref.seed)
