"""Final reports, exports, manifests, report replay and plan diffs (API_DESIGN §2, Phase 4).

Everything is user-scoped: another user's run, attempt or artifact is a 404. Report replay is
synchronous, reads only the metadata database and makes no LLM call; an integrity failure is a
result (`status = integrity_failed`), not an HTTP error.
"""

import json
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Query, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from querycure.api.deps import ConnDep, CurrentUser, EngineDep
from querycure.api.schemas.replay import (
    ManifestOut,
    PlanDiffOut,
    ReplayAttemptOut,
    ReplayAttemptPage,
    ReportOut,
    ReportReplayRequest,
)
from querycure.core.errors import BadRequestError, NotFinalizedError, NotFoundError
from querycure.core.logging import get_logger
from querycure.db.repositories.replay import (
    AttemptRow,
    decode_cursor,
    encode_cursor,
    get_attempt,
    insert_attempt,
    list_attempts,
)
from querycure.db.repositories.runs import get_run_for_user
from querycure.domain.users import User
from querycure.plans.diff import diff_plans
from querycure.plans.parser import parse_plan
from querycure.replay.artifact_store import get_artifact
from querycure.replay.report_replay import verify_report

router = APIRouter(tags=["reports"])
log = get_logger(__name__)
PLAN_ROLES = ("input.plan", "context.plan", "experiment.plan")
FOOTER_MARKER = "<!-- qc-export-footer -->"


async def owned_run(conn: AsyncConnection, user: User, run_id: uuid.UUID) -> None:
    if await get_run_for_user(conn, user_id=user.id, run_id=run_id) is None:
        raise NotFoundError("Run not found.")


def attempt_out(row: AttemptRow) -> ReplayAttemptOut:
    return ReplayAttemptOut.model_validate(row.model_dump())


async def _report_row(conn: AsyncConnection, run_id: uuid.UUID) -> Any:
    row = (
        await conn.execute(
            text(
                "SELECT p.final_status, p.outcome, p.report_schema_version, p.builder_version, "
                "p.md_renderer_version, p.report_json_sha256, p.report_md_sha256, "
                "m.manifest_sha256 FROM investigation_reports p "
                "JOIN replay_manifests m ON m.run_id = p.run_id WHERE p.run_id = :id"
            ),
            {"id": run_id},
        )
    ).first()
    if row is None:
        raise NotFinalizedError(
            "This run has no final report. Runs from before Phase 4 are never finalized."
        )
    return row


async def _stored(conn: AsyncConnection, sha: str) -> bytes:
    artifact = await get_artifact(conn, sha)  # re-verifies the digest
    if artifact is None:
        raise NotFoundError("The stored report artifact is missing.")
    return artifact.content


@router.get("/runs/{run_id}/report")
async def run_report(run_id: uuid.UUID, conn: ConnDep, user: CurrentUser) -> ReportOut:
    await owned_run(conn, user, run_id)
    row = await _report_row(conn, run_id)
    content = await _stored(conn, row.report_json_sha256)
    return ReportOut(
        run_id=run_id,
        final_status=row.final_status,
        outcome=row.outcome,
        report_schema_version=row.report_schema_version,
        builder_version=row.builder_version,
        md_renderer_version=row.md_renderer_version,
        report_json_sha256=row.report_json_sha256,
        report_md_sha256=row.report_md_sha256,
        manifest_sha256=row.manifest_sha256,
        report=json.loads(content),
    )


def _verify_instructions(run_id: uuid.UUID, row: Any, profile: str, body_cmd: str) -> list[str]:
    return [
        f"Run: {run_id}",
        f"Manifest digest: sha256:{row.manifest_sha256}",
        f"Report digest ({profile}): sha256:"
        + (row.report_md_sha256 if profile == "qc-text-v1" else row.report_json_sha256),
        "Reproduce the report digest (REPLAY_ENGINE §2.3): "
        f"{{ printf '{profile}\\n'; {body_cmd}; }} | shasum -a 256",
        "Integrity checks prove consistency with the digests stored for this run, not "
        "authenticity. Keep this manifest digest to check the live record later.",
    ]


@router.get("/runs/{run_id}/report.md")
async def run_report_markdown(run_id: uuid.UUID, conn: ConnDep, user: CurrentUser) -> Response:
    """Stored Markdown plus an export footer (manifest digest, run ID, how to verify)."""
    await owned_run(conn, user, run_id)
    row = await _report_row(conn, run_id)
    body = (await _stored(conn, row.report_md_sha256)).decode("utf-8")
    footer = _verify_instructions(
        run_id, row, "qc-text-v1", f"sed '/^{FOOTER_MARKER}$/,$d' report.md"
    )
    # The stored body ends with one LF; deleting the marker line onwards restores it exactly.
    text_out = body + FOOTER_MARKER + "\n" + "\n".join(f"- {line}" for line in footer)
    return Response(
        content=text_out + "\n",
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="querycure-{run_id}.md"'},
    )


