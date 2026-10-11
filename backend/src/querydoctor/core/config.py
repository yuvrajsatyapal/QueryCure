import base64
import binascii
from enum import StrEnum
from typing import Self

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


class Settings(BaseSettings):
    """Env vars from DEPLOYMENT.md §6. Secrets are SecretStr and never printed."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    profile: Profile = Field(default=Profile.LOCAL, validation_alias=_env("QD_PROFILE"))
    database_url: SecretStr | None = Field(default=None, validation_alias=_env("DATABASE_URL"))
    database_url_direct: SecretStr | None = Field(
        default=None, validation_alias=_env("DATABASE_URL_DIRECT")
    )
    # Owner role, used only by Alembic. The app itself connects as the restricted qd_app role.
    database_migration_url: SecretStr | None = Field(
        default=None, validation_alias=_env("DATABASE_MIGRATION_URL")
    )
    sandbox_admin_url: SecretStr | None = Field(
        default=None, validation_alias=_env("SANDBOX_ADMIN_URL")
    )
    master_key: SecretStr | None = Field(default=None, validation_alias=_env("QD_MASTER_KEY"))
    master_key_version: int = Field(default=1, ge=1, validation_alias=_env("QD_MASTER_KEY_VERSION"))
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
    cors_origins: list[str] = Field(default_factory=list, validation_alias=_env("CORS_ORIGINS"))
    cookie_domain: str | None = Field(default=None, validation_alias=_env("COOKIE_DOMAIN"))
    log_level: str = Field(default="INFO", validation_alias=_env("LOG_LEVEL"))

    @field_validator("master_key")
    @classmethod
    def _master_key_is_32_bytes(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return value
        try:
            raw = base64.b64decode(value.get_secret_value(), validate=True)
        except binascii.Error as exc:
            raise ValueError("QD_MASTER_KEY must be base64") from exc
        if len(raw) != 32:
            raise ValueError("QD_MASTER_KEY must decode to 32 bytes")
        return value

    @model_validator(mode="after")
    def _apply_profile_rules(self) -> Self:
        local = self.profile is Profile.LOCAL
        if self.allow_private_targets is None:
            self.allow_private_targets = local
        if self.feature_sandbox is None:
            self.feature_sandbox = local
        if self.worker_concurrency is None:
            self.worker_concurrency = 2 if local else 1
        if not local:
            # Public deployments: SSRF guard must not be bypassable (SECURITY.md §5.1).
            if self.allow_private_targets:
                raise ValueError("ALLOW_PRIVATE_TARGETS must be false in the demo profile")
            if self.master_key is None:
                raise ValueError("QD_MASTER_KEY is required in the demo profile")
        return self
