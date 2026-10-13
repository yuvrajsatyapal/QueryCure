"""Report replay (REPLAY_ENGINE §7, §8.1): verify a finalized run against its manifest.

Zero LLM calls and no SQL against any target or sandbox: it reads the metadata DB only. Checks
run in order and every mismatch is collected:

1. run finalized                         → not_replayable: not_finalized
2. manifest present, digest matches      → not_replayable: manifest_missing /
                                           integrity_failed: manifest_digest_mismatch
3. manifest schema and profiles known     → not_replayable: unsupported_manifest_schema /
                                           unsupported_profile
4. every listed artifact present, matches → not_replayable: artifact_purged /
                                           integrity_failed: artifact_digest_mismatch
5. events 1..cutoff complete and match    → not_replayable: events_purged /
                                           integrity_failed: events_gap, events_digest_mismatch
6. rebuild with the recorded builder and renderer (skipped when retired: warning)
                                         → integrity_failed: rebuild_mismatch
7. terminal status/outcome from the manifest; a differing run row is a warning.

Severity: error > integrity_failed > not_replayable > verified_stored_only > verified. What it
proves is consistency with stored digests, not authenticity (REPLAY_ENGINE §6).
"""

import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from querycure.replay.canonical import (
    canonical_json,
    canonical_raw,
    canonical_text,
    to_canonical,
)
from querycure.replay.digest import digest
from querycure.replay.events_digest import EventLogGapError, events_digest
from querycure.reports import registry
from querycure.reports.inputs import load_report_inputs

ReportReplayStatus = Literal[
    "verified", "verified_stored_only", "not_replayable", "integrity_failed", "error"
]
CheckStatus = Literal["ok", "failed", "skipped", "warning"]
SUPPORTED_MANIFEST_SCHEMAS = (1,)
PROFILES = ("qc-json-v1", "qc-text-v1", "qc-raw-v1")
NOT_REPLAYABLE = {
    "not_finalized",
    "manifest_missing",
    "artifact_purged",
    "events_purged",
    "unsupported_profile",
    "unsupported_manifest_schema",
}
INTEGRITY = {
    "manifest_digest_mismatch",
    "artifact_digest_mismatch",
    "events_gap",
    "events_digest_mismatch",
    "rebuild_mismatch",
}


@dataclass
class Check:
    name: str
    status: CheckStatus
    code: str | None = None
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "status": self.status, "code": self.code, "detail": self.detail}


@dataclass
class ReportReplayResult:
    status: ReportReplayStatus
    failure_code: str | None
    warnings: list[str]
    checks: list[Check]
    final_status: str | None = None
    outcome: str | None = None
    manifest_sha256: str | None = None
    report_json_sha256: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)

    def result_json(self) -> dict[str, Any]:
        return {
            "checks": [c.as_dict() for c in self.checks],
            "final_status": self.final_status,
            "outcome": self.outcome,
            "manifest_sha256": self.manifest_sha256,
            "report_json_sha256": self.report_json_sha256,
            **self.extras,
        }


def verified_digest(profile: str, content: bytes) -> str | None:
    """The digest of `content` if it is exactly its profile's canonical form, else None.

    Both conditions matter: re-canonicalizing catches content that is no longer valid for the
    profile, and comparing bytes catches edits that canonicalization would hide (whitespace)."""
    try:
        canonical = recanonicalize(profile, content)
    except (ValueError, UnicodeDecodeError):
        return None
    return digest(profile, content) if canonical == content else None


def recanonicalize(profile: str, content: bytes) -> bytes:
    """The stored bytes re-run through their profile (REPLAY_ENGINE §2.4)."""
    if profile == "qc-json-v1":
        return canonical_json(json.loads(content))
    if profile == "qc-text-v1":
        return canonical_text(content.decode("utf-8"))
    if profile == "qc-raw-v1":
        return canonical_raw(content)
    raise ValueError(f"unsupported profile {profile}")


def _bare(ref: str) -> str:
    return ref.removeprefix("sha256:")


