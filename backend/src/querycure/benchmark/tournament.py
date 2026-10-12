"""Optimization Tournament ranking (BENCHMARK_ENGINE §8). Pure and order-independent.

Verified candidates rank by the primary param set's speedup CI lower bound. Candidates within
5% of the best remaining one are treated as tied and separated by smaller index, lower write
overhead class, then the simpler change (statistics < index < rewrite). "Within 5%" is not
transitive, so the ranking repeatedly picks the winner of the remaining field instead of
sorting with a pairwise comparator. Unverified candidates follow (inconclusive before
rejected) and can never win.
"""

from dataclasses import dataclass

from querycure.domain.benchmark import (
    SIMPLICITY,
    CandidateKind,
    TournamentEntry,
    Verdict,
    WriteOverhead,
)

TIE_BAND = 0.05
_WRITE_RANK = {"low": 0, "medium": 1, "unknown": 2, "high": 3}
_VERDICT_RANK = {"verified": 0, "inconclusive": 1, "rejected": 2}


@dataclass(frozen=True)
class Contender:
    arm: str
    verdict: Verdict
    primary_ci_low: float | None
    kind: CandidateKind
    index_size_bytes: int
    write_overhead: WriteOverhead


def _tiebreak(c: Contender) -> tuple[int, int, int, float, str]:
    return (
        c.index_size_bytes,
        _WRITE_RANK[c.write_overhead],
        SIMPLICITY[c.kind],
        -(c.primary_ci_low or 0.0),
        c.arm,
    )


def _verified_order(verified: list[Contender]) -> list[Contender]:
    remaining = sorted(verified, key=lambda c: c.arm)
    ordered: list[Contender] = []
    while remaining:
        best = max(c.primary_ci_low or 0.0 for c in remaining)
        band = [c for c in remaining if (c.primary_ci_low or 0.0) >= best * (1 - TIE_BAND)]
        pick = min(band, key=_tiebreak)
        ordered.append(pick)
        remaining.remove(pick)
    return ordered


def rank(contenders: list[Contender]) -> tuple[list[TournamentEntry], str | None]:
    verified = _verified_order([c for c in contenders if c.verdict == "verified"])
    others = sorted(
        (c for c in contenders if c.verdict != "verified"),
        key=lambda c: (_VERDICT_RANK[c.verdict], -(c.primary_ci_low or 0.0), c.arm),
    )
    table = [
        TournamentEntry(arm=c.arm, rank=i, verdict=c.verdict, primary_ci_low=c.primary_ci_low)
        for i, c in enumerate([*verified, *others], start=1)
    ]
    return table, verified[0].arm if verified else None
