"""A virtual benchmark clock for deterministic end-to-end replay tests (Workstream 5, Phase 2).

Why: the replay classifier's cases depend on what the benchmark measured (a clean verified
source, a noise-warning source, a drifted or contradicting replay). Real latencies on a shared
host decide that differently from run to run, and an earlier test substituted one case for
another when they did. Production thresholds and rules must not change to fix that.

How: the executor's `time` module is replaced (test only) by a clock that never advances on
its own; the engine's `arm_noise` seam, called inside every timed region, advances it by a
duration drawn from a seeded profile. The sandbox still builds the index, runs every query
and fingerprints every row, so correctness, plans, the auditor's checks, the statistics,
the gates, replication and the comparison all run unchanged on fixed samples. Only elapsed
time is controlled. Untimed calls (round trips, DDL builds) measure zero.
"""

import random
from dataclasses import dataclass, field

import pytest

from querycure.benchmark.engine import EngineOptions
from querycure.domain.benchmark import BASELINE_ARM

MS = 1_000_000


@dataclass(frozen=True)
class Profile:
    """Sample duration = (median ± uniform `jitter` fraction) + uniform [0, `spike_ms`)."""

    baseline_ms: float
    candidate_ms: float
    jitter: float = 0.01
    spike_ms: float = 0.0

    def draw(self, arm: str, rng: random.Random) -> int:
        median = self.baseline_ms if arm == BASELINE_ARM else self.candidate_ms
        spread = rng.uniform(-self.jitter, self.jitter)
        value = median * (1 + spread) + rng.uniform(0, self.spike_ms)
        return max(1, round(value * MS))


# A clean 3x win: every gate passes in one experiment.
CLEAN = Profile(baseline_ms=9.0, candidate_ms=3.0)
# A clear sub-ms win buried in 0-2 ms of additive noise: gate 4b fails on dispersion, the
# effect stays separated, so replication runs and the three experiments agree (ADR-0019 §3).
NOISY = Profile(baseline_ms=9.0, candidate_ms=0.3, jitter=0.0, spike_ms=2.0)
# Same direction and correctness, but S = 2 instead of 3: drift D ≈ 0.67, outside ±25%.
DRIFTED = Profile(baseline_ms=9.0, candidate_ms=4.5)
# The candidate is now slower than the baseline: the verdict changes.
REVERSED = Profile(baseline_ms=3.0, candidate_ms=9.0)
# A clear regression (3x slower): rejected, and rejected again when re-measured.
REGRESSED = Profile(baseline_ms=9.0, candidate_ms=27.0)
# Too dispersed to judge: gate 4 fails on the replay side of the comparison.
UNDECIDABLE = Profile(baseline_ms=9.0, candidate_ms=3.0, jitter=0.0, spike_ms=30.0)


@dataclass
class VirtualClock:
    """`profile` times every arm; `arms`, when given, times candidate arms instead, assigned in
    order of first appearance (round 1's candidate before round 2's), so a multi-round
    investigation is timed deterministically without knowing its generated candidate keys."""

    profile: Profile
    seed: int = 0
    arms: tuple[Profile, ...] = ()
    now: int = 0
    samples: int = 0
    _rng: random.Random = field(init=False)
    _assigned: dict[str, Profile] = field(init=False, default_factory=dict)

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)

    def perf_counter_ns(self) -> int:
        return self.now

    def _profile_for(self, arm: str) -> Profile:
        if arm == BASELINE_ARM or not self.arms:
            return self.profile
        if arm not in self._assigned:
            self._assigned[arm] = self.arms[min(len(self._assigned), len(self.arms) - 1)]
        return self._assigned[arm]

    def arm_noise(self, arm: str, param_set: str, block: int) -> None:
        self.samples += 1
        self.now += self._profile_for(arm).draw(arm, self._rng)

    def use(self, profile: Profile, *, seed: int, arms: tuple[Profile, ...] = ()) -> None:
        """Switch profile (e.g. source, then replay) with a fresh seeded stream."""
        self.profile = profile
        self.arms = arms
        self._assigned = {}
        self._rng = random.Random(seed)

    def options(self, **kw: object) -> EngineOptions:
        return EngineOptions(arm_noise=self.arm_noise, **kw)  # type: ignore[arg-type]


def install(
    monkeypatch: pytest.MonkeyPatch,
    profile: Profile,
    *,
    seed: int = 0,
    arms: tuple[Profile, ...] = (),
) -> VirtualClock:
    """Replace the benchmark executor's clock for this test only."""
    clock = VirtualClock(profile, seed=seed, arms=arms)
    monkeypatch.setattr("querycure.benchmark.executor.time", clock)
    return clock
