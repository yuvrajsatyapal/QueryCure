import base64
import binascii
from enum import StrEnum
from typing import Literal, Self, TypedDict

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Profile(StrEnum):
    LOCAL = "local"
    DEMO = "demo"


class WorkerMode(StrEnum):
    SEPARATE = "separate"
    EMBEDDED = "embedded"


def _env(name: str) -> AliasChoices:
    return AliasChoices(name, name.lower())


FREE_ROUTER = "openrouter/free"


def is_free_model(model: str) -> bool:
    """`openrouter/auto` is listed at $0 but routes to paid models, so only the explicit
    free router and `:free` variants qualify."""
    return model == FREE_ROUTER or (model.endswith(":free") and "/" in model)


class EngineSettings(TypedDict):
    pool_size: int
    max_overflow: int
    pool_timeout: float
    statement_timeout_ms: int
    idle_in_transaction_timeout_ms: int


class Settings(BaseSettings):
    """Env vars from DEPLOYMENT.md §6. Secrets are SecretStr and never printed."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    profile: Profile = Field(default=Profile.LOCAL, validation_alias=_env("QC_PROFILE"))
    database_url: SecretStr | None = Field(default=None, validation_alias=_env("DATABASE_URL"))
    database_url_direct: SecretStr | None = Field(
        default=None, validation_alias=_env("DATABASE_URL_DIRECT")
    )
    # Owner role, used only by Alembic. The app itself connects as the restricted qc_app role.
    database_migration_url: SecretStr | None = Field(
        default=None, validation_alias=_env("DATABASE_MIGRATION_URL")
    )
    # The qc_retention role (DELETE only), for `python -m querycure.ops retention`.
    database_retention_url: SecretStr | None = Field(
        default=None, validation_alias=_env("DATABASE_RETENTION_URL")
    )
    # Mode C sandbox server (SECURITY §8). The admin role only creates/drops databases and
    # builds templates; candidate SQL runs as qc_bench with SANDBOX_BENCH_PASSWORD.
    sandbox_admin_url: SecretStr | None = Field(
        default=None, validation_alias=_env("SANDBOX_ADMIN_URL")
    )
    sandbox_bench_password: SecretStr | None = Field(
        default=None, validation_alias=_env("SANDBOX_BENCH_PASSWORD")
    )
    sandbox_lease_timeout_seconds: float = Field(
        default=120.0, gt=0, validation_alias=_env("SANDBOX_LEASE_TIMEOUT_SECONDS")
    )
    sandbox_image_digest: str = Field(
        default="unrecorded", validation_alias=_env("SANDBOX_IMAGE_DIGEST")
    )
    # ADR-0020: how this worker reaches the sandbox; recorded as the fingerprint's
    # container_runtime. Compose sets docker-network for the worker container on sandbox_net.
    bench_path: Literal["docker-network", "docker-relay"] = Field(
        default="docker-relay", validation_alias=_env("QC_BENCH_PATH")
    )
    master_key: SecretStr | None = Field(default=None, validation_alias=_env("QC_MASTER_KEY"))
    master_key_version: int = Field(default=1, ge=1, validation_alias=_env("QC_MASTER_KEY_VERSION"))
    allow_private_targets: bool | None = Field(
        default=None, validation_alias=_env("ALLOW_PRIVATE_TARGETS")
    )
    feature_live_inspection_public: bool = Field(
        default=False, validation_alias=_env("FEATURE_LIVE_INSPECTION_PUBLIC")
    )
    feature_sandbox: bool | None = Field(default=None, validation_alias=_env("FEATURE_SANDBOX"))
    worker_mode: WorkerMode = Field(
        default=WorkerMode.SEPARATE, validation_alias=_env("WORKER_MODE")
    )
    worker_concurrency: int | None = Field(
        default=None, ge=1, validation_alias=_env("WORKER_CONCURRENCY")
    )
    worker_lease_seconds: int = Field(
        default=60, ge=5, validation_alias=_env("WORKER_LEASE_SECONDS")
    )
    worker_heartbeat_seconds: float = Field(
        default=20.0, gt=0, validation_alias=_env("WORKER_HEARTBEAT_SECONDS")
    )
    worker_poll_seconds: float = Field(
        default=1.0, gt=0, validation_alias=_env("WORKER_POLL_SECONDS")
    )
    # Local-profile fallback keys (DEPLOYMENT §6); the demo profile is BYOK only (Phase 5).
    gemini_api_key: SecretStr | None = Field(default=None, validation_alias=_env("GEMINI_API_KEY"))
    openrouter_api_key: SecretStr | None = Field(
        default=None, validation_alias=_env("OPENROUTER_API_KEY")
    )
    # ADR-0016: free OpenRouter models only, by default and for every run unless an operator
    # explicitly turns LLM_FREE_ONLY off. Nothing ever falls back to a paid model.
    llm_provider: Literal["gemini", "openrouter", "stub"] = Field(
        default="openrouter", validation_alias=_env("LLM_PROVIDER")
    )
    # Pinned from the Phase 2 free-model benchmark (evals/results, PHASE_2_REPORT).
    llm_model: str = Field(
        default="nvidia/nemotron-3-super-120b-a12b:free", validation_alias=_env("LLM_MODEL")
    )
    llm_free_only: bool = Field(default=True, validation_alias=_env("LLM_FREE_ONLY"))
    # OpenRouter free tier: ~20 requests/min and 50/day without purchased credits.
    llm_requests_per_minute: int = Field(
        default=16, ge=1, validation_alias=_env("LLM_REQUESTS_PER_MINUTE")
    )
    llm_daily_request_limit: int = Field(
        default=45, ge=1, validation_alias=_env("LLM_DAILY_REQUEST_LIMIT")
    )
    # Free reasoning models can take ~1 min per call; a timeout wastes a scarce request.
    llm_call_timeout_seconds: float = Field(
        default=120.0, ge=5, validation_alias=_env("LLM_CALL_TIMEOUT_SECONDS")
    )
    # Stub provider only: seconds each canned answer takes, so tests can act mid-call.
    llm_stub_delay_seconds: float = Field(
        default=0.0, ge=0, le=60, validation_alias=_env("LLM_STUB_DELAY_SECONDS")
    )
    llm_max_concurrency: int = Field(default=1, ge=1, validation_alias=_env("LLM_MAX_CONCURRENCY"))
    llm_fallback_model: str | None = Field(
        default=None, validation_alias=_env("LLM_FALLBACK_MODEL")
    )
    openrouter_base_url: str = Field(
        default="https://openrouter.ai/api/v1", validation_alias=_env("OPENROUTER_BASE_URL")
    )
    sse_heartbeat_seconds: float = Field(
        default=15.0, gt=0, validation_alias=_env("SSE_HEARTBEAT_SECONDS")
    )
    cors_origins: list[str] = Field(default_factory=list, validation_alias=_env("CORS_ORIGINS"))
    cookie_domain: str | None = Field(default=None, validation_alias=_env("COOKIE_DOMAIN"))
    log_level: str = Field(default="INFO", validation_alias=_env("LOG_LEVEL"))
    # Operations (Phase 5). The metrics endpoint is open locally and needs this token
    # elsewhere; without it the endpoint answers 404 outside the local profile.
    metrics_token: SecretStr | None = Field(default=None, validation_alias=_env("METRICS_TOKEN"))
    db_pool_size: int = Field(default=5, ge=1, le=50, validation_alias=_env("DB_POOL_SIZE"))
    db_max_overflow: int = Field(default=5, ge=0, le=50, validation_alias=_env("DB_MAX_OVERFLOW"))
    db_pool_timeout_seconds: float = Field(
        default=10.0, gt=0, validation_alias=_env("DB_POOL_TIMEOUT_SECONDS")
    )
    # Server-side limits on the app's own metadata connections (not the target or sandbox,
    # which have their own): no metadata query should take a minute or hold a transaction.
    db_statement_timeout_ms: int = Field(
        default=60_000, ge=1000, validation_alias=_env("DB_STATEMENT_TIMEOUT_MS")
    )
    db_idle_in_transaction_timeout_ms: int = Field(
        default=120_000, ge=1000, validation_alias=_env("DB_IDLE_IN_TRANSACTION_TIMEOUT_MS")
    )
    # SIGTERM: in-flight jobs get this long to finish before they are abandoned to lease
    # expiry (and resumed from their checkpoint by the next worker).
    worker_shutdown_grace_seconds: float = Field(
        default=20.0, ge=0, le=300, validation_alias=_env("WORKER_SHUTDOWN_GRACE_SECONDS")
    )
    # GitHub OAuth (T5.1). Sign-in is offered only when both are set.
    github_client_id: str | None = Field(default=None, validation_alias=_env("GITHUB_CLIENT_ID"))
    github_client_secret: SecretStr | None = Field(
        default=None, validation_alias=_env("GITHUB_CLIENT_SECRET")
    )
    # Public URLs: the OAuth callback is registered against the API, and sign-in returns the
    # browser to the web app. Must be HTTPS outside the local profile.
    public_api_url: str | None = Field(default=None, validation_alias=_env("PUBLIC_API_URL"))
    web_base_url: str | None = Field(default=None, validation_alias=_env("WEB_BASE_URL"))
    # Number of reverse proxies that append to X-Forwarded-For (rate limits use the client
    # address). 0 = ignore the header: a client can put anything there.
    trusted_proxy_hops: int = Field(
        default=0, ge=0, le=5, validation_alias=_env("TRUSTED_PROXY_HOPS")
    )
    session_ttl_seconds: int = Field(
        default=30 * 24 * 3600, ge=300, validation_alias=_env("SESSION_TTL_SECONDS")
    )

    @field_validator("metrics_token", "github_client_secret", mode="before")
    @classmethod
    def _blank_secret_is_unset(cls, value: object) -> object:
        # An empty env var must not become an empty secret (e.g. an empty bearer token).
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("master_key")
    @classmethod
    def _master_key_is_32_bytes(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return value
        try:
            raw = base64.b64decode(value.get_secret_value(), validate=True)
        except binascii.Error as exc:
            raise ValueError("QC_MASTER_KEY must be base64") from exc
        if len(raw) != 32:
            raise ValueError("QC_MASTER_KEY must decode to 32 bytes")
        return value

    @model_validator(mode="after")
    def _free_models_only(self) -> Self:
        if self.llm_provider == "stub":
            # Offline canned responses for UI tests: free by construction, local only.
            if self.profile is not Profile.LOCAL:
                raise ValueError("LLM_PROVIDER=stub is only allowed in the local profile")
            return self
        if not self.llm_free_only:
            return self
        if self.llm_provider != "openrouter":
            raise ValueError(
                "LLM_FREE_ONLY requires LLM_PROVIDER=openrouter: only free OpenRouter models "
                "are allowed"
            )
        for name, model in (
            ("LLM_MODEL", self.llm_model),
            ("LLM_FALLBACK_MODEL", self.llm_fallback_model),
        ):
            if model is not None and not is_free_model(model):
                raise ValueError(
                    f"{name} must be a free OpenRouter model (an id ending in ':free', or "
                    "openrouter/free) while LLM_FREE_ONLY is on"
                )
        return self

    @model_validator(mode="after")
    def _apply_profile_rules(self) -> Self:
        local = self.profile is Profile.LOCAL
        if self.allow_private_targets is None:
            self.allow_private_targets = local
        if self.feature_sandbox is None:
            self.feature_sandbox = local
        if local:
            self.public_api_url = self.public_api_url or "http://localhost:8000"
            self.web_base_url = self.web_base_url or "http://localhost:3000"
        if self.worker_concurrency is None:
            self.worker_concurrency = 2 if local else 1
        if self.worker_heartbeat_seconds * 2 >= self.worker_lease_seconds:
            # Two missed beats must still fit inside the lease, or healthy jobs get reclaimed.
            raise ValueError("WORKER_HEARTBEAT_SECONDS must be under half of WORKER_LEASE_SECONDS")
        if not local:
            # Public deployments: SSRF guard must not be bypassable (SECURITY.md §5.1).
            if self.allow_private_targets:
                raise ValueError("ALLOW_PRIVATE_TARGETS must be false in the demo profile")
            if self.master_key is None:
                raise ValueError("QC_MASTER_KEY is required in the demo profile")
            if self.llm_provider == "openrouter" and self.openrouter_api_key is not None:
                # The demo is BYOK only (DEPLOYMENT §1): a shared server key would be spent by
                # anonymous visitors.
                raise ValueError("OPENROUTER_API_KEY must not be set in the demo profile (BYOK)")
            if self.github_client_id is not None:
                for name, url in (("PUBLIC_API_URL", self.public_api_url),
                                  ("WEB_BASE_URL", self.web_base_url)):  # fmt: skip
                    if url is None or not url.startswith("https://"):
                        raise ValueError(f"{name} must be an https:// URL for GitHub sign-in")
        if (self.github_client_id is None) != (self.github_client_secret is None):
            raise ValueError("GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET must be set together")
        return self

    @property
    def github_login_enabled(self) -> bool:
        return self.github_client_id is not None and self.github_client_secret is not None

    def engine_options(self) -> "EngineSettings":
        """Keyword arguments for `db.engine.make_engine` (pool and server-side timeouts)."""
        return {
            "pool_size": self.db_pool_size,
            "max_overflow": self.db_max_overflow,
            "pool_timeout": self.db_pool_timeout_seconds,
            "statement_timeout_ms": self.db_statement_timeout_ms,
            "idle_in_transaction_timeout_ms": self.db_idle_in_transaction_timeout_ms,
        }
