"""Fixed-dataset templates against the real sandbox server (Part B, M5/M8).

Needs the compose `sandbox-db` (through `sandbox-relay`) only. The first group runs on a tiny
stand-in file pinned the way the registry pins the real one, so every code path is the real one.
The `real data` group needs the actual CSV (see tests/security/test_fixed_dataset_loader.py) and
is skipped, naming the file, when it is absent. No benchmark runs, no LLM is called.
"""

import datetime as dt
import hashlib
import uuid
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg.postgres import types

from querycure.benchmark.correctness import kinds_for_oids
from querycure.benchmark.executor import ArmRunner, Sample
from querycure.core.errors import SandboxUnavailableError
from querycure.replay.canonical.row_v1 import row_hash
from querycure.sandbox.provisioner import (
    BENCH_ROLE,
    FIXED_TEMPLATE_BUILDER,
    SandboxProvisioner,
    Template,
    template_name,
)
from querycure.workloads import registry
from querycure.workloads.loader import FixedDatasetError, default_csv_path
from querycure.workloads.registry import WORKLOADS, WorkloadRef
from tests.integration.fixed_dataset_fixtures import CSV, dataset, ref
from tests.integration.sandbox_fixtures import SANDBOX_URL, clone_names

pytestmark = pytest.mark.integration

LINE_1_ROW_HASH = "32d694fc830f6db91fdb391d3d3e600dfc07aa5fa7fa62821e388730c63d02cf"
ROW_CAP = 100_000


def database_exists(name: str) -> bool:
    with psycopg.connect(SANDBOX_URL, autocommit=True) as conn:
        return (
            conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone()
            is not None
        )


def build_databases() -> list[str]:
    with psycopg.connect(SANDBOX_URL, autocommit=True) as conn:
        rows = conn.execute(
            "SELECT datname FROM pg_database WHERE datname LIKE 'qc\\_tplbuild\\_%'"
        ).fetchall()
    return [r[0] for r in rows]


@pytest.fixture
def stand_in(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, provisioner: SandboxProvisioner
) -> Iterator[tuple[WorkloadRef, Path]]:
    """The registry pins a tiny file instead of the real one for the length of a test."""
    pinned = dataset()
    spec = WORKLOADS["online_retail_ii"]
    monkeypatch.setitem(
        registry.WORKLOADS, "online_retail_ii", spec.model_copy(update={"fixed": pinned})
    )
    path = tmp_path / "online_retail_ii.csv"
    path.write_bytes(CSV)
    live = ref(pinned)
    yield live, path
    with provisioner.lease(timeout_seconds=60) as lease:
        lease.drop_template(live)
        lease.cleanup_orphans()


def runner(provisioner: SandboxProvisioner, clone: str) -> ArmRunner:
    return ArmRunner(provisioner.bench_conninfo(clone), row_cap=ROW_CAP)


def rows_of(sample: Sample) -> int:
    assert sample.failure is None, (sample.failure, sample.error_code)
    assert sample.fingerprint is not None
    return sample.fingerprint.rows


# --- the stand-in file -------------------------------------------------------------------------


def test_a_fixed_template_is_built_once_and_reused(
    provisioner: SandboxProvisioner, stand_in: tuple[WorkloadRef, Path]
) -> None:
    live, path = stand_in
    with provisioner.lease(timeout_seconds=60) as lease:
        first = lease.ensure_template(live, source=path)
        second = lease.ensure_template(live)  # no source needed once it is built

    assert first == second
    assert first.name == template_name(live)
    assert len(first.data_digest) == 64
    with psycopg.connect(SANDBOX_URL, autocommit=True) as conn:
        row = conn.execute(
            "SELECT datistemplate, datallowconn, pg_get_userbyid(datdba), "
            "shobj_description(oid, 'pg_database') FROM pg_database WHERE datname = %s",
            (first.name,),
        ).fetchone()
    assert row == (
        True,
        False,
        BENCH_ROLE,
        f"{live}|{FIXED_TEMPLATE_BUILDER}|{first.data_digest}",
    )


def test_rebuilding_gives_the_same_data_digest(
    provisioner: SandboxProvisioner, stand_in: tuple[WorkloadRef, Path]
) -> None:
    live, path = stand_in
    with provisioner.lease(timeout_seconds=60) as lease:
        original = lease.ensure_template(live, source=path)
        lease.drop_template(live)
        rebuilt = lease.ensure_template(live, source=path)

    assert rebuilt.data_digest == original.data_digest


def test_a_missing_fixed_template_asks_for_the_local_build(
    provisioner: SandboxProvisioner, stand_in: tuple[WorkloadRef, Path]
) -> None:
    live, _ = stand_in
    with (
        provisioner.lease(timeout_seconds=60) as lease,
        pytest.raises(SandboxUnavailableError, match="build-template"),
    ):
        lease.ensure_template(live)

    assert not database_exists(template_name(live))


