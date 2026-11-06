"""Audit-completeness invariant in the real graph, on the metadata database only.

An experiment winner must never end as a `verified_recommendation` unless the required
deterministic audit completed. These tests run the whole graph (`execute_run`) with no sandbox.

REAL: graph orchestration and routing, `BudgetGuard` (wall clock and model-call exhaustion),
metadata persistence and every database constraint, the `run_experiment` bookkeeping and
candidate status transitions, the real `benchmark_auditor` and `audit_experiment`, the
`write_report` gate, `finalize_run`, and report sealing.

REPLACED, and only these: benchmark execution (`FixtureMeasure` replays the committed
recording), the sandbox context reads (`FixtureContext` serves its recorded EXPLAIN and schema)
and the LLM (scripted `RoleClient`; no network).

The recording: `evals/fixtures/measurements/orders_sandbox_composite_index/…json`, round 0. Its
engine verdicts are `verified` for the composite index (`oc_863aa629a369`) and `inconclusive`
(`effect_not_significant`) for `ANALYZE orders` (`oc_07150a9c30d7`).

Two measure sources, so the audit outcome is never faked:

- `FixtureMeasure` as is: the samples are labelled `prerecorded`, so the REAL auditor fails its
  `provenance` check and downgrades the verified index candidate. That is the stale-winner case.
- `SyntheticMeasuredReplay` (test-only, below): the same recorded samples handed to the node
  labelled `measured`, for the audit-passes cases. This is a SYNTHETIC label on recorded data,
  so these runs are not evidence of any measurement; the committed fixture is never modified
  (a test checks its bytes and that it still says `prerecorded`), and the replay's own progress
  events keep saying `prerecorded: true` in the database. No check is waived or patched.

Dependency on the eval harness: the fixture's experiment id, seed and candidate keys derive from
the eval run id `uuid5(NAMESPACE, "<case>:run")`, and `FixtureMeasure` requires the run's
experiment config to equal the recorded one. Reproducing that identity and the same inputs and
budget needs the harness's own `_seed` (private); copying it would drift silently. Each test
asserts the seeded run id first, so a change fails with a clear message. Because the run id is
fixed, every test gets its own throwaway database.

Needs the metadata database (docker compose `metadata-db`) only. If the recording no longer
matches the code, the run fails fast with MEASUREMENT_FIXTURE_MISMATCH; the eval suite's Mode C
replay of the same fixture is the upstream guard.
"""

import hashlib
import os
import uuid
from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from pathlib import Path
from typing import Any, Literal

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from langgraph.runtime import Runtime
from sqlalchemy.ext.asyncio import AsyncEngine

from querycure.agents.nodes.run_experiment import run_experiment as real_run_experiment
from querycure.agents.nodes.write_report import write_report as real_write_report
from querycure.agents.run import RunServices, execute_run
from querycure.agents.runtime import LlmClients, RunContext
from querycure.agents.state import InvestigationState
from querycure.audit.completeness import (
    UnauditedCandidate,
    audit_incomplete_error,
    unaudited_reasons,
)
from querycure.benchmark.engine import ApprovedExperiment, EngineHooks, EngineOptions, ReplicatedRun
from querycure.benchmark.measurement_fixtures import (
    FixtureContext,
    FixtureMeasure,
    MeasurementFixture,
)
from querycure.benchmark.replication import Replicate
from querycure.db.engine import make_engine
from querycure.domain.benchmark import ExperimentConfig, ExperimentResult
from querycure.evals.runner import _seed, measurement_fixture_path
from querycure.sandbox.provisioner import SandboxProvisioner
from tests.fake_llm import RoleClient, Step
from tests.integration.conftest import ADMIN_URL, BACKEND
from tests.integration.test_benchmark_auditor import verifications
from tests.integration.test_context_nodes import SETTINGS
from tests.integration.test_eval_runner import case
from tests.integration.test_investigation_graph import run_row
from tests.integration.test_optimization_graph import (
    NOTHING_MORE,
    candidate_rows,
    candidates,
    scripts,
)

pytestmark = pytest.mark.integration

