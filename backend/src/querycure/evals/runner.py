"""Run eval cases end to end: a throwaway database per case, fixed IDs, the real graph.

Replay mode (CI) serves recorded responses and never touches the network. Record mode calls
the configured free OpenRouter model (ADR-0016), saves what it returned, and stops cleanly
when the request cap or the free quota runs out.
"""

import datetime as dt
import hashlib
import json
import platform
import secrets
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import psycopg
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from querycure.agents.prompts import PROMPT_VERSIONS
from querycure.agents.run import RunServices, execute_run
from querycure.agents.runtime import LlmClients
from querycure.agents.services import sandbox_inspector
from querycure.benchmark.measurement_fixtures import (
    CapturingContext,
    CapturingMeasure,
    FixtureContext,
    FixtureMeasure,
    MeasurementFixture,
    RecordedContext,
)
from querycure.core.config import Settings, is_free_model
from querycure.core.errors import BudgetExhaustedError, ConfigurationError
from querycure.db.engine import make_engine
from querycure.demo.export import export_bundle
from querycure.demo.gallery import BundleSource, DemoBundle
from querycure.domain.budgets import default_budget
from querycure.evals.cases import EVALS_DIR, EvalCase
from querycure.evals.recording import (
    LiveDivergenceError,
    Recording,
    RecordingClient,
    RecordingMissingError,
    ReplayClient,
    model_slug,
)
from querycure.evals.scoring import SCORING_VERSION, Score, observe, score
from querycure.jobs.handlers import build_sandbox
from querycure.llm.openrouter import OpenRouterClient
from querycure.llm.rate_limit import LlmGate, MinuteRateLimiter
from querycure.llm.types import ChatClient
from querycure.plans.parser import parse_plan
from querycure.replay import artifact_store as store
from querycure.sql.ddl import parse_ddl

Mode = Literal["replay", "record"]
# Mode C measurement source in replay mode: "fixture" feeds the measurements captured when the
# case was recorded (deterministic, benchmark-free); "live" re-benchmarks in the sandbox and
# can only end DIVERGED once measurements differ (ADR-0022 §10).
Measurements = Literal["fixture", "live"]
BACKEND = Path(__file__).resolve().parents[3]
NAMESPACE = uuid.UUID("7c1f8f8e-2c4b-4f0e-9a51-6f1d2a3b4c5d")
# Evals spend scarce free requests: fewer tool turns per analyst than a normal run.
EVAL_TOOL_CALLS_PER_AGENT = 2


DIVERGED = "diverged"


@dataclass
class CaseResult:
    case: EvalCase
    score: Score | None
    error: str | None
    model: str = ""
    # What this result was produced from: model, recording, measurement source and fixture
    # digest, prompt and scoring versions (recorded in results JSON).
    provenance: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.error is None and self.score is not None and self.score.passed

    @property
    def diverged(self) -> bool:
        return (self.error or "").startswith(DIVERGED)

    @property
    def expected_failure(self) -> str | None:
        """The recorded reason when this model is known to fail this case (baseline)."""
        return None if self.passed else self.case.known_failures.get(self.model)

    @property
    def acceptable(self) -> bool:
        return self.passed or self.expected_failure is not None


class RequestCap:
    """Hard cap on provider requests for one record invocation (free quota is scarce).

    With a ledger, every request is also counted per UTC day across invocations: eval runs
    use throwaway databases, so the worker's database-backed daily count never sees them.
    """

    def __init__(self, remaining: int, ledger: "QuotaLedger | None" = None) -> None:
        self.remaining = remaining
        self._ledger = ledger

    async def check(self) -> None:
        if self.remaining <= 0:
            raise BudgetExhaustedError(
                "The eval request cap is used up.",
                details=[{"budget": "eval_request_cap", "limit": 0}],
            )
        self.remaining -= 1
        if self._ledger is not None:
            self._ledger.add(1)


class QuotaLedger:
    """Free requests made by eval recording today (UTC), kept in a small local file."""

    def __init__(self, directory: Path, today: str) -> None:
        self._path = directory / f"{today}.json"

    def used(self) -> int:
        try:
            return int(json.loads(self._path.read_text())["requests"])
        except (FileNotFoundError, KeyError, ValueError):
            return 0

    def add(self, n: int) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps({"requests": self.used() + n}) + "\n")


class _CappedGate(LlmGate):
    def __init__(self, limiter: MinuteRateLimiter, cap: RequestCap) -> None:
        super().__init__(limiter)
        self._cap = cap

    async def before_call(self) -> None:
        await self._cap.check()
        await super().before_call()


