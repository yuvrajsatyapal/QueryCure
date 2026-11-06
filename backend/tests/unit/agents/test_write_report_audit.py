"""write_report enforces the audit-completeness invariant (orchestration, no database).

The repository helpers are replaced by an in-memory store with transaction semantics: in
strict mode a write outside `engine.begin()` fails the test, and an exception leaving the block
rolls every write back. So these tests pin what the node reads, writes and emits, that all of it
happens inside the one transaction that seals the run, and that a retry never repeats it.

The same behaviour against a real database is in `tests/integration/test_write_report_gate.py`
(rollback through the `finalize_run` fault seam) and `tests/integration/test_unaudited_winner.py`
(the whole graph).
"""

import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from querycure.agents.nodes import write_report as module
from querycure.agents.nodes.run_experiment import experiment_id_for
from querycure.audit import enforcement
from querycure.audit.completeness import (
    UnauditedCandidate,
    audit_incomplete_error,
    unaudited_reasons,
)
from querycure.domain.optimization import CandidateStatus, OptimizationCandidate
from querycure.domain.runs import RunOutcome, RunStatus
from querycure.events.types import EventType
from tests.unit.agents.fakes import FakeEvents
from tests.unit.audit.test_completeness import KEY_A, KEY_B, RUN, Row, candidate

RUN_ID = RUN


def audited_row(c: OptimizationCandidate, status: str = "completed") -> Row:
    return Row(
        experiment_id=experiment_id_for(RUN_ID, c.round),
        candidate_id=c.id,  # type: ignore[arg-type]
        candidate_key=c.key,
        round=c.round,
        auditor_status=status,
    )


def unaudited(c: OptimizationCandidate) -> UnauditedCandidate:
    return UnauditedCandidate(id=c.id, key=c.key, round=c.round, status=c.status)


class Boom(RuntimeError):
    pass


class Store:
    """Candidates, verification rows, events and the run row, with commit/rollback."""

    def __init__(
        self, candidates: list[OptimizationCandidate], rows: list[Row], *, strict: bool = False
    ) -> None:
        self.candidates = candidates
        self.rows = rows
        self.strict = strict
        self.in_txn = False
        self.status_calls: list[tuple[list[uuid.UUID], str, list[dict[str, str]] | None]] = []
        self.events: list[tuple[EventType, dict[str, Any]]] = []
        self.sealed: list[Any] = []
        self.run = SimpleNamespace(status="running", outcome=None, finalized_at=None)
        self.fail_finalize = False
        self._snapshot: tuple[Any, ...] | None = None

    # transaction ---------------------------------------------------------------------------

    def begin(self) -> None:
        assert not self.in_txn, "nested transaction"
        self._snapshot = (
            list(self.candidates),
            list(self.status_calls),
            list(self.events),
            list(self.sealed),
            SimpleNamespace(**vars(self.run)),
        )
        self.in_txn = True

    def end(self, failed: bool) -> None:
        self.in_txn = False
        if failed:
            assert self._snapshot is not None
            self.candidates, self.status_calls, self.events, self.sealed, self.run = self._snapshot

    def _writing(self) -> None:
        if self.strict:
            assert self.in_txn, "a write happened outside the sealing transaction"

    # repository stand-ins ------------------------------------------------------------------

    async def list_candidates(self, conn: object, run_id: uuid.UUID, **_: object) -> Any:
        assert run_id == RUN_ID
        return list(self.candidates)

    async def list_verifications(self, conn: object, run_id: uuid.UUID, **_: object) -> Any:
        assert run_id == RUN_ID
        return list(self.rows)

    async def set_candidate_status(
        self,
        conn: object,
        run_id: uuid.UUID,
        ids: list[uuid.UUID],
        status: str,
        *,
        reasons: list[dict[str, str]] | None = None,
    ) -> None:
        self._writing()
        self.status_calls.append((list(ids), status, reasons))
        self.candidates = [
            c.model_copy(update={"status": status, "verdict_reasons": reasons})
            if c.id in ids
            else c
            for c in self.candidates
        ]

    async def emit(
        self, conn: object, run_id: uuid.UUID, type: EventType, payload: dict[str, Any]
    ) -> int:
        self._writing()
        self.events.append((type, payload))
        return len(self.events)

    async def finalize_run(self, conn: object, run_id: uuid.UUID, conclusion: Any) -> None:
        self._writing()
        if self.fail_finalize:
            raise Boom("finalize_run failed after the downgrade")
        self.sealed.append(conclusion)
        self.run = SimpleNamespace(
            status=conclusion.final_status.value,
            outcome=conclusion.outcome.value if conclusion.outcome else None,
            finalized_at="sealed",
        )


