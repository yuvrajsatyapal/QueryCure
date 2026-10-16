"""Export a finalized run as a demo bundle (eval harness only; see `demo.gallery`)."""

import base64
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from querycure.demo.gallery import EXPORTED_ROLES, BundleArtifact, BundleSource, DemoBundle


async def _content(conn: AsyncConnection, sha: str) -> Any:
    return (
        await conn.execute(
            text("SELECT content, kind, canonicalization FROM artifacts WHERE sha256 = :s"),
            {"s": sha},
        )
    ).one()


async def export_bundle(
    conn: AsyncConnection,
    run_id: uuid.UUID,
    *,
    slug: str,
    title: str,
    summary: str,
    label: str,
    source: BundleSource,
) -> DemoBundle | None:
    """None when the run was never finalized (no manifest: nothing verifiable to show)."""
    head = (
        await conn.execute(
            text(
                "SELECT m.manifest_sha256, p.report_json_sha256, p.report_md_sha256, p.outcome "
                "FROM replay_manifests m JOIN investigation_reports p ON p.run_id = m.run_id "
                "WHERE m.run_id = :id"
            ),
            {"id": run_id},
        )
    ).first()
    if head is None:
        return None
    manifest = await _content(conn, head.manifest_sha256)
    report_json = await _content(conn, head.report_json_sha256)
    report_md = await _content(conn, head.report_md_sha256)
    rows = await conn.execute(
        text(
            "SELECT DISTINCT a.sha256, a.kind, a.canonicalization, ra.role, a.content "
            "FROM run_artifacts ra JOIN artifacts a ON a.id = ra.artifact_id "
            "WHERE ra.run_id = :id AND ra.role = ANY(:roles) ORDER BY ra.role, a.sha256"
        ),
        {"id": run_id, "roles": sorted(EXPORTED_ROLES)},
    )
    artifacts = [
        BundleArtifact(
            sha256=r.sha256,
            kind=r.kind,
            role=r.role,
            profile=r.canonicalization,
            content_b64=base64.b64encode(bytes(r.content)).decode(),
        )
        for r in rows
    ]
    return DemoBundle(
        slug=slug,
        title=title,
        summary=summary,
        label=label,
        source=source,
        run_id=str(run_id),
        outcome=head.outcome,
        manifest_sha256=head.manifest_sha256,
        manifest_b64=base64.b64encode(bytes(manifest.content)).decode(),
        report_json_sha256=head.report_json_sha256,
        report_md_sha256=head.report_md_sha256,
        report_json_b64=base64.b64encode(bytes(report_json.content)).decode(),
        report_md_b64=base64.b64encode(bytes(report_md.content)).decode(),
        artifacts=artifacts,
    )
