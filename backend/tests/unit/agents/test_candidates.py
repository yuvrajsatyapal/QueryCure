import uuid

from querycure.agents.candidates import arm_of, judge_candidates, to_candidates
from querycure.agents.outputs import CandidateDraft, CandidateSet
from querycure.benchmark.engine import sql_digest

BASE = "SELECT * FROM orders WHERE customer_id = $1 ORDER BY created_at DESC LIMIT 20"
HY = "hy_000000000001"


def _draft(**kw: object) -> CandidateDraft:
    body: dict[str, object] = {
        "kind": "create_index",
        "addresses_hypotheses": [HY],
        "ddl": ["CREATE INDEX ON orders (customer_id, created_at);"],
        "expected_benefit": "Avoids the sort.",
    }
    body.update(kw)
    return CandidateDraft.model_validate(body)


def _judge(*drafts: CandidateDraft, seen: tuple[str, ...] = (), cap: int = 4):  # type: ignore[no-untyped-def]
    return judge_candidates(
        CandidateSet(candidates=list(drafts), summary="s"),
        baseline=BASE,
        hypothesis_keys={HY},
        seen_digests=set(seen),
        max_candidates=cap,
    )


def test_valid_candidate_is_kept_and_normalized() -> None:
    out, report = _judge(_draft())

    assert report.removed == 0
    assert out.candidates[0].ddl == ["CREATE INDEX ON orders (customer_id, created_at)"]


def test_policy_violation_is_removed_with_a_reason() -> None:
    out, report = _judge(_draft(ddl=["DROP TABLE orders"]), _draft())

    assert len(out.candidates) == 1
    assert report.removed == 1
    assert "sandbox policy" in report.problems[0]


def test_unknown_hypotheses_are_stripped_and_a_candidate_without_any_is_dropped() -> None:
    out, report = _judge(
        _draft(addresses_hypotheses=["hy_ffffffffffff", HY]),
        _draft(addresses_hypotheses=["hy_ffffffffffff"], ddl=["ANALYZE orders"],
               kind="analyze_statistics"),
    )  # fmt: skip

    assert [c.addresses_hypotheses for c in out.candidates] == [[HY]]
    assert report.removed == 1


def test_more_than_half_invalid_asks_for_one_retry() -> None:
    _, report = _judge(_draft(ddl=["DROP TABLE orders"]), _draft(ddl=["VACUUM orders"]), _draft())

    assert report.needs_retry


def test_repeats_within_a_round_or_from_earlier_rounds_are_dropped() -> None:
    earlier = sql_digest(arm_of(_draft(ddl=["CREATE INDEX ON orders (customer_id)"])))

    out, report = _judge(
        _draft(), _draft(), _draft(ddl=["CREATE INDEX ON orders (customer_id)"]), seen=(earlier,)
    )

    assert len(out.candidates) == 1
    assert report.removed == 2


def test_round_cap_drops_extras_without_counting_them_as_invalid() -> None:
    out, report = _judge(_draft(), _draft(ddl=["CREATE INDEX ON orders (customer_id)"]), cap=1)

    assert len(out.candidates) == 1
    assert report.removed == 0


def test_rewrite_must_keep_the_parameters() -> None:
    out, report = _judge(
        _draft(kind="query_rewrite", ddl=[], query="SELECT * FROM orders LIMIT 20")
    )

    assert out.candidates == []
    assert "parameters" in report.problems[0]


def test_candidate_keys_and_digests_are_deterministic() -> None:
    run = uuid.UUID(int=1)
    out, _ = _judge(_draft())

    first = to_candidates(run, 0, out)
    again = to_candidates(run, 0, out)

    assert first == again
    assert first[0].key.startswith("oc_")
    assert first[0].sql_sha256 == sql_digest(arm_of(out.candidates[0], first[0].key))
    assert to_candidates(run, 1, out)[0].key != first[0].key