class _Result:
    def __init__(self, run: Any) -> None:
        self._run = run

    def one(self) -> Any:
        return self._run


class _Conn:
    def __init__(self, store: Store) -> None:
        self._store = store

    async def execute(self, *_: object, **__: object) -> _Result:
        return _Result(self._store.run)


class _Begin:
    def __init__(self, store: Store) -> None:
        self._store = store

    async def __aenter__(self) -> _Conn:
        self._store.begin()
        return _Conn(self._store)

    async def __aexit__(self, exc_type: object, *_: object) -> None:
        self._store.end(failed=exc_type is not None)


class _Engine:
    def __init__(self, store: Store) -> None:
        self._store = store

    def begin(self) -> _Begin:
        return _Begin(self._store)


@pytest.fixture
def install(monkeypatch: pytest.MonkeyPatch) -> Any:
    def go(store: Store) -> Store:
        monkeypatch.setattr(enforcement, "list_candidates", store.list_candidates)
        monkeypatch.setattr(enforcement, "list_verifications", store.list_verifications)
        monkeypatch.setattr(enforcement, "set_candidate_status", store.set_candidate_status)
        monkeypatch.setattr(enforcement, "emit", store.emit)
        return store

    return go


# --- enforce_audit_completeness -------------------------------------------------------------


async def test_unaudited_verified_candidate_is_downgraded_with_one_error_event(
    install: Any,
) -> None:
    c = candidate()
    store = install(Store([c], []))

    check = await enforcement.enforce_audit_completeness(object(), RUN_ID, "budget_exhausted")  # type: ignore[arg-type]

    assert check.unaudited == [unaudited(c)]
    assert store.status_calls == [
        ([c.id], "inconclusive", unaudited_reasons(unaudited(c), "budget_exhausted"))
    ]
    # An `error` event, not verification.completed: no verification (audit) completed.
    assert store.events == [
        (EventType.ERROR, audit_incomplete_error([unaudited(c)], "budget_exhausted").model_dump())
    ]
    assert store.candidates[0].status == "inconclusive"


async def test_running_it_twice_changes_nothing_the_second_time(install: Any) -> None:
    c = candidate()
    store = install(Store([c], []))

    first = await enforcement.enforce_audit_completeness(object(), RUN_ID, "budget_exhausted")  # type: ignore[arg-type]
    second = await enforcement.enforce_audit_completeness(object(), RUN_ID, "budget_exhausted")  # type: ignore[arg-type]

    assert first.unaudited == [unaudited(c)]
    assert second.unaudited == []
    assert len(store.status_calls) == 1
    assert len(store.events) == 1


async def test_several_unaudited_candidates_get_their_own_status_and_share_one_event(
    install: Any,
) -> None:
    a = candidate(KEY_A)
    b = candidate(KEY_B, status="verified_with_noise_warning")
    store = install(Store([a, b], []))

    check = await enforcement.enforce_audit_completeness(object(), RUN_ID, None)  # type: ignore[arg-type]

    assert check.unaudited == [unaudited(a), unaudited(b)]
    assert store.status_calls == [
        ([a.id], "inconclusive", unaudited_reasons(unaudited(a), None)),
        ([b.id], "inconclusive", unaudited_reasons(unaudited(b), None)),
    ]
    assert store.events == [
        (EventType.ERROR, audit_incomplete_error([unaudited(a), unaudited(b)], None).model_dump())
    ]