def _verdict(checks: list[Check], retired: bool) -> tuple[ReportReplayStatus, str | None]:
    codes = [c.code for c in checks if c.status == "failed" and c.code]
    integrity = [c for c in codes if c in INTEGRITY]
    missing = [c for c in codes if c in NOT_REPLAYABLE]
    if integrity:
        return "integrity_failed", integrity[0]
    if missing:
        return "not_replayable", missing[0]
    return ("verified_stored_only" if retired else "verified"), None


async def _artifact(conn: AsyncConnection, sha: str) -> Any:
    return (
        await conn.execute(
            text(
                "SELECT id, sha256, canonicalization, content FROM artifacts "
                "WHERE sha256 = :sha AND deleted_at IS NULL"
            ),
            {"sha": sha},
        )
    ).first()


async def verify_report(
    conn: AsyncConnection,
    run_id: uuid.UUID,
    *,
    client_schema_versions: tuple[int, ...] | None = None,
) -> ReportReplayResult:
    checks: list[Check] = []
    warnings: list[str] = []

    def done(retired: bool = False, **kw: Any) -> ReportReplayResult:
        status, code = _verdict(checks, retired)
        return ReportReplayResult(
            status=status, failure_code=code, warnings=warnings, checks=checks, **kw
        )

    run = (
        await conn.execute(
            text(
                "SELECT status, outcome, finalized_at, events_cutoff_seq FROM investigation_runs "
                "WHERE id = :id"
            ),
            {"id": run_id},
        )
    ).one()
    if run.finalized_at is None:
        checks.append(
            Check(
                "finalized",
                "failed",
                "not_finalized",
                "the run was never finalized (earlier phases are never retro-sealed)",
            )
        )
        return done()
    checks.append(Check("finalized", "ok"))

    row = (
        await conn.execute(
            text(
                "SELECT manifest_sha256, manifest_artifact_id, events_cutoff_seq, events_digest "
                "FROM replay_manifests WHERE run_id = :id"
            ),
            {"id": run_id},
        )
    ).first()
    stored = None
    if row is not None:
        stored = (
            await conn.execute(
                text("SELECT sha256, canonicalization, content FROM artifacts WHERE id = :id"),
                {"id": row.manifest_artifact_id},
            )
        ).first()
    if row is None or stored is None:
        checks.append(Check("manifest", "failed", "manifest_missing", "no stored manifest"))
        return done()
    recomputed = verified_digest(stored.canonicalization, bytes(stored.content))
    if not (recomputed == stored.sha256 == row.manifest_sha256):
        checks.append(
            Check(
                "manifest",
                "failed",
                "manifest_digest_mismatch",
                "the manifest does not match its stored digest",
            )
        )
        return done(manifest_sha256=row.manifest_sha256)
    checks.append(Check("manifest", "ok", detail=f"sha256:{row.manifest_sha256}"))
    manifest = json.loads(bytes(stored.content))
    meta: dict[str, Any] = {
        "manifest_sha256": row.manifest_sha256,
        "final_status": manifest.get("final_status"),
        "outcome": manifest.get("outcome"),
        "report_json_sha256": _bare((manifest.get("report") or {}).get("json") or ""),
    }

    if manifest.get("schema_version") not in SUPPORTED_MANIFEST_SCHEMAS:
        checks.append(
            Check(
                "manifest_schema",
                "failed",
                "unsupported_manifest_schema",
                f"manifest schema {manifest.get('schema_version')}",
            )
        )
        return done(**meta)
    unknown = sorted({a["profile"] for a in manifest["artifacts"]} - set(PROFILES))
    if unknown:
        checks.append(
            Check(
                "manifest_schema",
                "failed",
                "unsupported_profile",
                "unknown profile " + ", ".join(unknown),
            )
        )
        return done(**meta)
    checks.append(Check("manifest_schema", "ok"))

    bad, purged = [], []
    for entry in manifest["artifacts"]:
        art = await _artifact(conn, _bare(entry["digest"]))
        if art is None:
            purged.append(entry["role"])
            continue
        again = verified_digest(entry["profile"], bytes(art.content))
        if art.canonicalization != entry["profile"] or again != _bare(entry["digest"]):
            bad.append(entry["role"])
    if purged:
        checks.append(
            Check(
                "artifacts",
                "failed",
                "artifact_purged",
                "missing: " + ", ".join(sorted(set(purged))),
            )
        )
    if bad:
        checks.append(
            Check(
                "artifacts",
                "failed",
                "artifact_digest_mismatch",
                "changed: " + ", ".join(sorted(set(bad))),
            )
        )
    if not purged and not bad:
        checks.append(Check("artifacts", "ok", detail=f"{len(manifest['artifacts'])} verified"))

    cutoff = manifest["events"]["cutoff_seq"]
    present = (
        await conn.execute(
            text("SELECT count(*) FROM investigation_events WHERE run_id = :r AND seq <= :c"),
            {"r": run_id, "c": cutoff},
        )
    ).scalar_one()
    events_ok = False
    if present == 0 and cutoff > 0:
        checks.append(Check("events", "failed", "events_purged", "no sealed events remain"))
    else:
        try:
            again = await events_digest(conn, run_id, cutoff)
            if again != manifest["events"]["digest"] or again != row.events_digest:
                checks.append(
                    Check(
                        "events", "failed", "events_digest_mismatch", f"events 1..{cutoff} changed"
                    )
                )
            else:
                events_ok = True
                checks.append(Check("events", "ok", detail=f"1..{cutoff}"))
        except EventLogGapError as exc:
            checks.append(Check("events", "failed", "events_gap", exc.message))

    report_meta = manifest["report"]
    retired = False
    builder, renderer = report_meta["builder_version"], report_meta["md_renderer_version"]
    stored_json = await _artifact(conn, _bare(report_meta["json"]))
    if builder in registry.RETIRED_BUILDERS or builder not in registry.BUILDERS:
        retired = True
        warnings.append("builder_retired")
        checks.append(Check("rebuild_json", "skipped", detail=f"{builder} retired"))
    elif not events_ok or stored_json is None:
        checks.append(Check("rebuild_json", "skipped", detail="inputs failed earlier checks"))
    else:
        final = (
            await conn.execute(
                text("SELECT finalized_at FROM investigation_runs WHERE id = :id"), {"id": run_id}
            )
        ).scalar_one()
        inputs = await load_report_inputs(conn, run_id, cutoff)
        rebuilt = registry.build(
            builder,
            inputs,
            finalized_at=to_canonical(final),
            cutoff_seq=cutoff,
            events_digest=manifest["events"]["digest"],
        )
        if digest("qc-json-v1", canonical_json(to_canonical(rebuilt))) != _bare(
            report_meta["json"]
        ):
            checks.append(
                Check(
                    "rebuild_json",
                    "failed",
                    "rebuild_mismatch",
                    f"{builder} rebuilds different JSON from the records",
                )
            )
        else:
            checks.append(Check("rebuild_json", "ok", detail=builder))
    if renderer in registry.RETIRED_RENDERERS or renderer not in registry.RENDERERS:
        retired = True
        warnings.append("md_renderer_retired")
        checks.append(Check("rebuild_markdown", "skipped", detail=f"{renderer} retired"))
    elif stored_json is None:
        checks.append(Check("rebuild_markdown", "skipped", detail="report JSON missing"))
    else:
        md = registry.RENDERERS[renderer](json.loads(bytes(stored_json.content)))
        if digest("qc-text-v1", canonical_text(md)) != _bare(report_meta["markdown"]):
            checks.append(
                Check(
                    "rebuild_markdown",
                    "failed",
                    "rebuild_mismatch",
                    f"{renderer} renders different Markdown",
                )
            )
        else:
            checks.append(Check("rebuild_markdown", "ok", detail=renderer))

    if (run.status, run.outcome) != (manifest["final_status"], manifest["outcome"]):
        warnings.append("run_row_differs_from_manifest")
    schema = report_meta["report_schema_version"]
    if client_schema_versions is not None and schema > max(client_schema_versions):
        warnings.append("schema_newer_than_client")
    return done(retired, **meta)
