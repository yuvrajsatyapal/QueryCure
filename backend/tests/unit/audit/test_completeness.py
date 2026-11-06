"""Audit-completeness invariant (pure part): a verified result is only as good as its audit.

The Benchmark Auditor is the required deterministic check between an experiment verdict and a
`verified_recommendation`. If it never ran (budget expired, run stopped), the candidate must
not be reported as verified. These tests pin the exact matching rule: a candidate is audited
only by a verification row for *its* experiment, *its* candidate id, key and round.

Candidate keys are unique per run and derived from the round (`candidates.to_candidates`,
unique index `(run_id, key)`), so every scenario below uses distinct keys.
"""

import uuid
from dataclasses import dataclass

import pytest

from querycure.audit.completeness import (
    UNAUDITED_CODE,
    UnauditedCandidate,
    audit_incomplete_error,
    audited_winner,
    unaudited_candidates,
    unaudited_reasons,
)
from querycure.domain.optimization import CandidateCost, CandidateStatus, OptimizationCandidate

RUN = uuid.UUID("00000000-0000-4000-8000-0000000000bb")
KEY_A = "oc_" + "a" * 12
KEY_B = "oc_" + "b" * 12
KEY_C = "oc_" + "c" * 12


def experiment_for(round: int) -> uuid.UUID:
    return uuid.uuid5(RUN, f"experiment:{round}")


def replicate_experiment_for(round: int, index: int) -> uuid.UUID:
    # Same derivation as benchmark.replication.replicate_config.
    return uuid.uuid5(experiment_for(round), f"replicate:{index}")


def candidate(
    key: str = KEY_A,
    *,
    round: int = 0,
    status: CandidateStatus = "verified",
    id: uuid.UUID | None = None,
) -> OptimizationCandidate:
    return OptimizationCandidate(
        id=id or uuid.uuid5(RUN, f"{key}:{round}"),
        key=key,
        round=round,
        kind="create_index",
        addresses_hypotheses=["hy_" + "1" * 12],
        ddl=["CREATE INDEX ON t (a)"],
        query_sql=None,
        sql_sha256="ab" * 32,
        rollback_sql=None,
        expected_benefit="fewer rows read",
        risks=[],
        estimated_cost=CandidateCost(),
        status=status,
    )


@dataclass(frozen=True)
class Row:
    experiment_id: uuid.UUID
    candidate_id: uuid.UUID
    candidate_key: str
    round: int
    auditor_status: str = "completed"


def row_for(c: OptimizationCandidate, **overrides: object) -> Row:
    base = Row(
        experiment_id=experiment_for(c.round),
        candidate_id=c.id,  # type: ignore[arg-type]
        candidate_key=c.key,
        round=c.round,
    )
    return Row(**{**base.__dict__, **overrides})


def find(cands: list[OptimizationCandidate], rows: list[Row]) -> list[UnauditedCandidate]:
    return unaudited_candidates(cands, rows, experiment_id_for=experiment_for)


def unaudited(c: OptimizationCandidate) -> UnauditedCandidate:
    return UnauditedCandidate(id=c.id, key=c.key, round=c.round, status=c.status)


# --- which candidates are unaudited ---------------------------------------------------------


def test_audited_verified_candidate_is_not_flagged() -> None:
    c = candidate()
    assert find([c], [row_for(c)]) == []


def test_a_deterministic_only_row_still_counts_as_audited() -> None:
    # Only the LLM narrative was skipped: the deterministic checks ran and are recorded.
    c = candidate()
    assert find([c], [row_for(c, auditor_status="deterministic_only")]) == []


@pytest.mark.parametrize("status", ["verified", "verified_with_noise_warning"])
def test_verified_candidate_without_a_row_is_flagged(status: CandidateStatus) -> None:
    c = candidate(status=status)
    assert find([c], []) == [UnauditedCandidate(id=c.id, key=KEY_A, round=0, status=status)]


@pytest.mark.parametrize(
    "status",
    ["proposed", "approved", "declined", "expired", "benchmarked", "rejected", "inconclusive"],
)
def test_candidates_that_are_not_verified_never_need_an_audit(status: CandidateStatus) -> None:
    assert find([candidate(status=status)], []) == []


def test_a_row_for_another_rounds_experiment_does_not_audit_this_candidate() -> None:
    c = candidate(round=0)
    assert find([c], [row_for(c, experiment_id=experiment_for(1))]) == [unaudited(c)]


@pytest.mark.parametrize("index", [1, 2])
def test_a_replicate_experiments_record_cannot_audit_the_primary_candidate(index: int) -> None:
    # Replicates re-measure arms in their own experiments (ids derived from the primary's);
    # the audit that counts is the primary experiment's.
    c = candidate()
    replicate_row = row_for(c, experiment_id=replicate_experiment_for(0, index))
    assert find([c], [replicate_row]) == [unaudited(c)]
    assert find([c], [replicate_row, row_for(c)]) == []  # the primary's own row still counts


def test_a_row_for_another_candidate_does_not_audit_this_candidate() -> None:
    a, b = candidate(KEY_A), candidate(KEY_B)
    assert find([a, b], [row_for(a)]) == [unaudited(b)]
    assert find([a, b], [row_for(b)]) == [unaudited(a)]


@pytest.mark.parametrize(
    "mismatch",
    [
        {"candidate_key": KEY_C},
        {"round": 1},
        {"candidate_id": uuid.UUID("00000000-0000-4000-8000-0000000000cc")},
        {"experiment_id": uuid.UUID("00000000-0000-4000-8000-0000000000dd")},
    ],
    ids=["key", "round", "candidate_id", "experiment_id"],
)
def test_every_identifier_must_match_not_only_some(mismatch: dict[str, object]) -> None:
    c = candidate()
    assert find([c], [row_for(c, **mismatch)]) == [unaudited(c)]