def _ids(case: EvalCase) -> tuple[uuid.UUID, uuid.UUID]:
    return uuid.uuid5(NAMESPACE, f"{case.id}:user"), uuid.uuid5(NAMESPACE, f"{case.id}:run")


def recording_path(case: EvalCase, model: str, root: Path | None = None) -> Path:
    return (root or EVALS_DIR / "recordings") / case.id / f"{model_slug(model)}.json"


def measurement_fixture_path(case: EvalCase, model: str, root: Path | None = None) -> Path:
    return (root or EVALS_DIR / "fixtures" / "measurements") / case.id / f"{model_slug(model)}.json"


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _db_url(admin_url: str, name: str) -> str:
    base, _, _ = admin_url.rpartition("/")
    return f"{base}/{name}"


def _migrate(url: str) -> None:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url.replace("postgresql://", "postgresql+psycopg://", 1))
    command.upgrade(cfg, "head")


async def _seed(url: str, case: EvalCase, settings: Settings) -> uuid.UUID:
    user_id, run_id = _ids(case)
    budget = default_budget(settings.profile).model_copy(
        update={
            k: v
            for k, v in {
                "tool_calls_per_agent": case.budget.tool_calls_per_agent
                or EVAL_TOOL_CALLS_PER_AGENT,
                "llm_calls": case.budget.llm_calls,
            }.items()
            if v is not None
        }
    )
    engine = make_engine(url, set_role="qc_app")
    try:
        async with engine.begin() as conn:
            inv = (
                await conn.execute(
                    text(
                        "INSERT INTO investigations (id, user_id, title, objective, modes, "
                        "workload_id, pre_authorize_sandbox) VALUES (:inv, :user, :title, "
                        ":objective, :modes, :workload, :pre) RETURNING id"
                    ),
                    {
                        "inv": uuid.uuid5(NAMESPACE, f"{case.id}:investigation"),
                        "user": user_id,
                        "title": case.id,
                        "objective": case.objective,
                        # Mode C cases are pre-authorized: the approval row is still written
                        # (scored by must_request_approval) but no human is in the loop.
                        "modes": ["sandbox_benchmark"] if case.workload else ["offline"],
                        "workload": case.workload,
                        "pre": case.workload is not None,
                    },
                )
            ).scalar_one()
            await conn.execute(
                text(
                    "INSERT INTO investigation_runs (id, investigation_id, run_number, kind, "
                    "status, budget, usage) VALUES (:run, :inv, 1, 'initial', 'queued', "
                    "CAST(:budget AS JSONB), '{}')"
                ),
                {"run": run_id, "inv": inv, "budget": budget.model_dump_json()},
            )
            query = await store.store_raw_sql(conn, case.query)
            await store.link(conn, run_id=run_id, artifact_id=query.id, role="input.query")
            if case.plan is not None:
                raw = (EVALS_DIR / "fixtures" / "plans" / case.plan).read_text()
                kind = "plan_analyze" if parse_plan(raw).analyzed else "plan"
                plan = await store.store_json(conn, kind=kind, value=json.loads(raw))
                await store.link(conn, run_id=run_id, artifact_id=plan.id, role="input.plan")
            if case.schema_ddl is not None:
                declared = parse_ddl(case.schema_ddl)
                schema = await store.store_json(
                    conn, kind="schema_snapshot", value=declared.model_dump(mode="json")
                )
                await store.link(conn, run_id=run_id, artifact_id=schema.id, role="input.schema")
    finally:
        await engine.dispose()
    return run_id


