"""Source snapshot of an experiment replay (REPLAY_OUTCOME_AUDIT §12.4, §13).

The facts a replay may confirm about its source run: kind, terminal status and outcome, the
recommendation with its measured experiment, and the digests that bind them. They are read
only from the source's sealed manifest and report JSON, after report replay verified both.

Storage: no copy. `start_replay` links the source's own manifest and report JSON artifacts to
the replay run (roles below), in the transaction that creates the run. Content-addressed and
digest-checked on every read, they are listed in the replay's manifest when it is sealed, so
the snapshot is a pure function of sealed records and later changes to the source run (row,
outcome, deletion) cannot reach it. A new artifact kind would need a migration
(`artifacts_kind_check`), and copying the facts would be a second source of truth.
"""

import copy
import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from querycure.domain.runs import TERMINAL_STATUSES, RunKind, RunOutcome
from querycure.replay.artifact_store import (
    ArtifactIntegrityError,
    StoredArtifact,
    get_artifact,
    link,
)

SNAPSHOT_SCHEMA_VERSION = 1
ROLE_MANIFEST = "input.replay_source.manifest"
ROLE_REPORT_JSON = "input.replay_source.report_json"
ROLE_CONFIG = "input.experiment_config"
KINDS = {
    ROLE_MANIFEST: "replay_manifest",
    ROLE_REPORT_JSON: "report_json",
    ROLE_CONFIG: "experiment_config",
}
SUPPORTED_SOURCE_MANIFESTS = (1,)
RECOMMENDATION_KEYS = (
    "status",
    "candidate_key",
    "kind",
    "ddl",
    "query_sql",
    "primary_measurement",
    "scope",
)
VERIFIED = ("verified", "verified_with_noise_warning")
NODE = "experiment_replay"


class SourceSnapshotError(Exception):
    """The source's sealed records are missing, inconsistent or unverifiable. Callers map it
    to the existing `source_integrity_failed` code (D6)."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class SourceRecommendation(BaseModel):
    """The source report's `recommendation`, verbatim (`report-builder@1` shape)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: str
    candidate_key: str | None
    kind: str | None
    ddl: list[str]
    query_sql: str | None
    primary_measurement: dict[str, Any] | None
    scope: str

    @property
    def measured_result_sha256(self) -> str | None:
        """Digest of the experiment result the recommendation's measurement was read from."""
        source = (self.primary_measurement or {}).get("source")
        sha = source.get("artifact_sha256") if isinstance(source, dict) else None
        return sha if isinstance(sha, str) and sha else None


class ReplaySourceSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1]
    source_run_id: str
    source_run_kind: RunKind
    source_experiment_id: str
    source_experiment_result_sha256: str
    source_experiment_environment_digest: str | None
    source_manifest_sha256: str
    source_report_json_sha256: str
    source_builder_version: str
    source_final_status: str
    source_outcome: RunOutcome | None
    source_recommendation: SourceRecommendation | None


def _bare(ref: Any) -> str | None:
    return ref.removeprefix("sha256:") if isinstance(ref, str) and ref else None


def snapshot_from_sealed(
    *,
    manifest: dict[str, Any],
    report: dict[str, Any],
    manifest_sha256: str,
    report_json_sha256: str,
    source_run_id: str,
    source_experiment_id: str,
    source_experiment_result_sha256: str,
    source_arms: Sequence[str],
) -> ReplaySourceSnapshot:
    """The snapshot of a source run from its sealed manifest and report JSON. Pure; every
    inconsistency between the two, or with the replayed experiment, is a SourceSnapshotError."""
    manifest, report = copy.deepcopy(manifest), copy.deepcopy(report)
    if manifest.get("schema_version") not in SUPPORTED_SOURCE_MANIFESTS:
        raise SourceSnapshotError(f"source manifest schema {manifest.get('schema_version')}")
    if manifest.get("run_id") != source_run_id or (report.get("run") or {}).get("id") != (
        source_run_id
    ):
        raise SourceSnapshotError("source manifest or report belongs to another run")
    if _bare((manifest.get("report") or {}).get("json")) != report_json_sha256:
        raise SourceSnapshotError("source manifest names another report")
    for key in ("final_status", "outcome"):
        if manifest.get(key) != report.get(key):
            raise SourceSnapshotError(f"source {key} differs between manifest and report")
    if manifest.get("final_status") not in {s.value for s in TERMINAL_STATUSES}:
        raise SourceSnapshotError(f"source final status {manifest.get('final_status')}")
    entry = next(
        (e for e in manifest.get("experiments") or [] if e.get("id") == source_experiment_id),
        None,
    )
    if entry is None or _bare(entry.get("result")) != source_experiment_result_sha256:
        raise SourceSnapshotError("source experiment result is not the one sealed")
    rec = report.get("recommendation")
    if not isinstance(rec, dict) or any(k not in rec for k in RECOMMENDATION_KEYS):
        raise SourceSnapshotError("source report unreadable: no recommendation")
    try:
        snapshot = ReplaySourceSnapshot.model_validate(
            {
                "schema_version": SNAPSHOT_SCHEMA_VERSION,
                "source_run_id": source_run_id,
                "source_run_kind": manifest.get("run_kind"),
                "source_experiment_id": source_experiment_id,
                "source_experiment_result_sha256": source_experiment_result_sha256,
                "source_experiment_environment_digest": entry.get("environment"),
                "source_manifest_sha256": manifest_sha256,
                "source_report_json_sha256": report_json_sha256,
                "source_builder_version": (manifest.get("report") or {}).get("builder_version"),
                "source_final_status": manifest.get("final_status"),
                "source_outcome": manifest.get("outcome"),
                "source_recommendation": {k: rec[k] for k in RECOMMENDATION_KEYS},
            }
        )
    except ValidationError as exc:
        raise SourceSnapshotError(f"source report unreadable: {exc.errors()[0]['loc']}") from exc
    if (
        snapshot.source_run_kind is not RunKind.EXPERIMENT_REPLAY
        and snapshot.source_outcome is RunOutcome.VERIFIED_RECOMMENDATION
    ):
        _check_recommendation(snapshot, manifest, source_arms)
    return snapshot


