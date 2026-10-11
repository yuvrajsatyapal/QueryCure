import base64
import binascii
from enum import StrEnum
from typing import Literal, Self

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
    sandbox_admin_url: SecretStr | None = Field(
        default=None, validation_alias=_env("SANDBOX_ADMIN_URL")
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
    llm_provider: Literal["gemini", "openrouter"] = Field(
        default="openrouter", validation_alias=_env("LLM_PROVIDER")
    )
    llm_model: str = Field(default="openrouter/free", validation_alias=_env("LLM_MODEL"))
    llm_free_only: bool = Field(default=True, validation_alias=_env("LLM_FREE_ONLY"))
    # OpenRouter free tier: ~20 requests/min and 50/day without purchased credits.
    llm_requests_per_minute: int = Field(
        default=16, ge=1, validation_alias=_env("LLM_REQUESTS_PER_MINUTE")
    )
    llm_daily_request_limit: int = Field(
        default=45, ge=1, validation_alias=_env("LLM_DAILY_REQUEST_LIMIT")
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
    session_ttl_seconds: int = Field(
        default=30 * 24 * 3600, ge=300, validation_alias=_env("SESSION_TTL_SECONDS")
    )

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
        return self
