from querycure.benchmark.tournament import Contender, rank


def _c(arm: str, verdict: str, ci_low: float | None, *, kind: str = "create_index",
       index_bytes: int = 0, write: str = "unknown") -> Contender:  # fmt: skip
    return Contender(
        arm=arm,
        verdict=verdict,  # type: ignore[arg-type]
        primary_ci_low=ci_low,
        kind=kind,  # type: ignore[arg-type]
        index_size_bytes=index_bytes,
        write_overhead=write,  # type: ignore[arg-type]
    )


def test_verified_ranked_by_primary_ci_lower_bound() -> None:
    table, winner = rank([_c("oc_b", "verified", 3.0), _c("oc_a", "verified", 9.0)])

    assert [(e.arm, e.rank) for e in table] == [("oc_a", 1), ("oc_b", 2)]
    assert winner == "oc_a"


def test_within_five_percent_smaller_index_wins() -> None:
    big = _c("oc_big", "verified", 10.0, index_bytes=50_000_000)
    small = _c("oc_small", "verified", 9.6, index_bytes=2_000_000)

    _, winner = rank([big, small])

    assert winner == "oc_small"


def test_outside_five_percent_effect_wins_over_size() -> None:
    big = _c("oc_big", "verified", 10.0, index_bytes=50_000_000)
    small = _c("oc_small", "verified", 9.0, index_bytes=2_000_000)

    _, winner = rank([big, small])

    assert winner == "oc_big"


def test_simpler_change_breaks_remaining_ties() -> None:
    stats = _c("oc_stats", "verified", 5.0, kind="analyze_statistics")
    index = _c("oc_index", "verified", 5.0, kind="create_index")

    _, winner = rank([index, stats])

    assert winner == "oc_stats"


def test_write_overhead_breaks_ties_before_simplicity() -> None:
    low = _c("oc_low", "verified", 5.0, kind="create_index", write="low")
    high = _c("oc_high", "verified", 5.0, kind="analyze_statistics", write="high")

    _, winner = rank([high, low])

    assert winner == "oc_low"


def test_unverified_candidates_rank_after_verified_and_never_win() -> None:
    table, winner = rank(
        [
            _c("oc_rej", "rejected", None),
            _c("oc_inc", "inconclusive", 50.0),
            _c("oc_ok", "verified", 1.2),
        ]
    )

    assert [e.arm for e in table] == ["oc_ok", "oc_inc", "oc_rej"]
    assert winner == "oc_ok"


def test_no_verified_candidate_means_no_winner() -> None:
    _, winner = rank([_c("oc_inc", "inconclusive", 2.0), _c("oc_rej", "rejected", 0.5)])

    assert winner is None


def test_ranking_is_independent_of_input_order() -> None:
    items = [_c(f"oc_{i}", "verified", 2.0 + (i % 3) * 0.01) for i in range(6)]

    assert rank(items) == rank(list(reversed(items)))
