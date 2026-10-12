from collections import Counter

import pytest

from querycure.benchmark.schedule import build_schedule, derive_seed

ARMS = ["baseline", "oc_a", "oc_b"]


def _runs_per(schedule: list, param_set: str) -> Counter[str]:
    counts: Counter[str] = Counter()
    for block in schedule:
        if block.param_set == param_set:
            for arm in block.arm_order:
                counts[arm] += block.runs
    return counts


def test_every_arm_gets_exactly_the_measured_runs() -> None:
    schedule = build_schedule(ARMS, ["hot", "cold"], measured_runs=30, block_size=5, seed=7)

    for param_set in ("hot", "cold"):
        assert _runs_per(schedule, param_set) == {arm: 30 for arm in ARMS}


def test_last_block_is_partial_when_runs_do_not_divide() -> None:
    schedule = build_schedule(ARMS, ["hot"], measured_runs=12, block_size=5, seed=7)

    assert [b.runs for b in schedule] == [5, 5, 2]
    assert _runs_per(schedule, "hot") == {arm: 12 for arm in ARMS}


def test_each_block_contains_every_arm_once() -> None:
    for block in build_schedule(ARMS, ["hot"], measured_runs=30, block_size=5, seed=1):
        assert sorted(block.arm_order) == sorted(ARMS)


def test_param_sets_alternate_within_each_block_index() -> None:
    schedule = build_schedule(ARMS, ["hot", "cold"], measured_runs=10, block_size=5, seed=1)

    assert [(b.block, b.param_set) for b in schedule] == [
        (0, "hot"), (0, "cold"), (1, "hot"), (1, "cold")
    ]  # fmt: skip


def test_schedule_is_deterministic_and_seed_dependent() -> None:
    def orders(seed: int) -> list[tuple[str, ...]]:
        schedule = build_schedule(ARMS, ["hot"], measured_runs=50, block_size=5, seed=seed)
        return [b.arm_order for b in schedule]

    assert orders(42) == orders(42)
    assert orders(42) != orders(43)


def test_shuffle_spreads_first_position_across_arms() -> None:
    """Interleaving must not always run the same arm first (drift would favour it)."""
    schedule = build_schedule(ARMS, ["hot"], measured_runs=300, block_size=5, seed=3)

    firsts = Counter(b.arm_order[0] for b in schedule)

    assert set(firsts) == set(ARMS)
    assert max(firsts.values()) - min(firsts.values()) <= 15


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"measured_runs": 0, "block_size": 5}, "measured_runs"),
        ({"measured_runs": 10, "block_size": 0}, "block_size"),
    ],
)
def test_invalid_sizes_are_refused(kwargs: dict[str, int], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        build_schedule(ARMS, ["hot"], seed=1, **kwargs)


def test_derived_seeds_are_stable_and_distinct() -> None:
    assert derive_seed(42, "hot", 0) == derive_seed(42, "hot", 0)
    assert derive_seed(42, "hot", 0) != derive_seed(42, "hot", 1)
    # Golden value: a changed derivation would silently reorder stored experiments on replay.
    assert derive_seed(42, "hot", 0) == 0xB504B48E3E7F2579


def test_schedule_golden_order() -> None:
    """Pinned: replay re-derives the original order from the stored seed."""
    schedule = build_schedule(ARMS, ["hot"], measured_runs=40, block_size=5, seed=42)

    assert [b.arm_order for b in schedule][3:6] == [
        ("oc_b", "oc_a", "baseline"),
        ("baseline", "oc_b", "oc_a"),
        ("baseline", "oc_b", "oc_a"),
    ]