def test_a_refused_source_builds_no_database_at_all(
    provisioner: SandboxProvisioner, stand_in: tuple[WorkloadRef, Path], tmp_path: Path
) -> None:
    live, _ = stand_in
    wrong = tmp_path / "wrong.csv"
    wrong.write_bytes(CSV + b"x")
    before = build_databases()

    with provisioner.lease(timeout_seconds=60) as lease, pytest.raises(FixedDatasetError):
        lease.ensure_template(live, source=wrong)

    assert not database_exists(template_name(live))
    assert build_databases() == before


def test_a_failed_load_leaves_no_template_and_no_half_built_database(
    monkeypatch: pytest.MonkeyPatch,
    provisioner: SandboxProvisioner,
    stand_in: tuple[WorkloadRef, Path],
) -> None:
    live, path = stand_in
    pinned = WORKLOADS["online_retail_ii"].fixed
    assert pinned is not None
    wrong_facts = pinned.reconciliation.model_copy(update={"rows": 99})
    monkeypatch.setitem(
        registry.WORKLOADS,
        "online_retail_ii",
        WORKLOADS["online_retail_ii"].model_copy(
            update={"fixed": pinned.model_copy(update={"reconciliation": wrong_facts})}
        ),
    )
    before = build_databases()

    with (
        provisioner.lease(timeout_seconds=60) as lease,
        pytest.raises(FixedDatasetError, match="rows: expected 99"),
    ):
        lease.ensure_template(live, source=path)

    assert not database_exists(template_name(live))
    assert build_databases() == before


def test_a_clone_is_readable_by_the_bench_role_and_keeps_the_load_statistics(
    provisioner: SandboxProvisioner, stand_in: tuple[WorkloadRef, Path]
) -> None:
    live, path = stand_in
    experiment = uuid.uuid4()
    with provisioner.lease(timeout_seconds=60) as lease:
        template = lease.ensure_template(live, source=path)
        clone = lease.create_clone(template, experiment, 0)
        try:
            with psycopg.connect(**provisioner.bench_conninfo(clone)) as conn:
                count = conn.execute("SELECT count(*) FROM retail_lines").fetchone()
                owner = conn.execute(
                    "SELECT pg_get_userbyid(relowner), reloptions FROM pg_class "
                    "WHERE relname = 'retail_lines'"
                ).fetchone()
                stats = conn.execute(
                    "SELECT count(*) FROM pg_stats WHERE tablename = 'retail_lines'"
                ).fetchone()
        finally:
            lease.drop_clone(clone)

    assert count == (4,)
    assert owner is not None
    assert owner[0] == BENCH_ROLE
    assert "autovacuum_enabled=false" in owner[1]
    assert stats is not None
    assert stats[0] > 0
    assert clone_names() == []


def test_registered_example_queries_bind_their_parameters(
    provisioner: SandboxProvisioner, stand_in: tuple[WorkloadRef, Path]
) -> None:
    """Integers, invoice text and date strings, bound as the benchmark engine binds them."""
    live, path = stand_in
    with provisioner.lease(timeout_seconds=60) as lease:
        template = lease.ensure_template(live, source=path)
        clone = lease.create_clone(template, uuid.uuid4(), 0)
        try:
            arm = runner(provisioner, clone)
            try:
                for query in WORKLOADS["online_retail_ii"].example_queries:
                    for param_set in query.param_sets:
                        sample = arm.execute(query.sql, param_set.values)
                        rows_of(sample)  # no error, whatever the row count
                one_day = arm.execute(
                    WORKLOADS["online_retail_ii"].example_queries[2].sql,
                    ["2009-12-01 00:00:00", "2009-12-02 00:00:00"],
                )
                assert (
                    rows_of(one_day) == 1
                )  # customer 13085 only; the NULL-customer line is excluded
            finally:
                arm.close()
        finally:
            lease.drop_clone(clone)


def test_the_row_profile_hashes_a_loaded_row_to_the_golden(
    provisioner: SandboxProvisioner, stand_in: tuple[WorkloadRef, Path]
) -> None:
    live, path = stand_in
    with provisioner.lease(timeout_seconds=60) as lease:
        template = lease.ensure_template(live, source=path)
        clone = lease.create_clone(template, uuid.uuid4(), 0)
        try:
            arm = runner(provisioner, clone)
            try:
                sample = arm.execute("SELECT * FROM retail_lines WHERE line_id = $1", [1])
            finally:
                arm.close()
        finally:
            lease.drop_clone(clone)

    assert rows_of(sample) == 1
    assert sample.fingerprint is not None
    only = bytes.fromhex(LINE_1_ROW_HASH)
    assert sample.fingerprint.ordered == hashlib.sha256(only).hexdigest()


