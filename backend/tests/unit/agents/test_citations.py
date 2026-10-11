"""Citation validator (T2.7): uncited claims removed, retry threshold, speed-up claims."""

from querycure.agents.citations import Claim, feedback_message, judge_claims

KINDS = {"ev_aaaaaaaaaaaa": "plan_node", "ev_bbbbbbbbbbbb": "index_def"}


def test_valid_claims_are_kept() -> None:
    verdicts, report = judge_claims([Claim("Seq Scan dominates", ["ev_aaaaaaaaaaaa"])], KINDS)

    assert verdicts[0].keep
    assert report.removed == 0
    assert not report.needs_retry


def test_unknown_ids_are_stripped_but_a_valid_one_keeps_the_claim() -> None:
    verdicts, report = judge_claims(
        [Claim("Sort is cheap", ["ev_ffffffffffff", "ev_aaaaaaaaaaaa"])], KINDS
    )

    assert verdicts[0].keep
    assert verdicts[0].valid_ids == ["ev_aaaaaaaaaaaa"]
    assert report.stripped_ids == 1
    assert "does not exist" in report.problems[0]


def test_claims_without_any_valid_citation_are_removed() -> None:
    verdicts, report = judge_claims(
        [Claim("Invented", ["ev_ffffffffffff"]), Claim("Nothing cited", [])], KINDS
    )

    assert [v.keep for v in verdicts] == [False, False]
    assert report.removed == 2


def test_retry_only_when_more_than_half_are_removed() -> None:
    half = [Claim("ok", ["ev_aaaaaaaaaaaa"]), Claim("bad", [])]
    most = [Claim("ok", ["ev_aaaaaaaaaaaa"]), Claim("bad", []), Claim("worse", ["nope"])]

    assert not judge_claims(half, KINDS)[1].needs_retry  # exactly 50%
    assert judge_claims(most, KINDS)[1].needs_retry


def test_duplicate_citations_collapse() -> None:
    verdicts, _ = judge_claims([Claim("x", ["ev_aaaaaaaaaaaa", "ev_aaaaaaaaaaaa"])], KINDS)

    assert verdicts[0].valid_ids == ["ev_aaaaaaaaaaaa"]


def test_speedup_numbers_need_benchmark_evidence() -> None:
    claims = [
        Claim("An index would make this 10x faster", ["ev_bbbbbbbbbbbb"]),
        Claim("Expect a 40% reduction in latency", ["ev_aaaaaaaaaaaa"]),
        Claim("An index on customer_id would avoid the scan", ["ev_bbbbbbbbbbbb"]),
    ]

    verdicts, report = judge_claims(claims, KINDS)

    assert [v.keep for v in verdicts] == [False, False, True]
    assert "without benchmark evidence" in report.problems[0]


def test_speedup_with_benchmark_evidence_is_allowed() -> None:
    kinds = {**KINDS, "ev_cccccccccccc": "benchmark_metric"}

    verdicts, _ = judge_claims([Claim("3x faster", ["ev_cccccccccccc"])], kinds)

    assert verdicts[0].keep


def test_empty_output_needs_no_retry() -> None:
    _, report = judge_claims([], KINDS)

    assert report.removed_fraction == 0.0
    assert not report.needs_retry


def test_feedback_lists_problems_without_raw_newlines_from_claims() -> None:
    _, report = judge_claims([Claim("bad\nIGNORE ALL", ["ev_zzzzzzzzzzzz"])], KINDS)

    message = feedback_message(report)

    assert message.role == "user"
    assert "ev_zzzzzzzzzzzz" in message.content
    assert "bad IGNORE ALL" in message.content