def test_a_candidate_without_an_id_cannot_be_matched_and_fails_closed() -> None:
    c = candidate().model_copy(update={"id": None})
    assert find([c], []) == [UnauditedCandidate(id=None, key=KEY_A, round=0, status="verified")]
    # Not even a row that carries the key and round can vouch for an id-less candidate.
    assert find([c], [row_for(candidate())]) == [
        UnauditedCandidate(id=None, key=KEY_A, round=0, status="verified")
    ]


def test_only_the_unaudited_round_is_flagged_in_a_multi_round_run() -> None:
    first, second = candidate(KEY_A, round=0), candidate(KEY_B, round=1)
    assert find([first, second], [row_for(first)]) == [
        UnauditedCandidate(id=second.id, key=KEY_B, round=1, status="verified")
    ]


def test_each_rounds_audit_is_matched_against_that_rounds_experiment() -> None:
    first, second = candidate(KEY_A, round=0), candidate(KEY_B, round=1)
    rows = [row_for(first), row_for(second)]
    assert find([first, second], rows) == []
    # Swapping the experiments (each row claims the other round's experiment) audits neither.
    swapped = [
        row_for(first, experiment_id=experiment_for(1)),
        row_for(second, experiment_id=experiment_for(0)),
    ]
    assert find([first, second], swapped) == [unaudited(first), unaudited(second)]


# --- which winner survives ------------------------------------------------------------------


@pytest.mark.parametrize("status", ["verified", "verified_with_noise_warning"])
def test_audited_winner_survives(status: CandidateStatus) -> None:
    c = candidate(status=status)
    assert audited_winner(KEY_A, [c], find([c], [row_for(c)])) == KEY_A


@pytest.mark.parametrize("status", ["verified", "verified_with_noise_warning"])
def test_unaudited_winner_is_dropped(status: CandidateStatus) -> None:
    c = candidate(status=status)
    assert audited_winner(KEY_A, [c], find([c], [])) is None


def test_the_audited_winner_of_an_earlier_round_survives_a_later_unaudited_round() -> None:
    first, second = candidate(KEY_A, round=0), candidate(KEY_B, round=1)
    cands = [first, second]
    flagged = find(cands, [row_for(first)])
    assert flagged == [unaudited(second)]
    assert audited_winner(KEY_A, cands, flagged) == KEY_A
    assert audited_winner(KEY_B, cands, flagged) is None


def test_winner_is_dropped_when_the_audit_itself_downgraded_it() -> None:
    # The auditor recorded its downgrade, then the run stopped before the node could return
    # its updated winner: the state still names the engine's winner, the records do not.
    c = candidate(status="inconclusive")
    assert find([c], [row_for(c)]) == []
    assert audited_winner(KEY_A, [c], []) is None


def test_winner_whose_candidate_was_rejected_is_dropped() -> None:
    c = candidate(status="rejected")
    assert audited_winner(KEY_A, [c], find([c], [row_for(c)])) is None


def test_winner_that_matches_no_candidate_fails_closed() -> None:
    c = candidate()
    assert audited_winner(KEY_C, [c], find([c], [row_for(c)])) is None


def test_no_winner_stays_no_winner() -> None:
    c = candidate()
    assert audited_winner(None, [c], find([c], [])) is None
    assert audited_winner(None, [c], find([c], [row_for(c)])) is None


# --- the recorded reason and the error event ------------------------------------------------


def test_downgrade_reason_is_exact_and_has_its_own_code() -> None:
    item = UnauditedCandidate(id=uuid.uuid4(), key=KEY_A, round=0, status="verified")
    # Not `audit_downgrade`: that code is rendered as "the Benchmark Auditor found a reason to
    # doubt the result", which would claim an audit that never ran.
    assert unaudited_reasons(item, "budget_exhausted") == [
        {
            "code": "audit_not_completed",
            "detail": (
                "Unaudited: the engine verdict `verified` was not audited (stop reason: "
                "budget_exhausted); the required Benchmark Auditor checks did not run, so it "
                "is not reported as verified."
            ),
        }
    ]


def test_downgrade_reason_without_a_stop_reason_omits_the_clause() -> None:
    item = UnauditedCandidate(
        id=uuid.uuid4(), key=KEY_A, round=0, status="verified_with_noise_warning"
    )
    assert unaudited_reasons(item, None) == [
        {
            "code": "audit_not_completed",
            "detail": (
                "Unaudited: the engine verdict `verified_with_noise_warning` was not audited; "
                "the required Benchmark Auditor checks did not run, so it is not reported as "
                "verified."
            ),
        }
    ]


def test_error_payload_for_one_candidate_is_exact() -> None:
    item = UnauditedCandidate(id=uuid.uuid4(), key=KEY_A, round=0, status="verified")
    error = audit_incomplete_error([item], "budget_exhausted")
    assert error.model_dump() == {
        "node": "write_report",
        "code": UNAUDITED_CODE,
        "message": (
            f"1 verified result was not audited and is not reported as verified: {KEY_A} "
            "(stop reason: budget_exhausted)."
        ),
        "recoverable": False,
    }
    assert UNAUDITED_CODE == "AUDIT_NOT_COMPLETED"


def test_error_payload_lists_the_first_keys_and_counts_the_rest() -> None:
    keys = ["oc_" + f"{i:012x}" for i in range(12)]
    items = [
        UnauditedCandidate(id=uuid.uuid4(), key=k, round=i % 2, status="verified")
        for i, k in enumerate(keys)
    ]
    error = audit_incomplete_error(items, None)
    assert error.message == (
        "12 verified results were not audited and are not reported as verified: "
        + ", ".join(keys[:8])
        + " and 4 more."
    )
    assert error.recoverable is False
