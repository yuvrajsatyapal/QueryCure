from querycure.core.errors import (
    BudgetExhaustedError,
    InvalidStateError,
    NotFoundError,
    QueryCureError,
    SqlNotAllowedError,
    TargetBlockedError,
)


def test_errors_carry_stable_code_and_status() -> None:
    cases = [
        (NotFoundError("run not found"), "NOT_FOUND", 404),
        (InvalidStateError("approval already decided"), "INVALID_STATE", 409),
        (SqlNotAllowedError("DELETE is not allowed"), "SQL_NOT_ALLOWED", 422),
        (TargetBlockedError("private address"), "CONNECTION_TARGET_BLOCKED", 422),
    ]
    for err, code, status in cases:
        assert isinstance(err, QueryCureError)
        assert err.code == code
        assert err.status == status


def test_envelope_matches_api_contract() -> None:
    err = SqlNotAllowedError(
        "Only a single SELECT statement can be inspected.",
        details=[{"field": "query", "message": "statement type DELETE is not allowed"}],
    )

    assert err.to_envelope(request_id="req_1") == {
        "error": {
            "code": "SQL_NOT_ALLOWED",
            "message": "Only a single SELECT statement can be inspected.",
            "status": 422,
            "details": [{"field": "query", "message": "statement type DELETE is not allowed"}],
            "request_id": "req_1",
        }
    }


def test_internal_errors_are_not_http_errors() -> None:
    err = BudgetExhaustedError("llm_calls")

    assert err.code == "BUDGET_EXHAUSTED"
    assert err.status == 500
