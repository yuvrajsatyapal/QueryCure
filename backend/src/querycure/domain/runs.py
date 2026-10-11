from enum import StrEnum


class ExecutionMode(StrEnum):
    OFFLINE = "offline"
    LIVE_INSPECTION = "live_inspection"
    SANDBOX_BENCHMARK = "sandbox_benchmark"


class RunKind(StrEnum):
    INITIAL = "initial"
    REINVESTIGATION = "reinvestigation"
    EXPERIMENT_REPLAY = "experiment_replay"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    CANCELLING = "cancelling"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RunOutcome(StrEnum):
    VERIFIED_RECOMMENDATION = "verified_recommendation"
    UNVERIFIED_RECOMMENDATIONS = "unverified_recommendations"
    NO_ACTION_NEEDED = "no_action_needed"
    INCONCLUSIVE = "inconclusive"


TERMINAL_STATUSES = frozenset({RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED})
ACTIVE_STATUSES = frozenset(
    {RunStatus.QUEUED, RunStatus.RUNNING, RunStatus.AWAITING_APPROVAL, RunStatus.CANCELLING}
)

# AGENT_SYSTEM §9. The only place run transitions are defined; transition_run() enforces it.
ALLOWED_TRANSITIONS: dict[RunStatus, frozenset[RunStatus]] = {
    # queued -> failed: the job was dead-lettered before the run could start (worker crashes
    # exhausted its attempts). Not in the original AGENT_SYSTEM §9 diagram; documented there.
    RunStatus.QUEUED: frozenset({RunStatus.RUNNING, RunStatus.CANCELLED, RunStatus.FAILED}),
    RunStatus.RUNNING: frozenset(
        {
            RunStatus.AWAITING_APPROVAL,
            RunStatus.COMPLETED,
            RunStatus.FAILED,
            RunStatus.CANCELLING,
            RunStatus.QUEUED,  # lease expired and the job was reclaimed
        }
    ),
    RunStatus.AWAITING_APPROVAL: frozenset(
        {RunStatus.QUEUED, RunStatus.COMPLETED, RunStatus.CANCELLED}
    ),
    RunStatus.CANCELLING: frozenset({RunStatus.CANCELLED}),
    RunStatus.COMPLETED: frozenset(),
    RunStatus.FAILED: frozenset(),
    RunStatus.CANCELLED: frozenset(),
}


def sources_for(target: RunStatus) -> frozenset[RunStatus]:
    return frozenset(src for src, targets in ALLOWED_TRANSITIONS.items() if target in targets)