@router.get("/runs/{run_id}/report.json")
async def run_report_json(run_id: uuid.UUID, conn: ConnDep, user: CurrentUser) -> Response:
    """`report` is the stored report JSON; `export` carries the manifest digest."""
    await owned_run(conn, user, run_id)
    row = await _report_row(conn, run_id)
    body = json.loads(await _stored(conn, row.report_json_sha256))
    export = {
        "run_id": str(run_id),
        "manifest_sha256": f"sha256:{row.manifest_sha256}",
        "report_json_sha256": f"sha256:{row.report_json_sha256}",
        "report_md_sha256": f"sha256:{row.report_md_sha256}",
        "verify": _verify_instructions(
            run_id,
            row,
            "qc-json-v1",
            "cat report.canonical.json  # `.report` re-encoded as RFC 8785",
        ),
    }
    return Response(
        content=json.dumps({"export": export, "report": body}, indent=1, ensure_ascii=False),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="querycure-{run_id}.json"'},
    )


@router.get("/runs/{run_id}/replay/manifest")
async def run_manifest(run_id: uuid.UUID, conn: ConnDep, user: CurrentUser) -> ManifestOut:
    await owned_run(conn, user, run_id)
    row = (
        await conn.execute(
            text("SELECT manifest_sha256 FROM replay_manifests WHERE run_id = :id"),
            {"id": run_id},
        )
    ).first()
    if row is None:
        raise NotFinalizedError("This run was never finalized; it has no manifest.")
    return ManifestOut(
        run_id=run_id,
        manifest_sha256=row.manifest_sha256,
        manifest=json.loads(await _stored(conn, row.manifest_sha256)),
    )


@router.post("/runs/{run_id}/replay/report")
async def replay_report(
    run_id: uuid.UUID,
    engine: EngineDep,
    conn: ConnDep,
    user: CurrentUser,
    body: ReportReplayRequest | None = None,
) -> ReplayAttemptOut:
    """Synchronous verification; the attempt row records the result (REPLAY_ENGINE §8.1)."""
    await owned_run(conn, user, run_id)
    versions = tuple(body.client_schema_versions) if body and body.client_schema_versions else None
    try:
        async with engine.connect() as read:
            result = await verify_report(read, run_id, client_schema_versions=versions)
        row = await insert_attempt(
            conn,
            user_id=user.id,
            kind="report",
            source_run_id=run_id,
            status=result.status,
            failure_code=result.failure_code,
            warnings=result.warnings,
            result=result.result_json(),
            finished=True,
        )
    except Exception:
        log.exception("report_replay_failed", run_id=str(run_id))
        row = await insert_attempt(
            conn,
            user_id=user.id,
            kind="report",
            source_run_id=run_id,
            status="error",
            failure_code="internal_error",
            finished=True,
        )
    return attempt_out(row)


@router.get("/replay-attempts/{attempt_id}")
async def replay_attempt(
    attempt_id: uuid.UUID, conn: ConnDep, user: CurrentUser
) -> ReplayAttemptOut:
    row = await get_attempt(conn, attempt_id, user_id=user.id)
    if row is None:
        raise NotFoundError("Replay attempt not found.")
    return attempt_out(row)


@router.get("/runs/{run_id}/replay/attempts")
async def run_replay_attempts(
    run_id: uuid.UUID,
    conn: ConnDep,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: str | None = None,
) -> ReplayAttemptPage:
    await owned_run(conn, user, run_id)
    try:
        after = decode_cursor(cursor) if cursor else None
    except ValueError as exc:
        raise BadRequestError("Invalid cursor.") from exc
    rows = await list_attempts(
        conn, user_id=user.id, source_run_id=run_id, limit=limit + 1, after=after
    )
    return ReplayAttemptPage(
        items=[attempt_out(r) for r in rows[:limit]],
        next_cursor=encode_cursor(rows[limit - 1]) if len(rows) > limit else None,
    )


@router.get("/runs/{run_id}/plans/diff")
async def plan_diff(
    run_id: uuid.UUID,
    conn: ConnDep,
    user: CurrentUser,
    from_: Annotated[str, Query(alias="from", pattern=r"^[0-9a-f]{64}$")],
    to: Annotated[str, Query(pattern=r"^[0-9a-f]{64}$")],
) -> PlanDiffOut:
    """Both plans must be plan artifacts of this run (uploaded, live EXPLAIN or experiment)."""
    await owned_run(conn, user, run_id)
    linked = {
        r[0]
        for r in (
            await conn.execute(
                text(
                    "SELECT a.sha256 FROM run_artifacts ra JOIN artifacts a ON a.id = "
                    "ra.artifact_id WHERE ra.run_id = :run AND ra.role = ANY(:roles) "
                    "AND a.sha256 = ANY(:shas)"
                ),
                {"run": run_id, "roles": list(PLAN_ROLES), "shas": [from_, to]},
            )
        )
    }
    if not {from_, to} <= linked:
        raise NotFoundError("Plan not found for this run.")
    before = parse_plan(await _stored(conn, from_))
    after = parse_plan(await _stored(conn, to))
    return PlanDiffOut(
        run_id=run_id, from_sha256=from_, to_sha256=to, diff=diff_plans(before, after)
    )
