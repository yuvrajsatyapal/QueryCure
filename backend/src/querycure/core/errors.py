from typing import Any, ClassVar


class QueryCureError(Exception):
    """Base for domain errors. `code` is a stable contract shared with API clients."""

    code: ClassVar[str] = "INTERNAL_ERROR"
    status: ClassVar[int] = 500

    def __init__(
        self,
        message: str,
        *,
        details: list[dict[str, Any]] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or []
        self.headers = headers  # extra response headers, e.g. Retry-After on a 429

    def to_envelope(self, *, request_id: str) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "status": self.status,
                "details": self.details,
                "request_id": request_id,
            }
        }


class BadRequestError(QueryCureError):
    code = "BAD_REQUEST"
    status = 400


class InvalidPlanFormatError(QueryCureError):
    code = "INVALID_PLAN_FORMAT"
    status = 400


class UnauthenticatedError(QueryCureError):
    code = "UNAUTHENTICATED"
    status = 401


class AccessDeniedError(QueryCureError):
    """Restricted trial (ADR-0031): the caller is not an approved account. The message never
    says which accounts are approved."""

    code = "ACCESS_DENIED"
    status = 403


class CsrfFailedError(QueryCureError):
    code = "CSRF_FAILED"
    status = 403


class FeatureDisabledError(QueryCureError):
    code = "FEATURE_DISABLED"
    status = 403


class ApprovalRequiredError(QueryCureError):
    code = "APPROVAL_REQUIRED"
    status = 409


class ConfigurationError(QueryCureError):
    code = "CONFIGURATION_ERROR"
    status = 503


class NotFoundError(QueryCureError):
    code = "NOT_FOUND"
    status = 404


class InvalidStateError(QueryCureError):
    code = "INVALID_STATE"
    status = 409


class PayloadTooLargeError(QueryCureError):
    code = "PAYLOAD_TOO_LARGE"
    status = 413


class ValidationFailedError(QueryCureError):
    code = "VALIDATION_ERROR"
    status = 422


class SqlNotAllowedError(QueryCureError):
    code = "SQL_NOT_ALLOWED"
    status = 422


class SqlParseError(QueryCureError):
    code = "SQL_PARSE_ERROR"
    status = 422


class TargetBlockedError(QueryCureError):
    code = "CONNECTION_TARGET_BLOCKED"
    status = 422


class RoleTooPrivilegedError(QueryCureError):
    code = "ROLE_TOO_PRIVILEGED"
    status = 422


class TargetPermissionError(QueryCureError):
    code = "TARGET_PERMISSION_DENIED"
    status = 422


class TargetQueryError(QueryCureError):
    code = "TARGET_QUERY_ERROR"
    status = 422


class TargetUnreachableError(QueryCureError):
    code = "TARGET_UNREACHABLE"
    status = 502


class TargetTimeoutError(QueryCureError):
    code = "TARGET_TIMEOUT"
    status = 504


class BudgetExhaustedError(QueryCureError):
    code = "BUDGET_EXHAUSTED"


class RunCancelledError(QueryCureError):
    code = "RUN_CANCELLED"


class ArtifactConflictError(QueryCureError):
    code = "ARTIFACT_CONFLICT"


class RunFinalizedError(QueryCureError):
    """Content writes to a sealed run (REPLAY_ENGINE §5 sealing rules)."""

    code = "RUN_FINALIZED"
    status = 409


class IdempotencyConflictError(QueryCureError):
    code = "IDEMPOTENCY_CONFLICT"
    status = 409


class ConcurrencyLimitError(QueryCureError):
    code = "CONCURRENCY_LIMIT"
    status = 429


class SandboxUnavailableError(QueryCureError):
    """The sandbox server cannot be reached, is busy past the wait limit, or is full."""

    code = "SANDBOX_UNAVAILABLE"
    status = 503


class SandboxPolicyError(QueryCureError):
    """Candidate SQL outside the sandbox DDL allowlist (SECURITY §6.5)."""

    code = "SANDBOX_SQL_NOT_ALLOWED"
    status = 422


class NotFinalizedError(QueryCureError):
    """A manifest or final report was requested for a run that was never finalized."""

    code = "NOT_FINALIZED"
    status = 404


class ExperimentNotReplayableError(QueryCureError):
    code = "EXPERIMENT_NOT_REPLAYABLE"
    status = 422


class LlmQuotaExhaustedError(QueryCureError):
    """No free model capacity left today (ADR-0016); nothing is started."""

    code = "LLM_QUOTA_EXHAUSTED"
    status = 429


class RateLimitedError(QueryCureError):
    """A token bucket is empty (T5.3). Carries Retry-After."""

    code = "RATE_LIMITED"
    status = 429
