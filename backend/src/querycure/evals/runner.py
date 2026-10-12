"""Run eval cases end to end: a throwaway database per case, fixed IDs, the real graph.

Replay mode (CI) serves recorded responses and never touches the network. Record mode calls
the configured free OpenRouter model (ADR-0016), saves what it returned, and stops cleanly
when the request cap or the free quota runs out.
"""

import json
import secrets
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import psycopg
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from querycure.agents.run import RunServices, execute_run
from querycure.agents.runtime import LlmClients
from querycure.core.config import Settings, is_free_model
from querycure.core.errors import BudgetExhaustedError, ConfigurationError
from querycure.db.engine import make_engine
from querycure.domain.budgets import default_budget
from querycure.evals.cases import EVALS_DIR, EvalCase
from querycure.evals.recording import (
    Recording,
    RecordingClient,
    RecordingMissingError,
    ReplayClient,
    model_slug,
)
from querycure.evals.scoring import Score, observe, score
from querycure.llm.openrouter import OpenRouterClient
from querycure.llm.rate_limit import LlmGate, MinuteRateLimiter
from querycure.llm.types import ChatClient
from querycure.plans.parser import parse_plan
from querycure.replay import artifact_store as store
from querycure.sql.ddl import parse_ddl

Mode = Literal["replay", "record"]
BACKEND = Path(__file__).resolve().parents[3]
NAMESPACE = uuid.UUID("7c1f8f8e-2c4b-4f0e-9a51-6f1d2a3b4c5d")
# Evals spend scarce free requests: fewer tool turns per analyst than a normal run.
EVAL_TOOL_CALLS_PER_AGENT = 2


@dataclass
class CaseResult:
    case: EvalCase
    score: Score | None
    error: str | None
    tools: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.error is None and self.score is not None and self.score.passed


class RequestCap:
    """Hard cap on provider requests for one record invocation (free quota is scarce)."""

    def __init__(self, remaining: int) -> None:
        self.remaining = remaining

    async def check(self) -> None:
        if self.remaining <= 0:
            raise BudgetExhaustedError(
                "The eval request cap is used up.",
                details=[{"budget": "eval_request_cap", "limit": 0}],
            )
        self.remaining -= 1


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
                        "INSERT INTO investigations (id, user_id, title, objective, modes) "
                        "VALUES (:inv, :user, :title, :objective, ARRAY['offline']) RETURNING id"
                    ),
                    {
                        "inv": uuid.uuid5(NAMESPACE, f"{case.id}:investigation"),
                        "user": user_id,
                        "title": case.id,
                        "objective": case.objective,
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
    reference_tools: dict[str, list[str]],
    recordings_dir: Path | None = None,
    live_client: ChatClient | None = None,  # tests: a fake standing in for OpenRouter
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
        if mode == "replay":
            path = recording_path(case, model, recordings_dir)
            if not path.exists():
                return CaseResult(case, None, f"no recording for {case.id} with {model}")
            client = ReplayClient(Recording.load(path))
        else:
            if live_client is None:
                if settings.openrouter_api_key is None:
                    raise ConfigurationError("OPENROUTER_API_KEY is not set.")
                live_client = OpenRouterClient(
                    api_key=settings.openrouter_api_key,
                    model=model,
                    base_url=settings.openrouter_base_url,
                    free_only=settings.llm_free_only,
                )
            client = RecordingClient(live_client, recording)
            gate = _CappedGate(
                MinuteRateLimiter(settings.llm_requests_per_minute), cap or RequestCap(10**6)
            )

        engine = make_engine(url, set_role="qc_app")

        def clients(_: Any) -> LlmClients:
            return LlmClients(primary=client)

        services = RunServices(
            engine=engine,
            settings=settings,
            checkpoint_url=url,
            clients=clients,
            llm_gate=gate,
            checkpoint_role="qc_app",
        )
        error = None
        try:
            await execute_run(services, run_id, attempt=1, reclaimed=False)
        except RecordingMissingError:
            error = "recording does not match the current prompts: re-record this case"
        except Exception as exc:  # reported per case, never swallowed
            error = f"{type(exc).__name__}: {exc}"[:300]
        try:
            async with engine.connect() as conn:
                seen = await observe(conn, run_id)
        finally:
            await engine.dispose()
        if mode == "record" and error is None:
            recording.save(recording_path(case, model, recordings_dir))
        result = score(case, seen, other_tools=reference_tools)
        return CaseResult(case, result, error, tools=[t for t, _ in seen.tools])
    finally:
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def check_model(model: str, settings: Settings) -> None:
    if settings.llm_free_only and not is_free_model(model):
        raise ConfigurationError(f"{model} is not a free model; LLM_FREE_ONLY is on (ADR-0016).")