def _check_recommendation(
    snapshot: ReplaySourceSnapshot, manifest: dict[str, Any], source_arms: Sequence[str]
) -> None:
    """An investigation that sealed a verified recommendation must name the candidate and
    the sealed experiment result its measurement came from."""
    rec = snapshot.source_recommendation
    measured = None if rec is None else rec.measured_result_sha256
    if rec is None or rec.status not in VERIFIED or rec.candidate_key is None or measured is None:
        raise SourceSnapshotError("source recommendation evidence is missing")
    sealed = {_bare(e.get("result")) for e in manifest.get("experiments") or []}
    if measured not in sealed:
        raise SourceSnapshotError("source recommendation cites an unsealed experiment result")
    if measured == snapshot.source_experiment_result_sha256 and rec.candidate_key not in (
        source_arms
    ):
        raise SourceSnapshotError("source recommendation is not an arm of this experiment")


@dataclass(frozen=True)
class CapturedSnapshot:
    snapshot: ReplaySourceSnapshot
    manifest_artifact_id: uuid.UUID
    report_artifact_id: uuid.UUID


async def _verified(conn: AsyncConnection, sha: str | None, role: str) -> StoredArtifact:
    """The artifact with this digest, re-verified by `get_artifact`, of the role's kind."""
    what = role.rsplit(".", 1)[-1]
    try:
        artifact = None if sha is None else await get_artifact(conn, sha)
    except ArtifactIntegrityError as exc:
        raise SourceSnapshotError(f"source {what} does not match its digest") from exc
    if artifact is None or artifact.canonicalization != "qc-json-v1":
        raise SourceSnapshotError(f"source {what} is missing")
    if artifact.kind != KINDS[role]:
        raise SourceSnapshotError(f"source {what} is a {artifact.kind} artifact")
    return artifact


async def capture_source_snapshot(
    conn: AsyncConnection,
    *,
    source_run_id: uuid.UUID,
    source_experiment_id: uuid.UUID,
    manifest_sha256: str | None,
    report_json_sha256: str | None,
    source_experiment_result_sha256: str,
    source_arms: Sequence[str],
) -> CapturedSnapshot:
    """Snapshot of a source whose report replay just passed, from the digests it verified.
    `get_artifact` re-checks each digest, so the bytes read are the bytes verified."""
    manifest_art = await _verified(conn, manifest_sha256, ROLE_MANIFEST)
    report_art = await _verified(conn, report_json_sha256, ROLE_REPORT_JSON)
    snapshot = snapshot_from_sealed(
        manifest=json.loads(manifest_art.content),
        report=json.loads(report_art.content),
        manifest_sha256=manifest_art.sha256,
        report_json_sha256=report_art.sha256,
        source_run_id=str(source_run_id),
        source_experiment_id=str(source_experiment_id),
        source_experiment_result_sha256=source_experiment_result_sha256,
        source_arms=source_arms,
    )
    return CapturedSnapshot(snapshot, manifest_art.id, report_art.id)