CASE_ID = "orders_sandbox_composite_index"
RECORDED_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"
RUN_ID = uuid.UUID("4d007ded-05c7-5098-af85-8b5384576ca0")  # uuid5(NAMESPACE, f"{CASE_ID}:run")
INDEX_KEY = "oc_863aa629a369"  # keyed_id("oc", RUN_ID, round 0, position 0): the composite index
ANALYZE_KEY = "oc_07150a9c30d7"  # position 1: ANALYZE orders
# Exactly the recorded arms, including write_overhead: the replay compares configs byte for byte.
INDEX_DRAFT = {
    "kind": "create_index",
    "ddl": [
        "CREATE INDEX IF NOT EXISTS idx_orders_customer_id_created_at "
        "ON orders (customer_id, created_at DESC)"
    ],
    "write_overhead": "medium",
}
ANALYZE_DRAFT = {
    "kind": "analyze_statistics",
    "ddl": ["ANALYZE orders"],
    "write_overhead": "low",
}
NEUTRAL = '{"summary": "No concerns beyond the checks.", "concerns": []}'


# --- the measure sources ---------------------------------------------------------------------


class SyntheticMeasuredReplay:
    """TEST ONLY. Replays the recorded samples through the real `FixtureMeasure` (same config,
    SQL-digest and verdict checks) but hands the node results labelled `measured`.

    Why it exists: a replay is `prerecorded`, which the real auditor refuses to count, so no
    audit-passes run is possible with the recording as is. The label is SYNTHETIC; nothing is
    waived. `MeasurementFixture` itself forbids non-prerecorded results, which is why this is a
    wrapper and the committed fixture stays untouched.
    """

    provenance: Literal["measured"] = "measured"  # what the node tags the persisted blocks with

    def __init__(self, fixture: MeasurementFixture) -> None:
        self._replay = FixtureMeasure(fixture)

    @staticmethod
    def _relabel(result: ExperimentResult) -> ExperimentResult:
        return result.model_copy(update={"provenance": "measured"})

    def __call__(
        self,
        config: ExperimentConfig,
        approved: ApprovedExperiment,
        *,
        provisioner: SandboxProvisioner | None = None,
        hooks_for: Callable[[ExperimentConfig, int], EngineHooks],
        options: EngineOptions | None = None,
        on_result: Callable[[ExperimentConfig, int, ExperimentResult], None] | None = None,
    ) -> ReplicatedRun:
        def relabelled(cfg: ExperimentConfig, index: int, result: ExperimentResult) -> None:
            if on_result is not None:
                on_result(cfg, index, self._relabel(result))

        ran = self._replay(
            config,
            approved,
            provisioner=provisioner,
            hooks_for=hooks_for,
            options=options,
            on_result=relabelled,
        )
        return ReplicatedRun(
            replicates=[
                Replicate(config=r.config, result=self._relabel(r.result)) for r in ran.replicates
            ],
            replication=ran.replication,
        )


# --- fixtures --------------------------------------------------------------------------------


@pytest.fixture
def fresh_db() -> Iterator[str]:
    """A throwaway migrated database per test: the run id is fixed by the recording."""
    try:
        admin = psycopg.connect(ADMIN_URL, autocommit=True, connect_timeout=3)
    except psycopg.OperationalError as exc:
        reason = f"metadata DB not reachable ({exc.__class__.__name__}); run docker compose up"
        if os.environ.get("QC_REQUIRE_DB") == "1":
            pytest.fail(reason)
        pytest.skip(reason)
    name = f"qc_test_{uuid.uuid4().hex[:12]}"
    base, _, _ = ADMIN_URL.rpartition("/")
    url = f"{base}/{name}"
    with admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    try:
        cfg = Config(str(BACKEND / "alembic.ini"))
        cfg.set_main_option("script_location", str(BACKEND / "migrations"))
        cfg.set_main_option(
            "sqlalchemy.url", url.replace("postgresql://", "postgresql+psycopg://", 1)
        )
        command.upgrade(cfg, "head")
        yield url
    finally:
        with psycopg.connect(ADMIN_URL, autocommit=True) as cleanup:
            cleanup.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture
async def engine(fresh_db: str) -> AsyncIterator[AsyncEngine]:
    app = make_engine(fresh_db, set_role="qc_app")
    yield app
    await app.dispose()


@pytest.fixture
def db(fresh_db: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(fresh_db, autocommit=True) as conn:
        yield conn


FIXTURE_FILE: Path = measurement_fixture_path(case(CASE_ID), RECORDED_MODEL)


@pytest.fixture
def recording() -> Iterator[MeasurementFixture]:
    """The committed recording; its bytes must be the same after the test."""
    before = hashlib.sha256(FIXTURE_FILE.read_bytes()).hexdigest()
    fixture = MeasurementFixture.model_validate_json(FIXTURE_FILE.read_text())
    yield fixture
    assert hashlib.sha256(FIXTURE_FILE.read_bytes()).hexdigest() == before
    assert fixture.provenance == "prerecorded"
    assert {r.result.provenance for r in fixture.rounds[0].replicates} == {"prerecorded"}


@pytest.fixture
def winner_in_state(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """What the graph state holds when write_report starts (the stale-state precondition)."""
    seen: dict[str, Any] = {}

    async def write_report(
        state: InvestigationState, runtime: Runtime[RunContext]
    ) -> dict[str, Any]:
        seen["winner"] = state.get("winner")
        seen["stop_reason"] = state.get("stop_reason")
        return await real_write_report(state, runtime)

    monkeypatch.setattr("querycure.agents.graph.write_report", write_report)
    return seen


def after_experiment(
    monkeypatch: pytest.MonkeyPatch,
    db: psycopg.Connection,
    action: Callable[[psycopg.Connection, uuid.UUID], None],
) -> None:
    """Run the REAL run_experiment node, then change the run's budget state under the REAL guard."""

    async def run_experiment(
        state: InvestigationState, runtime: Runtime[RunContext]
    ) -> dict[str, Any]:
        update = await real_run_experiment(state, runtime)
        action(db, runtime.context.run_id)
        return update

    monkeypatch.setattr("querycure.agents.graph.run_experiment", run_experiment)


def expire_wall_clock(db: psycopg.Connection, run_id: uuid.UUID) -> None:
    """The 600 s wall clock is spent: the auditor node's guard check refuses to start."""
    db.execute(
        "UPDATE investigation_runs SET started_at = now() - interval '2 hours' WHERE id = %s",
        (run_id,),
    )


def exhaust_model_calls(db: psycopg.Connection, run_id: uuid.UUID) -> None:
    """The run's model-call budget is used up: the auditor's deterministic checks still run and
    are recorded, then its narrative call is refused by the real `charge_llm_call`."""
    db.execute(
        "UPDATE investigation_runs SET usage = jsonb_set(usage, '{llm_calls}', "
        "to_jsonb((budget->>'llm_calls')::int)) WHERE id = %s",
        (run_id,),
    )


async def run_graph(
    engine: AsyncEngine,
    url: str,
    recording: MeasurementFixture,
    *,
    synthetic_measured: bool = False,
    auditor: Sequence[Step] = (),
) -> uuid.UUID:
    run_id = await _seed(url, case(CASE_ID), SETTINGS)
    assert run_id == RUN_ID, "the eval harness no longer derives this run id: re-derive the keys"
    assert recording.context is not None
    roles: dict[str, Sequence[Step]] = dict(
        scripts([candidates(INDEX_DRAFT, ANALYZE_DRAFT), NOTHING_MORE])
    )
    if auditor:
        roles["benchmark_auditor"] = auditor
    llm = RoleClient(roles)
    services = RunServices(
        engine=engine,
        settings=SETTINGS,
        checkpoint_url=url,
        clients=lambda _inputs: LlmClients(primary=llm),
        checkpoint_role="qc_app",
        sandbox=None,
        measure=SyntheticMeasuredReplay(recording)
        if synthetic_measured
        else FixtureMeasure(recording),
        context_inspector=FixtureContext(recording.context),
    )
    await execute_run(services, run_id, attempt=1, reclaimed=False)
    return run_id


# --- what the tests read back ----------------------------------------------------------------


def candidate_states(db: psycopg.Connection, run_id: uuid.UUID) -> dict[str, tuple[str, list[str]]]:
    return {
        row[0]: (row[2], [r["code"] for r in (row[3] or [])]) for row in candidate_rows(db, run_id)
    }


def candidate_id(db: psycopg.Connection, run_id: uuid.UUID, key: str) -> uuid.UUID:
    row = db.execute(
        "SELECT id FROM optimization_candidates WHERE run_id = %s AND key = %s", (run_id, key)
    ).fetchone()
    assert row is not None
    return row[0]  # type: ignore[no-any-return]


def events(db: psycopg.Connection, run_id: uuid.UUID, type: str) -> list[dict[str, Any]]:
    return [
        r[0]
        for r in db.execute(
            "SELECT payload FROM investigation_events WHERE run_id = %s AND type = %s ORDER BY seq",
            (run_id, type),
        )
    ]


def audit_errors(db: psycopg.Connection, run_id: uuid.UUID) -> list[dict[str, Any]]:
    return [e for e in events(db, run_id, "error") if e.get("code") == "AUDIT_NOT_COMPLETED"]


def audits_by_key(db: psycopg.Connection, run_id: uuid.UUID) -> dict[str, dict[str, Any]]:
    return {row["candidate_key"]: row for row in verifications_with_key(db, run_id)}


def verifications_with_key(db: psycopg.Connection, run_id: uuid.UUID) -> list[dict[str, Any]]:
    cur = db.execute(
        "SELECT candidate_key, engine_verdict, verdict, checks, auditor_status, "
        "auditor_downgraded, auditor_prompt_version FROM verification_results "
        "WHERE run_id = %s ORDER BY candidate_key",
        (run_id,),
    )
    names = [d.name for d in cur.description or []]
    return [dict(zip(names, r, strict=True)) for r in cur.fetchall()]


def failed_checks(row: dict[str, Any]) -> list[str]:
    return [c["name"] for c in row["checks"] if c["status"] == "fail"]


def engine_reason_codes(recording: MeasurementFixture, key: str) -> list[str]:
    result = recording.rounds[0].replicates[0].result
    return [r.code for v in result.verdicts if v.arm == key for r in v.reasons]


def sealing(db: psycopg.Connection, run_id: uuid.UUID) -> dict[str, Any]:
    """Run state, report row, manifest and lifecycle events: sealing, not report text."""
    run = db.execute(
        "SELECT status, outcome, finalized_at IS NOT NULL FROM investigation_runs WHERE id = %s",
        (run_id,),
    ).fetchone()
    assert run is not None
    reports = db.execute(
        "SELECT final_status, outcome FROM investigation_reports WHERE run_id = %s", (run_id,)
    ).fetchall()
    manifests = db.execute(
        "SELECT count(*) FROM replay_manifests WHERE run_id = %s", (run_id,)
    ).fetchone()
    assert manifests is not None
    (concluded,) = events(db, run_id, "run.concluded")
    return {
        "run": tuple(run),
        "reports": [tuple(r) for r in reports],
        "manifests": manifests[0],
        "report_ready": len(events(db, run_id, "report.ready")),
        "stop_reason": concluded["stop_reason"],
    }


# --- the scenarios ---------------------------------------------------------------------------


async def test_winner_is_not_a_verified_recommendation_when_the_auditor_is_skipped_by_the_budget(
    engine: AsyncEngine,
    fresh_db: str,
    db: psycopg.Connection,
    recording: MeasurementFixture,
    monkeypatch: pytest.MonkeyPatch,
    winner_in_state: dict[str, Any],
) -> None:
    after_experiment(monkeypatch, db, expire_wall_clock)

    run_id = await run_graph(engine, fresh_db, recording)

    # The engine verdict became the candidates' status through the real run_experiment, and the
    # state's winner is the unaudited index when write_report starts.
    assert winner_in_state == {"winner": INDEX_KEY, "stop_reason": "budget_exhausted"}
    assert audits_by_key(db, run_id) == {}  # the auditor node never ran
    index_id = candidate_id(db, run_id, INDEX_KEY)
    unaudited = UnauditedCandidate(id=index_id, key=INDEX_KEY, round=0, status="verified")
    assert candidate_states(db, run_id) == {
        INDEX_KEY: ("inconclusive", ["audit_not_completed"]),
        # Not a verified candidate: the gate leaves the engine's own verdict alone.
        ANALYZE_KEY: ("inconclusive", engine_reason_codes(recording, ANALYZE_KEY)),
    }
    (reasons,) = db.execute(
        "SELECT verdict_reasons FROM optimization_candidates WHERE id = %s", (index_id,)
    ).fetchone() or (None,)
    assert reasons == unaudited_reasons(unaudited, "budget_exhausted")
    # One error event, naming only the unaudited candidate. `verification.completed` is not used:
    # the only one for the index is the engine's own, emitted before any audit.
    assert audit_errors(db, run_id) == [
        audit_incomplete_error([unaudited], "budget_exhausted").model_dump()
    ]
    engine_verdicts = [
        e for e in events(db, run_id, "verification.completed") if e["candidate_key"] == INDEX_KEY
    ]
    assert [(e["verdict"], "audit" in e) for e in engine_verdicts] == [("verified", False)]
    assert sealing(db, run_id) == {
        "run": ("completed", "inconclusive", True),
        "reports": [("completed", "inconclusive")],
        "manifests": 1,
        "report_ready": 1,
        "stop_reason": "budget_exhausted",
    }


async def test_winner_the_audit_downgraded_is_not_verified_when_the_budget_cuts_the_narrative(
    engine: AsyncEngine,
    fresh_db: str,
    db: psycopg.Connection,
    recording: MeasurementFixture,
    monkeypatch: pytest.MonkeyPatch,
    winner_in_state: dict[str, Any],
) -> None:
    after_experiment(monkeypatch, db, exhaust_model_calls)

    run_id = await run_graph(engine, fresh_db, recording)  # prerecorded samples: audit fails

    # The auditor raised before it could return its winner: the state still names the index
    # although the REAL audit has just downgraded it.
    assert winner_in_state == {"winner": INDEX_KEY, "stop_reason": "budget_exhausted"}
    audits = audits_by_key(db, run_id)
    assert set(audits) == {INDEX_KEY, ANALYZE_KEY}
    index = audits[INDEX_KEY]
    assert (index["engine_verdict"], index["verdict"]) == ("verified", "inconclusive")
    assert index["auditor_downgraded"] is True
    assert failed_checks(index) == ["provenance"]  # the only failing check, from the real audit
    analyze = audits[ANALYZE_KEY]
    assert (analyze["engine_verdict"], analyze["verdict"]) == ("inconclusive", "inconclusive")
    assert analyze["auditor_downgraded"] is False
    assert {a["auditor_status"] for a in audits.values()} == {"deterministic_only"}
    assert candidate_states(db, run_id) == {
        INDEX_KEY: ("inconclusive", ["audit_downgrade"]),  # the auditor's own reason
        ANALYZE_KEY: ("inconclusive", engine_reason_codes(recording, ANALYZE_KEY)),
    }
    assert audit_errors(db, run_id) == []  # it WAS audited: nothing to announce
    (index_event,) = [
        e for e in events(db, run_id, "verification.completed")
        if e["candidate_key"] == INDEX_KEY and "audit" in e
    ]  # fmt: skip
    assert index_event["verdict"] == "inconclusive"
    assert index_event["audit"]["downgraded"] is True
    assert index_event["audit"]["failed_checks"] == ["provenance"]
    assert sealing(db, run_id) == {
        "run": ("completed", "inconclusive", True),
        "reports": [("completed", "inconclusive")],
        "manifests": 1,
        "report_ready": 1,
        "stop_reason": "budget_exhausted",
    }


async def test_audited_winner_stays_verified_when_the_budget_only_cuts_the_narrative(
    engine: AsyncEngine,
    fresh_db: str,
    db: psycopg.Connection,
    recording: MeasurementFixture,
    monkeypatch: pytest.MonkeyPatch,
    winner_in_state: dict[str, Any],
) -> None:
    after_experiment(monkeypatch, db, exhaust_model_calls)

    run_id = await run_graph(engine, fresh_db, recording, synthetic_measured=True)

    assert winner_in_state == {"winner": INDEX_KEY, "stop_reason": "budget_exhausted"}
    audits = audits_by_key(db, run_id)
    index = audits[INDEX_KEY]
    assert (index["engine_verdict"], index["verdict"]) == ("verified", "verified")
    assert index["auditor_downgraded"] is False
    assert failed_checks(index) == []  # all eleven real checks, none waived
    assert {a["auditor_status"] for a in audits.values()} == {"deterministic_only"}
    assert candidate_states(db, run_id) == {
        INDEX_KEY: ("verified", []),
        ANALYZE_KEY: ("inconclusive", engine_reason_codes(recording, ANALYZE_KEY)),
    }
    assert audit_errors(db, run_id) == []
    assert sealing(db, run_id) == {
        "run": ("completed", "verified_recommendation", True),
        "reports": [("completed", "verified_recommendation")],
        "manifests": 1,
        "report_ready": 1,
        "stop_reason": "budget_exhausted",
    }
    # The synthetic label is visible in the data, never silently the truth about the samples.
    labels = db.execute(
        "SELECT DISTINCT provenance FROM benchmark_runs WHERE experiment_id IN "
        "(SELECT id FROM experiments WHERE run_id = %s)",
        (run_id,),
    ).fetchall()
    assert [r[0] for r in labels] == ["measured"]
    progress = events(db, run_id, "benchmark.progress")
    assert progress
    assert all(
        e.get("prerecorded") is True for e in progress if e["state"] in ("measuring", "scoring")
    )


async def test_a_fully_audited_run_is_unchanged(
    engine: AsyncEngine,
    fresh_db: str,
    db: psycopg.Connection,
    recording: MeasurementFixture,
    winner_in_state: dict[str, Any],
) -> None:
    run_id = await run_graph(
        engine, fresh_db, recording, synthetic_measured=True, auditor=[NEUTRAL, NEUTRAL]
    )

    assert winner_in_state == {"winner": INDEX_KEY, "stop_reason": None}
    audits = audits_by_key(db, run_id)
    index = audits[INDEX_KEY]
    assert (index["engine_verdict"], index["verdict"]) == ("verified", "verified")
    assert index["auditor_downgraded"] is False
    assert index["auditor_prompt_version"] == "benchmark_auditor@1"
    assert {a["auditor_status"] for a in audits.values()} == {"completed"}
    assert candidate_states(db, run_id) == {
        INDEX_KEY: ("verified", []),
        ANALYZE_KEY: ("inconclusive", engine_reason_codes(recording, ANALYZE_KEY)),
    }
    assert audit_errors(db, run_id) == []
    assert sealing(db, run_id) == {
        "run": ("completed", "verified_recommendation", True),
        "reports": [("completed", "verified_recommendation")],
        "manifests": 1,
        "report_ready": 1,
        "stop_reason": None,
    }


async def test_a_completed_audit_that_downgrades_the_winner_leaves_nothing_unaudited(
    engine: AsyncEngine,
    fresh_db: str,
    db: psycopg.Connection,
    recording: MeasurementFixture,
    winner_in_state: dict[str, Any],
) -> None:
    run_id = await run_graph(engine, fresh_db, recording, auditor=[NEUTRAL, NEUTRAL])

    # The auditor returned normally, so its own result replaced the engine's winner in the state.
    assert winner_in_state == {"winner": None, "stop_reason": None}
    audits = audits_by_key(db, run_id)
    index = audits[INDEX_KEY]
    assert (index["engine_verdict"], index["verdict"]) == ("verified", "inconclusive")
    assert failed_checks(index) == ["provenance"]
    assert {a["auditor_status"] for a in audits.values()} == {"completed"}
    assert candidate_states(db, run_id)[INDEX_KEY] == ("inconclusive", ["audit_downgrade"])
    assert audit_errors(db, run_id) == []
    sealed = sealing(db, run_id)
    assert sealed["run"] == ("completed", "inconclusive", True)
    assert sealed["reports"] == [("completed", "inconclusive")]
    assert run_row(db, run_id)[:2] == ("completed", "inconclusive")
    assert verifications(db, run_id)  # the audit rows are there to be read back
