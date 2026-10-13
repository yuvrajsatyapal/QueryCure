"""Candidate gate-6 safeguards for D13, scored on raw interleaved blocks.

Everything here is an *additional* condition on bench@2's clean `verified` outcome: the real
`querycure.benchmark.rules.assess` runs first, and a safeguard can only turn its `verified` into
`inconclusive`. Nothing changes any other verdict, so false-rejection rates are unaffected.
"""

import math
import random
import statistics
from collections.abc import Sequence

from querycure.benchmark.rules import BlockPair

# Two-sided 97.5% t quantiles (one-sided 2.5%) by degrees of freedom; df > 30 uses 1.96 + tail.
_T975 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306,
         9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131, 16: 2.120,
         17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086, 21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064,
         25: 2.060, 26: 2.056, 27: 2.052, 28: 2.048, 29: 2.045, 30: 2.042}


def t975(df: int) -> float:
    return _T975.get(df, 1.96 + 2.4 / max(df, 1))


def block_log_ratios(blocks: Sequence[BlockPair]) -> list[float]:
    return [
        math.log(statistics.median(b) / statistics.median(c))
        for b, c in blocks
        if b and c and statistics.median(c) > 0
    ]


def paired_t_low(blocks: Sequence[BlockPair]) -> float | None:
    """Lower 95% (two-sided) bound of the mean block log ratio, as a speedup factor."""
    r = block_log_ratios(blocks)
    if len(r) < 3:
        return None
    m, s = statistics.fmean(r), statistics.stdev(r)
    return math.exp(m - t975(len(r) - 1) * s / math.sqrt(len(r)))


def pooled_blocks(blocks: Sequence[BlockPair], size: int) -> list[BlockPair]:
    """Merge consecutive blocks so each holds `size` samples per arm (for block_size=1 runs)."""
    out: list[BlockPair] = []
    for i in range(0, len(blocks), size):
        chunk = blocks[i : i + size]
        out.append(([x for b, _ in chunk for x in b], [x for _, c in chunk for x in c]))
    return out


def block_bootstrap_low(blocks: Sequence[BlockPair], seed: int, resamples: int = 1000) -> float | None:
    """Cluster bootstrap of the ratio of medians: resample whole blocks, pool, take medians."""
    if len(blocks) < 3:
        return None
    rng = random.Random(seed)
    k = len(blocks)
    ratios = []
    for _ in range(resamples):
        pick = [blocks[int(rng.random() * k)] for _ in range(k)]
        b = [x for bb, _ in pick for x in bb]
        c = [x for _, cc in pick for x in cc]
        ratios.append(statistics.median(b) / statistics.median(c))
    ratios.sort()
    return ratios[math.floor(0.025 * resamples)]


def sign_test_ok(blocks: Sequence[BlockPair], alpha: float = 0.05) -> bool:
    """One-sided binomial sign test that blocks favour the candidate (ratio > 1)."""
    r = block_log_ratios(blocks)
    n = len(r)
    k = sum(1 for x in r if x > 0)
    p = sum(math.comb(n, j) for j in range(k, n + 1)) / 2**n
    return p <= alpha


# name -> predicate(blocks_primary, min_effect, seed) -> bool (True = keep "verified")
def make_rules(min_effect: float = 1.10) -> dict[str, object]:
    le = math.log(min_effect)
    return {
        "bench2": lambda bl, s: True,
        "all_blocks>=1.0": lambda bl, s: all(x >= 0 for x in block_log_ratios(bl)),
        "all_blocks>=min": lambda bl, s: all(x >= le for x in block_log_ratios(bl)),
        "sign_test": lambda bl, s: sign_test_ok(bl),
        "paired_t>=1.0": lambda bl, s: (lo := paired_t_low(bl)) is not None and lo >= 1.0,
        "paired_t>=min": lambda bl, s: (lo := paired_t_low(bl)) is not None and lo >= min_effect,
        "blockboot>=1.0": lambda bl, s: (lo := block_bootstrap_low(bl, s)) is not None and lo >= 1.0,
        "blockboot>=min": lambda bl, s: (lo := block_bootstrap_low(bl, s)) is not None and lo >= min_effect,
    }