@pytest.mark.parametrize("auditor_status", ["completed", "deterministic_only"])
async def test_an_audited_result_is_left_exactly_as_it_was(
    install: Any, auditor_status: str
) -> None:
    # deterministic_only = the audit ran and only the LLM narrative was skipped.
    c = candidate()
    store = install(Store([c], [audited_row(c, auditor_status)]))

    check = await enforcement.enforce_audit_completeness(object(), RUN_ID, "budget_exhausted")  # type: ignore[arg-type]

    assert check.unaudited == []
    assert store.status_calls == []
    assert store.events == []
    assert store.candidates == [c]


async def test_only_the_missing_audit_is_touched(install: Any) -> None:
    done, missing = candidate(KEY_A), candidate(KEY_B)
    store = install(Store([done, missing], [audited_row(done)]))

    check = await enforcement.enforce_audit_completeness(object(), RUN_ID, "budget_exhausted")  # type: ignore[arg-type]

    assert check.unaudited == [unaudited(missing)]
    assert store.status_calls == [
        ([missing.id], "inconclusive", unaudited_reasons(unaudited(missing), "budget_exhausted"))
    ]
    assert {c.key: c.status for c in store.candidates} == {KEY_A: "verified", KEY_B: "inconclusive"}


# --- the outcome the run ends with ----------------------------------------------------------


def outcome(winner: str | None, stop_reason: str | None) -> tuple[RunStatus, RunOutcome | None]:
    return module.decide(
        current=RunStatus.RUNNING,
        stop_reason=stop_reason,
        has_hypotheses=True,
        has_no_action_evidence=False,
        winner=winner,
        approval_status="approved",
        benchmarked=True,
    )


@pytest.mark.parametrize("status", ["verified", "verified_with_noise_warning"])
async def test_unaudited_winner_with_budget_exhausted_is_not_a_verified_recommendation(
    install: Any, status: CandidateStatus
) -> None:
    c = candidate(status=status)
    install(Store([c], []))
    check = await enforcement.enforce_audit_completeness(object(), RUN_ID, "budget_exhausted")  # type: ignore[arg-type]

    winner = check.winner(c.key)

    assert winner is None
    assert outcome(winner, "budget_exhausted") == (RunStatus.COMPLETED, RunOutcome.INCONCLUSIVE)


@pytest.mark.parametrize("status", ["verified", "verified_with_noise_warning"])
async def test_audited_winner_keeps_verified_recommendation_even_if_the_budget_ran_out_after(
    install: Any, status: CandidateStatus
) -> None:
    # Existing behaviour, preserved: the audit finished; only later work was cut short.
    c = candidate(status=status)
    install(Store([c], [audited_row(c, "deterministic_only")]))
    check = await enforcement.enforce_audit_completeness(object(), RUN_ID, "budget_exhausted")  # type: ignore[arg-type]

    winner = check.winner(c.key)

    assert winner == c.key
    verified = (RunStatus.COMPLETED, RunOutcome.VERIFIED_RECOMMENDATION)
    assert outcome(winner, "budget_exhausted") == verified
    assert outcome(winner, None) == verified


async def test_winner_the_audit_downgraded_is_not_reported_as_verified(install: Any) -> None:
    # Deterministic audit ran and downgraded the candidate; the run then stopped before the
    # auditor node returned, so the state still carries the engine's winner.
    c = candidate(status="inconclusive")
    store = install(Store([c], [audited_row(c, "deterministic_only")]))

    check = await enforcement.enforce_audit_completeness(object(), RUN_ID, "budget_exhausted")  # type: ignore[arg-type]

    assert check.unaudited == []  # it was audited: nothing to downgrade or announce
    assert store.status_calls == []
    assert store.events == []
    winner = check.winner(c.key)
    assert winner is None
    assert outcome(winner, "budget_exhausted") == (RunStatus.COMPLETED, RunOutcome.INCONCLUSIVE)


