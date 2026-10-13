"""Job-kind → handler registry used by the worker entrypoint."""

from sqlalchemy.ext.asyncio import AsyncEngine

from querycure.agents.run import RunServices, env_clients, execute_run, fail_run
from querycure.benchmark.engine import EngineOptions
from querycure.core.config import Settings
from querycure.jobs.queue import Job, JobKind, ReapedJob
from querycure.llm.rate_limit import DailyQuota, LlmGate, MinuteRateLimiter
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
    if settings.database_url is None:
        raise ValueError("DATABASE_URL is required")
    sandbox = build_sandbox(settings)
    if sandbox is not None:
        sandbox.bootstrap()
    return RunServices(
        sandbox=sandbox,
        engine_options=engine_options(settings),
        engine=engine,
        settings=settings,
        checkpoint_url=settings.database_url.get_secret_value(),
        clients=env_clients(settings),
        # Free-tier limits apply to OpenRouter only; the offline stub makes no requests.
        llm_gate=LlmGate(
            MinuteRateLimiter(settings.llm_requests_per_minute),
            DailyQuota(engine, settings.llm_daily_request_limit),
        )
        if settings.llm_provider == "openrouter"
        else None,
    )


def build_handlers(services: RunServices) -> dict[JobKind, Handler]:
    handle = run_handler(services)
    return {"run_start": handle, "run_resume": handle}
