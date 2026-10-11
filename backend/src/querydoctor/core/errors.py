from typing import Any, ClassVar


class QueryDoctorError(Exception):
    """Base for domain errors. `code` is a stable contract shared with API clients."""

    code: ClassVar[str] = "INTERNAL_ERROR"
    status: ClassVar[int] = 500

    def __init__(self, message: str, *, details: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or []

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


class BadRequestError(QueryDoctorError):
    code = "BAD_REQUEST"
    status = 400


class NotFoundError(QueryDoctorError):
    code = "NOT_FOUND"
    status = 404


class InvalidStateError(QueryDoctorError):
    code = "INVALID_STATE"
    status = 409


class PayloadTooLargeError(QueryDoctorError):
    code = "PAYLOAD_TOO_LARGE"
    status = 413


class ValidationFailedError(QueryDoctorError):
    code = "VALIDATION_ERROR"
    status = 422


class SqlNotAllowedError(QueryDoctorError):
    code = "SQL_NOT_ALLOWED"
    status = 422


class SqlParseError(QueryDoctorError):
    code = "SQL_PARSE_ERROR"
    status = 422


class TargetBlockedError(QueryDoctorError):
    code = "CONNECTION_TARGET_BLOCKED"
    status = 422


class RoleTooPrivilegedError(QueryDoctorError):
    code = "ROLE_TOO_PRIVILEGED"
    status = 422


class TargetUnreachableError(QueryDoctorError):
    code = "TARGET_UNREACHABLE"
    status = 502


class TargetTimeoutError(QueryDoctorError):
    code = "TARGET_TIMEOUT"
    status = 504


class BudgetExhaustedError(QueryDoctorError):
    code = "BUDGET_EXHAUSTED"


class RunCancelledError(QueryDoctorError):
    code = "RUN_CANCELLED"


class ArtifactConflictError(QueryDoctorError):
    code = "ARTIFACT_CONFLICT"