# --- the node itself: wiring, order, one transaction, retries -------------------------------


class Harness:
    """The real `write_report`, with everything outside the audit gate replaced."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, store: Store) -> None:
        self.store = store
        self.order: list[str] = []
        real_enforce = enforcement.enforce_audit_completeness

        async def enforce(*args: Any, **kwargs: Any) -> Any:
            self.order.append("enforce")
            return await real_enforce(*args, **kwargs)

        async def empty(*_: object, **__: object) -> list[Any]:
            return []

        async def section(*_: object, **__: object) -> dict[str, bool]:
            self.order.append("optimization_section")  # reads candidate statuses: comes after
            return {"benchmarked": True}

        async def summary(*_: object, **__: object) -> tuple[str, None]:
            return "", None

        async def outcomes(*_: object, **__: object) -> dict[str, int]:
            return {}

        for target, name, fake in (
            (enforcement, "list_candidates", store.list_candidates),
            (enforcement, "list_verifications", store.list_verifications),
            (enforcement, "set_candidate_status", store.set_candidate_status),
            (enforcement, "emit", store.emit),
            (module, "emit", store.emit),
            (module, "finalize_run", store.finalize_run),
            (module, "enforce_audit_completeness", enforce),
            (module, "list_hypotheses", empty),
            (module, "list_evidence", empty),
            (module, "optimization_section", section),
            (module, "_reconcile_summary", summary),
            (module, "call_outcomes", outcomes),
        ):
            monkeypatch.setattr(target, name, fake)
        self.ctx = SimpleNamespace(
            run_id=RUN_ID, engine=_Engine(store), attempt=1, events=FakeEvents()
        )
        self.ctx.db = lambda: self.ctx.engine

    async def run(self, *, winner: str | None, stop_reason: str | None) -> dict[str, Any]:
        state: dict[str, Any] = {
            "winner": winner,
            "stop_reason": stop_reason,
            "approval_status": "approved",
            "materiality": {},
            "no_action_evidence": [],
        }
        return await module.write_report(state, SimpleNamespace(context=self.ctx))  # type: ignore[arg-type]


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> Any:
    def make(store: Store) -> Harness:
        return Harness(monkeypatch, store)

    return make


@pytest.mark.parametrize("status", ["verified", "verified_with_noise_warning"])
async def test_the_node_seals_an_unaudited_winner_as_inconclusive(
    harness: Any, status: CandidateStatus
) -> None:
    c = candidate(status=status)
    store = Store([c], [], strict=True)
    h: Harness = harness(store)

    result = await h.run(winner=c.key, stop_reason="budget_exhausted")

    (conclusion,) = store.sealed
    assert conclusion.final_status is RunStatus.COMPLETED
    assert conclusion.outcome is RunOutcome.INCONCLUSIVE
    assert conclusion.stop_reason == "budget_exhausted"
    assert result == {"outcome": "inconclusive"}
    assert h.order == ["enforce", "optimization_section"]
    (written,) = store.candidates
    assert (written.id, written.status) == (c.id, "inconclusive")
    assert written.verdict_reasons == unaudited_reasons(unaudited(c), "budget_exhausted")
    assert [(kind, p["code"]) for kind, p in store.events] == [
        (EventType.ERROR, "AUDIT_NOT_COMPLETED")
    ]


@pytest.mark.parametrize("status", ["verified", "verified_with_noise_warning"])
async def test_the_node_seals_an_audited_winner_as_before(
    harness: Any, status: CandidateStatus
) -> None:
    c = candidate(status=status)
    store = Store([c], [audited_row(c)], strict=True)
    h: Harness = harness(store)

    result = await h.run(winner=c.key, stop_reason=None)

    (conclusion,) = store.sealed
    assert conclusion.outcome is RunOutcome.VERIFIED_RECOMMENDATION
    assert result == {"outcome": "verified_recommendation"}
    assert store.status_calls == []
    assert store.events == []
    assert store.candidates == [c]


async def test_the_node_does_not_report_a_winner_the_audit_downgraded(harness: Any) -> None:
    c = candidate(status="inconclusive")
    store = Store([c], [audited_row(c, "deterministic_only")], strict=True)
    h: Harness = harness(store)

    await h.run(winner=c.key, stop_reason="budget_exhausted")  # the state is stale: a winner

    (conclusion,) = store.sealed
    assert conclusion.outcome is RunOutcome.INCONCLUSIVE
    assert store.status_calls == []
    assert store.events == []


@pytest.mark.parametrize(
    ("stop_reason", "final_status"),
    [("cancelled", RunStatus.CANCELLED), ("failed", RunStatus.FAILED)],
)
async def test_a_cancelled_or_failed_run_never_keeps_an_unaudited_verified_candidate(
    harness: Any, stop_reason: str, final_status: RunStatus
) -> None:
    c = candidate()
    store = Store([c], [], strict=True)
    h: Harness = harness(store)

    await h.run(winner=c.key, stop_reason=stop_reason)

    (conclusion,) = store.sealed
    assert (conclusion.final_status, conclusion.outcome) == (final_status, None)
    assert store.candidates[0].status == "inconclusive"
    assert store.status_calls == [
        ([c.id], "inconclusive", unaudited_reasons(unaudited(c), stop_reason))
    ]
    assert len(store.events) == 1


async def test_a_failure_after_the_downgrade_leaves_no_partial_state_and_the_retry_writes_once(
    harness: Any,
) -> None:
    c = candidate()
    store = Store([c], [], strict=True)
    h: Harness = harness(store)
    store.fail_finalize = True

    with pytest.raises(Boom):
        await h.run(winner=c.key, stop_reason="budget_exhausted")

    # Rolled back as one: no downgrade, no error event, nothing sealed.
    assert store.candidates == [c]
    assert store.candidates[0].status == "verified"
    assert store.candidates[0].verdict_reasons is None
    assert store.status_calls == []
    assert store.events == []
    assert store.sealed == []
    assert store.run.finalized_at is None
    assert store.run.status == "running"

    store.fail_finalize = False
    await h.run(winner=c.key, stop_reason="budget_exhausted")

    assert store.status_calls == [
        ([c.id], "inconclusive", unaudited_reasons(unaudited(c), "budget_exhausted"))
    ]
    assert len(store.events) == 1
    assert len(store.sealed) == 1
    assert store.sealed[0].outcome is RunOutcome.INCONCLUSIVE


async def test_retrying_a_run_that_is_already_sealed_writes_nothing(harness: Any) -> None:
    c = candidate()
    store = Store([c], [], strict=True)
    h: Harness = harness(store)
    await h.run(winner=c.key, stop_reason="budget_exhausted")
    assert len(store.sealed) == 1
    before = (list(store.status_calls), list(store.events), list(store.sealed), store.candidates)
    h.order.clear()

    again = await h.run(winner=c.key, stop_reason="budget_exhausted")

    assert again == {"outcome": "inconclusive"}  # the sealed outcome, read back
    assert h.order == []  # the gate and the report builder are not even reached
    assert (
        list(store.status_calls),
        list(store.events),
        list(store.sealed),
        store.candidates,
    ) == before


async def test_a_terminal_run_that_was_never_finalized_is_not_touched_either(harness: Any) -> None:
    c = candidate()
    store = Store([c], [], strict=True)
    store.run = SimpleNamespace(status="cancelled", outcome=None, finalized_at=None)
    h: Harness = harness(store)

    result = await h.run(winner=c.key, stop_reason="cancelled")

    assert result == {"outcome": None}
    assert h.order == []
    assert store.status_calls == []
    assert store.events == []
    assert store.sealed == []
