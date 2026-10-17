"""Job-kind → handler registry used by the worker entrypoint."""

from sqlalchemy.ext.asyncio import AsyncEngine

from querycure.agents.run import RunServices, env_clients, execute_run, fail_run
from querycure.benchmark.engine import EngineOptions
from querycure.core.config import Settings
from querycure.jobs.queue import Job, JobKind, ReapedJob
from querycure.llm.rate_limit import DailyQuota, LlmGate, MinuteRateLimiter
from querycure.replay.experiment_replay import execute_experiment_replay, mark_replay_failed
from querycure.sandbox.provisioner import SandboxProvisioner
from querycure.worker.runner import DeadCallback, Handler, PermanentJobError


def run_handler(services: RunServices) -> Handler:
    async def handle(job: Job) -> None:
        if job.run_id is None:
            raise PermanentJobError("JOB_WITHOUT_RUN")
        await execute_run(services, job.run_id, attempt=job.attempts, reclaimed=job.reclaimed)

    return handle


def dead_job_handler(services: RunServices) -> DeadCallback:
    async def on_dead(job: Job | ReapedJob) -> None:
        if job.run_id is not None:
            await mark_replay_failed(services.engine, job.run_id, "internal_error")
            await fail_run(services.engine, job.run_id, {"code": "JOB_DEAD_LETTERED"})

    return on_dead


def build_sandbox(settings: Settings) -> SandboxProvisioner | None:
    """Mode C needs the feature flag, the admin URL and the bench password."""
    if not settings.feature_sandbox or settings.sandbox_admin_url is None:
        return None
    if settings.sandbox_bench_password is None:
        raise ValueError("SANDBOX_BENCH_PASSWORD is required with SANDBOX_ADMIN_URL")
    return SandboxProvisioner(
        admin_url=settings.sandbox_admin_url, bench_password=settings.sandbox_bench_password
    )


def engine_options(settings: Settings) -> EngineOptions:
    return EngineOptions(
        lease_timeout_seconds=settings.sandbox_lease_timeout_seconds,
        sandbox_image_digest=settings.sandbox_image_digest,
        container_runtime=settings.bench_path,
    )


def build_services(engine: AsyncEngine, settings: Settings) -> RunServices:
    checkpoint_url = settings.direct_database_url()
    if settings.database_url is None or checkpoint_url is None:
        raise ValueError("DATABASE_URL is required")
    sandbox = build_sandbox(settings)
    if sandbox is not None:
        sandbox.bootstrap()
    return RunServices(
        sandbox=sandbox,
        engine_options=engine_options(settings),
        engine=engine,
        settings=settings,
        checkpoint_url=checkpoint_url,  # startup search_path: direct endpoint only
        clients=env_clients(settings),
        llm_gate=llm_gate(engine, settings),
    )


def llm_gate(engine: AsyncEngine, settings: Settings) -> LlmGate | None:
    """Free-tier limits. The daily quota counts OpenRouter free model ids only; Groq enforces
    its own daily limit, whose 429 stops the run (ADR-0027). The offline stub sends nothing."""
    minute = MinuteRateLimiter(settings.llm_requests_per_minute)
    if settings.llm_provider == "openrouter":
        return LlmGate(minute, DailyQuota(engine, settings.llm_daily_request_limit))
    if settings.llm_provider == "groq":
        return LlmGate(minute)
    return None


def replay_handler(services: RunServices) -> Handler:
    async def handle(job: Job) -> None:
        if job.run_id is None:
            raise PermanentJobError("JOB_WITHOUT_RUN")
        await execute_experiment_replay(
            services.engine,
            job.run_id,
            sandbox=services.sandbox,
            options=services.engine_options or EngineOptions(),
            reclaimed=job.reclaimed,
        )

    return handle


def build_handlers(services: RunServices) -> dict[JobKind, Handler]:
    handle = run_handler(services)
    return {
        "run_start": handle,
        "run_resume": handle,
        "experiment_replay": replay_handler(services),
    }
