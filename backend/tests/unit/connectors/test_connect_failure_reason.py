import pytest

from querycure.connectors.inspection_gateway import connect_failure_reason


@pytest.mark.parametrize(
    ("message", "reason"),
    [
        (
            'connection to server at "127.0.0.1", port 5432 failed: FATAL:  password '
            'authentication failed for user "qc_demo_inspector"',
            "auth_failed",
        ),
        ('FATAL:  role "nobody" does not exist', "auth_failed"),
        ('FATAL:  database "nope" does not exist', "database_missing"),
        ("server does not support SSL, but SSL was required", "tls_unsupported"),
        ("SSL error: certificate verify failed", "tls_failed"),
        (
            'connection to server at "10.0.0.5", port 5432 failed: Connection refused\n\t'
            "Is the server running on that host and accepting TCP/IP connections?",
            "unreachable",
        ),
        ("connection timeout expired", "unreachable"),
        ("something new libpq says", "unreachable"),
    ],
)
def test_classifies_libpq_messages_into_fixed_reasons(message: str, reason: str) -> None:
    assert connect_failure_reason(message) == reason
