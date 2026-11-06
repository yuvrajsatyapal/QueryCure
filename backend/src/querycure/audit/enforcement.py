"""Audit-completeness enforcement on the records (database access, one caller's transaction).

The matching rules live in `audit.completeness` (pure). This applies them: a candidate the
engine called verified whose Benchmark Auditor checks never ran is downgraded before the run is
sealed. Every path that seals a run after an experiment can have run calls it, inside the
transaction that seals: `write_report` (the graph's terminal node) and `fail_run` (a run failed
outside the graph).
"""

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncConnection

from querycure.agents.nodes.run_experiment import experiment_id_for
from querycure.audit.completeness import (
    UnauditedCandidate,
    audit_incomplete_error,
    audited_winner,
    unaudited_candidates,
    unaudited_reasons,
)
from querycure.core.logging import get_logger
from querycure.db.repositories.optimization import list_candidates, set_candidate_status
from querycure.db.repositories.verification import list_verifications
from querycure.domain.optimization import OptimizationCandidate
from querycure.events.emitter import emit
from querycure.events.types import EventType

log = get_logger(__name__)


@dataclass(frozen=True)
class AuditCheck:
    """What the records say about the audit, as of when enforcement looked."""

    unaudited: list[UnauditedCandidate]
    candidates: list[OptimizationCandidate]

    def winner(self, state_winner: str | None) -> str | None:
        """The state's winner, only if its candidate was audited and is still verified."""
        return audited_winner(state_winner, self.candidates, self.unaudited)


async def enforce_audit_completeness(
    conn: AsyncConnection, run_id: uuid.UUID, stop_reason: str | None
) -> AuditCheck:
    """A verified candidate without its audit is downgraded to inconclusive.

    `run_experiment` records the engine verdict as the candidate's status before the Benchmark
    Auditor runs. If the auditor was skipped (budget expired, cancelled) or crashed, nothing
    downgraded it, and the report would present an unaudited engine verdict as a verified
    recommendation.

    Idempotent: a downgraded candidate is no longer verified, so a second call finds nothing
    and writes nothing. The caller runs it inside the transaction that seals the run, holding
    the run-row lock, so the downgrade, its error event and the seal commit together or not at
    all. No `verification_results` row is written (it would claim checks ran) and
    `verification.completed` is not emitted (no verification completed): the candidate's status
    and reason, and one `error` event, carry the message.
    """
    candidates = await list_candidates(conn, run_id)
    verifications = await list_verifications(conn, run_id)
    unaudited = unaudited_candidates(
        candidates, verifications, experiment_id_for=lambda round: experiment_id_for(run_id, round)
    )
    if unaudited:
        for item in unaudited:
            await set_candidate_status(
                conn,
                run_id,
                [item.id] if item.id is not None else [],
                "inconclusive",
                reasons=unaudited_reasons(item, stop_reason),
            )
        error = audit_incomplete_error(unaudited, stop_reason)
        await emit(conn, run_id, EventType.ERROR, error.model_dump())
        log.warning(
            "audit_incomplete_candidates_downgraded",
            run_id=str(run_id),
            count=len(unaudited),
            stop_reason=stop_reason,
        )
    return AuditCheck(unaudited=unaudited, candidates=candidates)
