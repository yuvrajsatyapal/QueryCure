"""Reports, manifests, replay attempts and plan diffs (API_DESIGN §2 Phase 4)."""

import datetime as dt
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from querycure.plans.diff import PlanDiff


class ReportOut(BaseModel):
    """The stored, digest-verified report JSON plus its version axes (REPLAY_ENGINE §7)."""

    run_id: uuid.UUID
    final_status: str
    outcome: str | None
    report_schema_version: int
    builder_version: str
    md_renderer_version: str
    report_json_sha256: str
    report_md_sha256: str
    manifest_sha256: str
    report: dict[str, Any]


class ManifestOut(BaseModel):
    run_id: uuid.UUID
    manifest_sha256: str
    manifest: dict[str, Any]


class ReplayAttemptOut(BaseModel):
    id: uuid.UUID
    kind: Literal["report", "experiment"]
    status: str
    failure_code: str | None
    warnings: list[str]
    result: dict[str, Any]
    source_run_id: uuid.UUID
    source_experiment_id: uuid.UUID | None
    replay_run_id: uuid.UUID | None
    replay_experiment_id: uuid.UUID | None
    approval_request_id: uuid.UUID | None
    started_at: dt.datetime
    finished_at: dt.datetime | None
    created_at: dt.datetime


class ReplayAttemptPage(BaseModel):
    items: list[ReplayAttemptOut]
    next_cursor: str | None


class ReportReplayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Report schema versions the caller can render (REPLAY_ENGINE §7 rule 4).
    client_schema_versions: list[int] | None = Field(default=None, max_length=20)


class ExperimentReplayRequest(BaseModel):
    """`confirm_ddl` is the human confirmation of the exact SQL shown in the dialog: it
    creates the sandbox approval for the replay run (AGENT_SYSTEM §8)."""

    model_config = ConfigDict(extra="forbid")

    confirm_ddl: Literal[True]


class PlanDiffOut(BaseModel):
    run_id: uuid.UUID
    from_sha256: str
    to_sha256: str
    diff: PlanDiff


class VerificationOut(BaseModel):
    """One audited verdict (verification_results): the engine verdict, the audited verdict
    (equal, or inconclusive after a downgrade), the deterministic checks and the review."""

    experiment_id: uuid.UUID
    candidate_id: uuid.UUID
    candidate_key: str
    round: int
    engine_verdict: str
    verdict: str
    reasons: list[dict[str, Any]]
    checks: list[dict[str, Any]]
    auditor_status: str
    auditor_notes: str | None
    auditor_concerns: list[dict[str, Any]]
    auditor_prompt_version: str | None
    auditor_downgraded: bool


class VerificationList(BaseModel):
    items: list[VerificationOut]