async def run_case(
    case: EvalCase,
    *,
    mode: Mode,
    model: str,
    settings: Settings,
    admin_url: str,
    cap: RequestCap | None,
    recordings_dir: Path | None = None,
    live_client: ChatClient | None = None,  # tests: a fake standing in for OpenRouter
    measurements: Measurements = "fixture",
    fixtures_dir: Path | None = None,
    export_dir: Path | None = None,  # demo bundles: deterministic replays only
    capture_context: bool = False,  # fixture replay: read and store the sandbox context once
) -> CaseResult:
    name = f"qc_eval_{case.id[:30]}_{secrets.token_hex(4)}"
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    url = _db_url(admin_url, name)
    try:
        _migrate(url)
        run_id = await _seed(url, case, settings)
        recording = Recording(case_id=case.id, model=model)
        client: ChatClient
        gate: LlmGate | None = None
        measure: CapturingMeasure | FixtureMeasure | None = None
        context: CapturingContext | FixtureContext | None = None
        fixture: MeasurementFixture | None = None
        use_fixture = mode == "replay" and case.workload is not None and measurements == "fixture"
        provenance: dict[str, Any] = {
            "model": model,
            "mode": mode,
            "measurements": (
                None if case.workload is None else "live" if mode == "record" else measurements
            ),
            "prompt_versions": PROMPT_VERSIONS,
            "scoring_version": SCORING_VERSION,
        }
        if mode == "replay":
            path = recording_path(case, model, recordings_dir)
            if not path.exists():
                return CaseResult(
                    case, None, f"no recording for {case.id} with {model}", model=model,
                    provenance=provenance,
                )  # fmt: skip
            loaded = Recording.load(path)
            provenance["recording_sha256"] = _file_sha256(path)
            provenance["recorded_at"] = loaded.recorded_at
            if use_fixture:
                fixture_file = measurement_fixture_path(case, model, fixtures_dir)
                if not fixture_file.exists():
                    return CaseResult(
                        case, None,
                        f"no measurement fixture for {case.id} with {model}: re-record the case "
                        "(record mode captures one), or pass --measurements live",
                        model=model, provenance=provenance,
                    )  # fmt: skip
                fixture = MeasurementFixture.model_validate_json(fixture_file.read_text())
                if fixture.case_id != case.id or fixture.model != model:
                    return CaseResult(
                        case, None, "measurement fixture belongs to another case or model",
                        model=model, provenance=provenance,
                    )  # fmt: skip
                provenance["measurement_fixture_sha256"] = fixture.digest()
                provenance["measurement_recorded_on"] = fixture.recorded_on
                measure = FixtureMeasure(fixture)
                if fixture.context is not None and not capture_context:
                    context = FixtureContext(fixture.context)
                elif not capture_context:
                    return CaseResult(
                        case, None,
                        "measurement fixture has no recorded sandbox context: run once with "
                        "--capture-context (needs the sandbox) or re-record the case",
                        model=model, provenance=provenance,
                    )  # fmt: skip
            client = ReplayClient(loaded, exact_only=use_fixture)
        else:
            if live_client is None:
                if settings.openrouter_api_key is None:
                    raise ConfigurationError("OPENROUTER_API_KEY is not set.")
                live_client = OpenRouterClient(
                    api_key=settings.openrouter_api_key,
                    model=model,
                    base_url=settings.openrouter_base_url,
                    free_only=settings.llm_free_only,
                    timeout_seconds=settings.llm_call_timeout_seconds,
                )
            client = RecordingClient(live_client, recording)
            gate = _CappedGate(
                MinuteRateLimiter(settings.llm_requests_per_minute), cap or RequestCap(10**6)
            )

        engine = make_engine(url, set_role="qc_app")

        def clients(_: Any) -> LlmClients:
            return LlmClients(primary=client)

        if mode == "record" and case.workload is not None:
            measure = CapturingMeasure()
        # A fixture replay with recorded context touches no sandbox at all.
        needs_sandbox = case.workload is not None and not isinstance(context, FixtureContext)
        sandbox = build_sandbox(settings) if needs_sandbox else None
        if needs_sandbox and sandbox is None:
            return CaseResult(
                case, None, "Mode C case: set SANDBOX_ADMIN_URL and SANDBOX_BENCH_PASSWORD",
                model=model,
            )  # fmt: skip
        if sandbox is not None:
            sandbox.bootstrap()
            if mode == "record" or capture_context:
                live_sandbox = sandbox

                def open_live(workload_id: str, run: uuid.UUID) -> Any:
                    return sandbox_inspector(live_sandbox, workload_id=workload_id, run_id=run)

                context = CapturingContext(open_live)
        provenance["context"] = (
            None
            if case.workload is None
            else "recorded"
            if isinstance(context, FixtureContext)
            else "live sandbox"
        )
        services = RunServices(
            engine=engine,
            settings=settings,
            checkpoint_url=url,
            clients=clients,
            llm_gate=gate,
            checkpoint_role="qc_app",
            sandbox=sandbox,
            measure=measure,
            context_inspector=context,
        )
        error = None
        try:
            await execute_run(services, run_id, attempt=1, reclaimed=False)
        except LiveDivergenceError as exc:
            error = (
                f"{DIVERGED}: this replay's live sandbox measurements took another path than "
                f"the recording; the case is scored when recorded ({exc})"
            )
        except RecordingMissingError:
            error = "recording does not match the current prompts: re-record this case"
        except Exception as exc:  # reported per case, never swallowed
            error = f"{type(exc).__name__}: {exc}"[:300]
        try:
            async with engine.connect() as conn:
                seen = await observe(conn, run_id)
                if export_dir is not None and error is None and mode == "replay":
                    await _export_demo(conn, run_id, case, provenance, export_dir)
        finally:
            await engine.dispose()
        truncated = [
            m
            for e in seen.errors
            if any(
                marker in (m := str(e.get("message", "")))
                for marker in ("eval request cap", "free model allowance", "free model requests")
            )
        ]
        if isinstance(context, FixtureContext) and error is None and context.mismatch:
            error = f"measurement fixture mismatch: {context.mismatch}; re-record this case"
        if isinstance(measure, FixtureMeasure) and error is None:
            if measure.mismatch is not None:
                # Even if the graph recorded the experiment as failed and finished: not a pass.
                error = f"measurement fixture mismatch: {measure.mismatch}; re-record this case"
            elif measure.unused_rounds():
                error = (
                    f"measurement fixture mismatch: {measure.unused_rounds()} recorded round(s) "
                    "were never measured; re-record this case"
                )
        if error is None and truncated:
            # Cut short by our cap or the free quota: not the model's behaviour, never recorded.
            error = f"stopped early ({truncated[0][:80]}): not recorded, rerun later"
        if mode == "record" and error is None:
            recording.save(recording_path(case, model, recordings_dir))
            if isinstance(measure, CapturingMeasure):
                recorded = context.recorded() if isinstance(context, CapturingContext) else None
                _save_fixture(case, model, measure, recorded, fixtures_dir)
        # Only from a replay that matched every recorded prompt exactly: the context read now
        # is provably the one the recording saw.
        seen_context = context.recorded() if isinstance(context, CapturingContext) else None
        if capture_context and error is None and fixture is not None and seen_context:
            path = measurement_fixture_path(case, model, fixtures_dir)
            _write_fixture(path, fixture.model_copy(update={"context": seen_context}))
        return CaseResult(case, score(case, seen), error, model=model, provenance=provenance)
    finally:
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def _write_fixture(path: Path, fixture: MeasurementFixture) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(fixture.model_dump_json(indent=1) + "\n")


