"""Report replay and report API (T4.6, REPLAY_ENGINE §8.1), through the real app as qc_app.

Every `not_replayable` / `integrity_failed` code is reached from a fixture: the run is sealed
through the real API (create → cancel, which finalizes), then one record is changed with the
owner role, the way a bug or a manual edit would. No LLM transport is reachable: building a
provider client or sending a request fails the test.
"""

import hashlib
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx2 as httpx
import psycopg
import pytest

from querycure.reports import registry
from querycure.reports.provenance import unlabeled_numbers
from tests.integration.test_investigations_api import body, client_for

pytestmark = pytest.mark.integration


@pytest.fixture
async def api(migrated_db: str) -> AsyncIterator[httpx.AsyncClient]:
    async for c in client_for(migrated_db):
        yield c


@pytest.fixture(autouse=True)
def no_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Report replay must never construct or call a model client."""

    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("an LLM client was used during report replay")

    monkeypatch.setattr("querycure.llm.providers.build_client", refuse)
    monkeypatch.setattr("querycure.llm.openrouter.OpenRouterClient.complete_json", refuse)
    monkeypatch.setattr("querycure.llm.stub.StubClient.complete_json", refuse)


@pytest.fixture(autouse=True)
def _no_active_runs(owner: psycopg.Connection) -> None:
    owner.execute(
        "UPDATE investigation_runs SET status = 'cancelled', finalized_at = now() "
        "WHERE status IN ('queued', 'running', 'awaiting_approval', 'cancelling')"
    )


async def sealed_run(api: httpx.AsyncClient) -> str:
    created = await api.post("/api/v1/investigations", json=body())
    assert created.status_code == 202, created.text
    run_id: str = created.json()["run"]["id"]
    cancelled = await api.post(f"/api/v1/runs/{run_id}/cancel")
    assert cancelled.status_code == 202, cancelled.text
    return run_id


async def replay(api: httpx.AsyncClient, run_id: str, **kw: Any) -> dict[str, Any]:
    r = await api.post(f"/api/v1/runs/{run_id}/replay/report", json=kw or None)
    assert r.status_code == 200, r.text
    out: dict[str, Any] = r.json()
    return out


def manifest_of(owner: psycopg.Connection, run_id: str) -> tuple[str, dict[str, Any]]:
    row = owner.execute(
        "SELECT a.id, a.content FROM replay_manifests m JOIN artifacts a "
        "ON a.id = m.manifest_artifact_id WHERE m.run_id = %s",
        (run_id,),
    ).fetchone()
    assert row is not None
    return str(row[0]), json.loads(bytes(row[1]))


def reseal_manifest(owner: psycopg.Connection, run_id: str, manifest: dict[str, Any]) -> None:
    """Rewrite the manifest *and* its reference digests consistently (owner role): what an
    attacker with database access could do. Replay then cannot tell (REPLAY_ENGINE §6.2)."""
    from querycure.replay.canonical import canonical_json

    content = canonical_json(manifest)
    sha = hashlib.sha256(b"qc-json-v1\n" + content).hexdigest()
    artifact_id, _ = manifest_of(owner, run_id)
    owner.execute(
        "UPDATE artifacts SET content = %s, sha256 = %s WHERE id = %s",
        (content, sha, artifact_id),
    )
    owner.execute(
        "UPDATE replay_manifests SET manifest_sha256 = %s WHERE run_id = %s", (sha, run_id)
    )


def report_artifact(owner: psycopg.Connection, run_id: str, role: str) -> str:
    row = owner.execute(
        "SELECT artifact_id FROM run_artifacts WHERE run_id = %s AND role = %s", (run_id, role)
    ).fetchone()
    assert row is not None
    return str(row[0])


async def test_sealed_report_is_served_exported_and_verifies(api: httpx.AsyncClient) -> None:
    run_id = await sealed_run(api)

    report = (await api.get(f"/api/v1/runs/{run_id}/report")).json()
    assert report["builder_version"] == "report-builder@1"
    assert report["final_status"] == "cancelled"
    assert report["report"]["partial"] is True
    md = await api.get(f"/api/v1/runs/{run_id}/report.md")
    assert md.headers["content-type"].startswith("text/markdown")
    assert f"sha256:{report['manifest_sha256']}" in md.text
    assert "shasum -a 256" in md.text
    body_md = md.text.split("<!-- qc-export-footer -->")[0]
    assert (
        hashlib.sha256(b"qc-text-v1\n" + body_md.encode()).hexdigest() == report["report_md_sha256"]
    )
    assert unlabeled_numbers(body_md) == []
    exported = (await api.get(f"/api/v1/runs/{run_id}/report.json")).json()
    assert exported["export"]["manifest_sha256"] == f"sha256:{report['manifest_sha256']}"
    assert exported["report"] == report["report"]
    manifest = (await api.get(f"/api/v1/runs/{run_id}/replay/manifest")).json()
    assert manifest["manifest"]["final_status"] == "cancelled"

    attempt = await replay(api, run_id)

    assert attempt["kind"] == "report"
    assert attempt["status"] == "verified", attempt
    assert attempt["failure_code"] is None
    assert attempt["warnings"] == []
    names = [c["name"] for c in attempt["result"]["checks"]]
    assert names == [
        "finalized",
        "manifest",
        "manifest_schema",
        "artifacts",
        "events",
        "rebuild_json",
        "rebuild_markdown",
    ]
    assert attempt["result"]["final_status"] == "cancelled"
    listed = (await api.get(f"/api/v1/runs/{run_id}/replay/attempts")).json()
    assert [a["id"] for a in listed["items"]] == [attempt["id"]]
    assert (await api.get(f"/api/v1/replay-attempts/{attempt['id']}")).json()["status"] == (
        "verified"
    )


async def test_unfinalized_run_is_not_replayable(
    api: httpx.AsyncClient, owner: psycopg.Connection
) -> None:
    created = await api.post("/api/v1/investigations", json=body())
    run_id = created.json()["run"]["id"]

    attempt = await replay(api, run_id)
    report = await api.get(f"/api/v1/runs/{run_id}/report")
    manifest = await api.get(f"/api/v1/runs/{run_id}/replay/manifest")

    assert (attempt["status"], attempt["failure_code"]) == ("not_replayable", "not_finalized")
    assert report.status_code == manifest.status_code == 404
    assert report.json()["error"]["code"] == "NOT_FINALIZED"


def _mutate_event(owner: psycopg.Connection, run_id: str) -> None:
    owner.execute(
        "UPDATE investigation_events SET payload = '{\"edited\": true}' "
        "WHERE run_id = %s AND seq = 1",
        (run_id,),
    )


def _drop_manifest_row(owner: psycopg.Connection, run_id: str) -> None:
    owner.execute("DELETE FROM replay_manifests WHERE run_id = %s", (run_id,))


def _edit_manifest_bytes(owner: psycopg.Connection, run_id: str) -> None:
    artifact_id, _ = manifest_of(owner, run_id)
    owner.execute(
        "UPDATE artifacts SET content = content || ' '::bytea WHERE id = %s", (artifact_id,)
    )


def _future_manifest_schema(owner: psycopg.Connection, run_id: str) -> None:
    _, manifest = manifest_of(owner, run_id)
    reseal_manifest(owner, run_id, {**manifest, "schema_version": 99})


def _unknown_profile(owner: psycopg.Connection, run_id: str) -> None:
    _, manifest = manifest_of(owner, run_id)
    arts = [
        {**a, "profile": "qc-json-v9"} if i == 0 else a for i, a in enumerate(manifest["artifacts"])
    ]
    reseal_manifest(owner, run_id, {**manifest, "artifacts": arts})


def _purge_markdown(owner: psycopg.Connection, run_id: str) -> None:
    owner.execute(
        "DELETE FROM artifacts WHERE id = %s", (report_artifact(owner, run_id, "output.report_md"),)
    )


def _edit_markdown(owner: psycopg.Connection, run_id: str) -> None:
    owner.execute(
        "UPDATE artifacts SET content = content || 'tampered'::bytea WHERE id = %s",
        (report_artifact(owner, run_id, "output.report_md"),),
    )


def _purge_events(owner: psycopg.Connection, run_id: str) -> None:
    owner.execute("DELETE FROM investigation_events WHERE run_id = %s", (run_id,))


def _gap(owner: psycopg.Connection, run_id: str) -> None:
    owner.execute("DELETE FROM investigation_events WHERE run_id = %s AND seq = 1", (run_id,))


def _edit_record(owner: psycopg.Connection, run_id: str) -> None:
    owner.execute(
        "UPDATE investigations SET objective = 'edited after finalization' "
        "WHERE id = (SELECT investigation_id FROM investigation_runs WHERE id = %s)",
        (run_id,),
    )


@pytest.mark.parametrize(
    ("mutate", "status", "code"),
    [
        (_drop_manifest_row, "not_replayable", "manifest_missing"),
        (_edit_manifest_bytes, "integrity_failed", "manifest_digest_mismatch"),
        (_future_manifest_schema, "not_replayable", "unsupported_manifest_schema"),
        (_unknown_profile, "not_replayable", "unsupported_profile"),
        (_purge_markdown, "not_replayable", "artifact_purged"),
        (_edit_markdown, "integrity_failed", "artifact_digest_mismatch"),
        (_purge_events, "not_replayable", "events_purged"),
        (_gap, "integrity_failed", "events_gap"),
        (_mutate_event, "integrity_failed", "events_digest_mismatch"),
        (_edit_record, "integrity_failed", "rebuild_mismatch"),
    ],
    ids=lambda v: v if isinstance(v, str) else v.__name__,
)
async def test_every_failure_code_is_reachable(
    api: httpx.AsyncClient, owner: psycopg.Connection, mutate: Any, status: str, code: str
) -> None:
    run_id = await sealed_run(api)
    mutate(owner, run_id)

    attempt = await replay(api, run_id)

    assert (attempt["status"], attempt["failure_code"]) == (status, code), attempt["result"]
    assert any(c["code"] == code for c in attempt["result"]["checks"])


async def test_purged_and_tampered_are_all_collected_most_severe_wins(
    api: httpx.AsyncClient, owner: psycopg.Connection
) -> None:
    run_id = await sealed_run(api)
    _purge_markdown(owner, run_id)
    _mutate_event(owner, run_id)

    attempt = await replay(api, run_id)

    codes = {c["code"] for c in attempt["result"]["checks"] if c["code"]}
    assert codes >= {"artifact_purged", "events_digest_mismatch"}
    assert (attempt["status"], attempt["failure_code"]) == (
        "integrity_failed",
        "events_digest_mismatch",
    )


async def test_retired_builder_and_renderer_give_stored_only_with_warnings(
    api: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = await sealed_run(api)
    monkeypatch.setattr(registry, "RETIRED_BUILDERS", frozenset({"report-builder@1"}))
    monkeypatch.setattr(registry, "RETIRED_RENDERERS", frozenset({"report-md@1"}))

    attempt = await replay(api, run_id)

    assert attempt["status"] == "verified_stored_only"
    assert set(attempt["warnings"]) == {"builder_retired", "md_renderer_retired"}


async def test_status_comes_from_the_manifest_and_row_drift_is_a_warning(
    api: httpx.AsyncClient, owner: psycopg.Connection
) -> None:
    run_id = await sealed_run(api)
    owner.execute("UPDATE investigation_runs SET status = 'failed' WHERE id = %s", (run_id,))

    attempt = await replay(api, run_id, client_schema_versions=[0])

    assert attempt["status"] == "verified"
    assert attempt["result"]["final_status"] == "cancelled"
    assert set(attempt["warnings"]) == {"run_row_differs_from_manifest", "schema_newer_than_client"}


async def test_unexpected_error_is_recorded_as_error(
    api: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = await sealed_run(api)

    async def boom(*a: Any, **k: Any) -> Any:
        raise RuntimeError("disk on fire")

    monkeypatch.setattr("querycure.api.routers.reports.verify_report", boom)
    attempt = await replay(api, run_id)

    assert (attempt["status"], attempt["failure_code"]) == ("error", "internal_error")


async def test_other_users_get_404_for_reports_manifests_and_attempts(
    api: httpx.AsyncClient, migrated_db: str, owner: psycopg.Connection
) -> None:
    run_id = await sealed_run(api)
    attempt = await replay(api, run_id)
    async for other in client_for(migrated_db):
        user_id = owner.execute(
            "INSERT INTO users (kind) VALUES ('anonymous') RETURNING id"
        ).fetchone()
        assert user_id is not None
        import uuid as _uuid

        token = _uuid.uuid4().hex
        owner.execute(
            "INSERT INTO sessions (user_id, token_hash, expires_at) "
            "VALUES (%s, %s, now() + interval '1 hour')",
            (user_id[0], hashlib.sha256(token.encode()).hexdigest()),
        )
        other.cookies.set("qc_session", token)
        for path in (
            f"/api/v1/runs/{run_id}/report",
            f"/api/v1/runs/{run_id}/report.md",
            f"/api/v1/runs/{run_id}/report.json",
            f"/api/v1/runs/{run_id}/replay/manifest",
            f"/api/v1/runs/{run_id}/replay/attempts",
            f"/api/v1/replay-attempts/{attempt['id']}",
        ):
            assert (await other.get(path)).status_code == 404, path
        r = await other.post(f"/api/v1/runs/{run_id}/replay/report")
        assert r.status_code == 404


async def test_plan_diff_api_compares_two_plans_of_the_run(
    api: httpx.AsyncClient, migrated_db: str
) -> None:
    from tests.integration.test_investigations_api import PLANS

    uploaded = await api.post(
        "/api/v1/inspect/plan",
        content=(PLANS / "synthetic_canonical_seqscan_sort.json").read_bytes(),
        headers={"Content-Type": "application/json"},
    )
    assert uploaded.status_code == 200, uploaded.text
    sha = uploaded.json()["artifact_sha256"]
    created = await api.post(
        "/api/v1/investigations", json=body(query=None, plan_artifact_sha256=sha)
    )
    assert created.status_code == 202, created.text
    run_id = created.json()["run"]["id"]

    same = await api.get(f"/api/v1/runs/{run_id}/plans/diff", params={"from": sha, "to": sha})
    unknown = await api.get(
        f"/api/v1/runs/{run_id}/plans/diff", params={"from": sha, "to": "0" * 64}
    )

    assert same.status_code == 200, same.text
    diff = same.json()["diff"]
    assert {n["status"] for n in diff["nodes"]} == {"same"}
    assert diff["summary"]["execution_time_ms"]["from_value"] == pytest.approx(121.0)
    assert unknown.status_code == 404