async def link_source_snapshot(
    conn: AsyncConnection, replay_run_id: uuid.UUID, captured: CapturedSnapshot
) -> None:
    for artifact_id, role in (
        (captured.manifest_artifact_id, ROLE_MANIFEST),
        (captured.report_artifact_id, ROLE_REPORT_JSON),
    ):
        await link(conn, run_id=replay_run_id, artifact_id=artifact_id, role=role, produced_by=NODE)


async def _linked(conn: AsyncConnection, run_id: uuid.UUID, role: str) -> list[str]:
    rows = await conn.execute(
        text(
            "SELECT a.sha256 FROM run_artifacts ra JOIN artifacts a ON a.id = ra.artifact_id "
            "WHERE ra.run_id = :run AND ra.role = :role ORDER BY a.sha256"
        ),
        {"run": run_id, "role": role},
    )
    return [r.sha256 for r in rows]


async def _sealed_links(conn: AsyncConnection, run_id: uuid.UUID) -> dict[str, list[str]]:
    """The snapshot roles listed in a finalized run's own sealed manifest. That manifest is the
    authoritative record of what the run linked when it was sealed (REPLAY_ENGINE §5)."""
    sha = (
        await conn.execute(
            text("SELECT manifest_sha256 FROM replay_manifests WHERE run_id = :id"),
            {"id": run_id},
        )
    ).scalar_one_or_none()
    try:
        stored = None if sha is None else await get_artifact(conn, sha)
    except ArtifactIntegrityError as exc:
        raise SourceSnapshotError("replay manifest does not match its digest") from exc
    if stored is None or stored.kind != "replay_manifest":
        raise SourceSnapshotError("replay run is sealed without a manifest")
    listed = json.loads(stored.content).get("artifacts") or []
    return {
        role: sorted(_bare(a.get("digest")) or "" for a in listed if a.get("role") == role)
        for role in (ROLE_MANIFEST, ROLE_REPORT_JSON)
    }


async def load_source_snapshot(
    conn: AsyncConnection, replay_run_id: uuid.UUID
) -> ReplaySourceSnapshot | None:
    """The snapshot of a replay run, rebuilt from its own records only: the source manifest
    and report JSON (roles above), its `input.experiment_config` (the source experiment's
    config) and its `parent_run_id`; the source run's rows are never read.

    None means the replay has no snapshot because it predates snapshots (or is not a replay).
    For a sealed replay that is decided by its own sealed manifest, not by the links: a manifest
    listing the snapshot roles makes missing or different links an error. An unsealed replay
    has only its links, which the start transaction writes atomically and the app role can
    neither change nor delete. Anything inconsistent raises SourceSnapshotError."""
    run = (
        await conn.execute(
            text("SELECT kind, parent_run_id, finalized_at FROM investigation_runs WHERE id = :id"),
            {"id": replay_run_id},
        )
    ).one_or_none()
    linked = {
        role: await _linked(conn, replay_run_id, role) for role in (ROLE_MANIFEST, ROLE_REPORT_JSON)
    }
    manifests, reports = linked[ROLE_MANIFEST], linked[ROLE_REPORT_JSON]
    if run is None or run.kind != RunKind.EXPERIMENT_REPLAY.value or run.parent_run_id is None:
        if manifests or reports:
            raise SourceSnapshotError("source snapshot linked to a run that is not a replay")
        return None
    if run.finalized_at is not None and await _sealed_links(conn, replay_run_id) != linked:
        raise SourceSnapshotError("replay links differ from its sealed manifest")
    if not manifests and not reports:
        return None
    configs = await _linked(conn, replay_run_id, ROLE_CONFIG)
    if len(manifests) != 1 or len(reports) != 1 or len(configs) != 1:
        raise SourceSnapshotError("replay run has an incomplete source snapshot")
    manifest = json.loads((await _verified(conn, manifests[0], ROLE_MANIFEST)).content)
    config = json.loads((await _verified(conn, configs[0], ROLE_CONFIG)).content)
    experiment_id = config.get("experiment_id")
    entry = next(
        (e for e in manifest.get("experiments") or [] if e.get("id") == experiment_id), None
    )
    result_sha = None if entry is None else _bare(entry.get("result"))
    if result_sha is None:
        raise SourceSnapshotError("source experiment result is not the one sealed")
    return snapshot_from_sealed(
        manifest=manifest,
        report=json.loads((await _verified(conn, reports[0], ROLE_REPORT_JSON)).content),
        manifest_sha256=manifests[0],
        report_json_sha256=reports[0],
        source_run_id=str(run.parent_run_id),
        source_experiment_id=experiment_id,
        source_experiment_result_sha256=result_sha,
        source_arms=[c.get("arm") for c in config.get("candidates") or []],
    )
