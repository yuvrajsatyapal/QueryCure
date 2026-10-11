"""SSE / event-log types (API_DESIGN §3). Adding a type: update that table and the frontend."""

from enum import StrEnum


class EventType(StrEnum):
    RUN_STATUS_CHANGED = "run.status_changed"
    NODE_STARTED = "node.started"
    NODE_COMPLETED = "node.completed"
    AGENT_SUMMARY = "agent.summary"
    TOOL_STARTED = "tool.started"
    TOOL_COMPLETED = "tool.completed"
    EVIDENCE_CREATED = "evidence.created"
    FINDING_CREATED = "finding.created"
    HYPOTHESIS_CREATED = "hypothesis.created"
    HYPOTHESIS_UPDATED = "hypothesis.updated"
    CANDIDATE_CREATED = "candidate.created"
    APPROVAL_REQUESTED = "approval.requested"
    APPROVAL_DECIDED = "approval.decided"
    BENCHMARK_PROGRESS = "benchmark.progress"
    VERIFICATION_COMPLETED = "verification.completed"
    BUDGET_WARNING = "budget.warning"
    ERROR = "error"
    REPORT_READY = "report.ready"
    REPLAY_STATUS_CHANGED = "replay.status_changed"
    REPLAY_COMPARED = "replay.compared"


# The only types a finalized run may still append (outside the events digest).
LIFECYCLE_TYPES = frozenset({EventType.REPORT_READY, EventType.RUN_STATUS_CHANGED})

NOTIFY_CHANNEL = "qc_run_events"
