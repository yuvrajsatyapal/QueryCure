"""Neon's PgBouncer (transaction mode) rejects startup `options`, so pooled endpoints must get
no startup parameters at all; direct endpoints keep the server-enforced startup timeouts."""

import pytest

from querycure.db.engine import (
    CONNECT_TIMEOUT_SECONDS,
    connect_args_for,
    is_pooled_url,
    resolve_timeout_scope,
)

POOLED = "postgresql://qc_app:pw@ep-example-123456-pooler.c-4.us-east-2.aws.neon.tech/db"
DIRECT = "postgresql://qc_app:pw@ep-example-123456.c-4.us-east-2.aws.neon.tech/db"
LOCAL = "postgresql://qc_app:pw@127.0.0.1:5432/querycure"


@pytest.mark.parametrize(("url", "pooled"), [(POOLED, True), (DIRECT, False), (LOCAL, False)])
def test_pooler_hosts_are_detected_by_hostname_only(url: str, pooled: bool) -> None:
    assert is_pooled_url(url) is pooled


def test_a_password_containing_pooler_does_not_make_a_direct_url_pooled() -> None:
    assert not is_pooled_url("postgresql://u:x-pooler@db.example.com/d")


def test_auto_scope_follows_the_host() -> None:
    assert resolve_timeout_scope(POOLED, "auto") == "transaction"
    assert resolve_timeout_scope(DIRECT, "auto") == "session"
    assert resolve_timeout_scope(DIRECT, "transaction") == "transaction"


def test_pooled_connections_send_no_startup_options() -> None:
    args = connect_args_for("transaction", 60_000, 120_000)

    assert "options" not in args
    assert args["prepare_threshold"] is None  # no server-side prepared statements via PgBouncer


def test_direct_connections_keep_server_enforced_startup_timeouts() -> None:
    args = connect_args_for("session", 60_000, 120_000)

    assert args["options"] == (
        "-c statement_timeout=60000 -c idle_in_transaction_session_timeout=120000"
    )


def test_no_timeouts_means_no_options_in_either_scope() -> None:
    assert "options" not in connect_args_for("session", None, None)
    assert "options" not in connect_args_for("transaction", None, None)


@pytest.mark.parametrize("scope", ["session", "transaction"])
def test_every_connection_detects_a_dead_peer(scope: str) -> None:
    """2026-10-18: a worker connected to Neon kept a half-open TCP connection after the
    compute suspended; with no keepalive settings macOS waits ~2 h before probing, so an
    await (and shutdown) hung. libpq's own keepalives notice a dead peer in about a minute,
    and connect_timeout bounds a connection attempt. Both are client-side, so PgBouncer
    accepts them."""
    args = connect_args_for(scope, None, None)  # type: ignore[arg-type]

    assert args["connect_timeout"] == CONNECT_TIMEOUT_SECONDS
    assert args["keepalives"] == 1
    probe = args["keepalives_idle"] + args["keepalives_interval"] * args["keepalives_count"]
    assert probe <= 90