# --- the real file -----------------------------------------------------------------------------


@pytest.fixture
def real_template(provisioner: SandboxProvisioner) -> Iterator[Template]:
    pinned = WORKLOADS["online_retail_ii"].fixed
    assert pinned is not None
    path = default_csv_path(pinned)
    if not path.is_file():
        pytest.skip(
            f"real data: the pinned CSV is not at {path} (set QC_DATASETS_DIR); "
            f"expected SHA-256 {pinned.csv_sha256}."
        )
    live = WorkloadRef.parse("online_retail_ii@v1:data=b3471c34b273")
    with provisioner.lease(timeout_seconds=900) as lease:
        template = lease.ensure_template(live, source=path)
    yield template
    with provisioner.lease(timeout_seconds=60) as lease:
        lease.drop_template(live)
        lease.cleanup_orphans()


def test_real_data_template_reproduces_the_pinned_numbers_in_a_clone(
    provisioner: SandboxProvisioner, real_template: Template
) -> None:
    with provisioner.lease(timeout_seconds=300) as lease:
        clone = lease.create_clone(real_template, uuid.uuid4(), 0)
        try:
            with psycopg.connect(
                **provisioner.bench_conninfo(clone, statement_timeout_ms=120_000)
            ) as conn:
                row = conn.execute(
                    "SELECT count(*), sum(quantity), sum(quantity * unit_price)::text, "
                    "count(*) FILTER (WHERE customer_id IS NULL), "
                    "count(*) FILTER (WHERE description IS NULL) FROM retail_lines"
                ).fetchone()
        finally:
            lease.drop_clone(clone)

    assert row == (1_067_371, 10_608_492, "19287250.568", 243_007, 4_382)
    assert len(real_template.data_digest) == 64


def test_real_data_example_queries_return_what_the_profile_says(
    provisioner: SandboxProvisioner, real_template: Template
) -> None:
    q1, q2, q3 = WORKLOADS["online_retail_ii"].example_queries
    with provisioner.lease(timeout_seconds=300) as lease:
        clone = lease.create_clone(real_template, uuid.uuid4(), 0)
        try:
            arm = ArmRunner(
                provisioner.bench_conninfo(clone, statement_timeout_ms=120_000), row_cap=ROW_CAP
            )
            try:
                got: dict[str, int] = {}
                for query in (q1, q2, q3):
                    for param_set in query.param_sets:
                        got[f"{query.name}/{param_set.name}"] = rows_of(
                            arm.execute(query.sql, param_set.values)
                        )
                line_1 = arm.execute("SELECT * FROM retail_lines WHERE line_id = $1", [1])
            finally:
                arm.close()
        finally:
            lease.drop_clone(clone)

    assert got["recent_lines_for_customer/heaviest_customer"] == 50  # LIMIT 50, 13,097 lines
    assert got["recent_lines_for_customer/median_customer"] == 50
    assert got["recent_lines_for_customer/single_line_customer"] == 1
    assert got["recent_lines_for_customer/nonexistent_customer"] == 0
    assert got["lines_of_invoice/largest_invoice"] == 1350
    assert got["lines_of_invoice/cancellation_invoice"] >= 1
    assert got["lines_of_invoice/typical_invoice"] >= 1
    assert got["lines_of_invoice/missing_invoice"] == 0
    assert got["customer_totals_in_window/full_range"] == 5_942  # every customer id
    assert 0 < got["customer_totals_in_window/one_day"] < got["customer_totals_in_window/one_month"]
    assert got["customer_totals_in_window/one_month"] < 5_942
    assert line_1.fingerprint is not None
    assert line_1.fingerprint.ordered == hashlib.sha256(bytes.fromhex(LINE_1_ROW_HASH)).hexdigest()


def test_the_row_hash_of_line_one_is_the_profile_golden() -> None:
    """Sanity of the constant used above: the unit goldens' first line, hashed here directly."""
    kinds = kinds_for_oids(
        types[t].oid
        for t in (
            "int8",
            "int2",
            "int4",
            "text",
            "text",
            "text",
            "int4",
            "timestamp",
            "numeric",
            "int4",
            "text",
        )
    )
    row: tuple[Any, ...] = (
        1, 1, 2, "489434", "85048", "15CM CHRISTMAS GLASS BALL 20 LIGHTS", 12,
        dt.datetime(2009, 12, 1, 7, 45), Decimal("6.950"), 13085, "United Kingdom",
    )  # fmt: skip

    assert row_hash(kinds, row).hex() == LINE_1_ROW_HASH