def _save_fixture(
    case: EvalCase,
    model: str,
    measure: CapturingMeasure,
    context: RecordedContext | None,
    root: Path | None,
) -> None:
    """The measurements this recording's prompts embed, kept so replay is deterministic.
    A recording that ran no complete experiment gets no fixture (an old one is removed, since
    it would describe another recording)."""
    path = measurement_fixture_path(case, model, root)
    fixture = measure.fixture(
        case_id=case.id,
        model=model,
        recorded_on=dt.datetime.now(dt.UTC).date().isoformat(),
        source_note=(
            f"Measured live in the local sandbox while recording ({platform.system()} "
            f"{platform.machine()}); replayed as prerecorded evidence, not a new measurement"
        ),
    )
    if fixture is None:
        path.unlink(missing_ok=True)
        return
    _write_fixture(path, fixture.model_copy(update={"context": context}))


async def _export_demo(
    conn: Any, run_id: uuid.UUID, case: EvalCase, provenance: dict[str, Any], out: Path
) -> None:
    """A sealed, labelled demo bundle from this deterministic replay (demo.gallery)."""
    if case.workload is not None and provenance.get("measurements") != "fixture":
        raise ConfigurationError("demo bundles come only from fixture replays (deterministic)")
    measured = provenance.get("measurement_recorded_on")
    label = (
        f"Prerecorded demonstration. Agent answers recorded from {provenance['model']} on "
        f"{provenance.get('recorded_at')}"
        + (
            f"; benchmark measurements recorded in a local Docker sandbox on {measured}"
            if measured
            else "; no benchmark (offline analysis)"
        )
        + ". Shown from stored records: not a live run, not your database."
    )
    bundle = await export_bundle(
        conn,
        run_id,
        slug=case.id.replace("_", "-"),
        title=case.id.replace("_", " ").capitalize(),
        summary=" ".join((case.description or "").split()),
        label=label,
        source=BundleSource(
            eval_case=case.id,
            model=provenance["model"],
            recorded_at=provenance.get("recorded_at"),
            measurements_recorded_on=measured,
            recording_sha256=provenance.get("recording_sha256"),
            measurement_fixture_sha256=provenance.get("measurement_fixture_sha256"),
            prompt_versions=provenance["prompt_versions"],
            scoring_version=provenance["scoring_version"],
        ),
    )
    if bundle is not None:
        _write_bundle(out, bundle)


def _write_bundle(out: Path, bundle: DemoBundle) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{bundle.slug}.json").write_text(bundle.model_dump_json(indent=1) + "\n")


def check_model(model: str, settings: Settings) -> None:
    if settings.llm_free_only and not is_free_model(model):
        raise ConfigurationError(f"{model} is not a free model; LLM_FREE_ONLY is on (ADR-0016).")
