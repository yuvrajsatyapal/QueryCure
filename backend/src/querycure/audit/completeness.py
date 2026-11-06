"""Audit completeness: a verified result is only as good as its audit (pure, no I/O).

The engine verdict `verified` is not a recommendation until the Benchmark Auditor's
deterministic checks have run and been recorded (ADR-0009). If the auditor never ran (the run's
budget expired, it was cancelled), the candidate must not be reported as verified.

A candidate is audited only by a `verification_results` row for *its* experiment, *its*
candidate id, key and round. Anything looser could let another round's or another candidate's
audit vouch for it, so a missing or ambiguous match counts as unaudited (fail closed).
"""

import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from querycure.domain.audit import VERIFIED_VERDICTS
from querycure.domain.investigation import NodeError
from querycure.domain.optimization import CandidateStatus, OptimizationCandidate

UNAUDITED_CODE = "AUDIT_NOT_COMPLETED"
# Its own reason code: `audit_downgrade` renders as "the Benchmark Auditor found a reason to
# doubt the result", which would claim an audit that never ran.
UNAUDITED_REASON = "audit_not_completed"
REPORT_NODE = "write_report"
MAX_KEYS_IN_MESSAGE = 8
MAX_MESSAGE = 500


class VerificationKey(Protocol):
    """The columns of a verification_results row that identify what it audited."""

    @property
    def experiment_id(self) -> uuid.UUID: ...
    @property
    def candidate_id(self) -> uuid.UUID: ...
    @property
    def candidate_key(self) -> str: ...
    @property
    def round(self) -> int: ...


@dataclass(frozen=True)
class UnauditedCandidate:
    id: uuid.UUID | None
    key: str
    round: int
    status: CandidateStatus


def _audits(
    row: VerificationKey, candidate: OptimizationCandidate, experiment_id: uuid.UUID
) -> bool:
    return (
        candidate.id is not None
        and row.experiment_id == experiment_id
        and row.candidate_id == candidate.id
        and row.candidate_key == candidate.key
        and row.round == candidate.round
    )


def unaudited_candidates(
    candidates: Sequence[OptimizationCandidate],
    verifications: Sequence[VerificationKey],
    *,
    experiment_id_for: Callable[[int], uuid.UUID],
) -> list[UnauditedCandidate]:
    """Candidates currently verified (or verified with a noise warning) with no audit row."""
    out: list[UnauditedCandidate] = []
    for c in candidates:
        if c.status not in VERIFIED_VERDICTS:
            continue
        experiment_id = experiment_id_for(c.round)
        if any(_audits(v, c, experiment_id) for v in verifications):
            continue
        out.append(UnauditedCandidate(id=c.id, key=c.key, round=c.round, status=c.status))
    return out


def audited_winner(
    winner: str | None,
    candidates: Sequence[OptimizationCandidate],
    unaudited: Sequence[UnauditedCandidate],
) -> str | None:
    """The run's winner only if its candidate is audited and still verified in the records.

    The state can be stale in two ways, and both must read as "no winner": the auditor never
    ran (the candidate is unaudited), or it ran and downgraded the candidate but the run
    stopped before the node returned its updated winner (the record says inconclusive).
    """
    if winner is None or any(u.key == winner for u in unaudited):
        return None
    if any(c.key == winner and c.status in VERIFIED_VERDICTS for c in candidates):
        return winner
    return None


def unaudited_reasons(item: UnauditedCandidate, stop_reason: str | None) -> list[dict[str, str]]:
    stop = f" (stop reason: {stop_reason})" if stop_reason else ""
    return [
        {
            "code": UNAUDITED_REASON,
            "detail": (
                f"Unaudited: the engine verdict `{item.status}` was not audited{stop}; the "
                "required Benchmark Auditor checks did not run, so it is not reported as verified."
            ),
        }
    ]


def audit_incomplete_error(
    unaudited: Sequence[UnauditedCandidate], stop_reason: str | None
) -> NodeError:
    keys = [u.key for u in unaudited]
    shown = ", ".join(keys[:MAX_KEYS_IN_MESSAGE])
    more = f" and {len(keys) - MAX_KEYS_IN_MESSAGE} more" if len(keys) > MAX_KEYS_IN_MESSAGE else ""
    stop = f" (stop reason: {stop_reason})" if stop_reason else ""
    noun = "result was" if len(keys) == 1 else "results were"
    message = (
        f"{len(keys)} verified {noun} not audited and "
        f"{'is' if len(keys) == 1 else 'are'} not reported as verified: {shown}{more}{stop}."
    )
    return NodeError(
        node=REPORT_NODE, code=UNAUDITED_CODE, message=message[:MAX_MESSAGE], recoverable=False
    )
