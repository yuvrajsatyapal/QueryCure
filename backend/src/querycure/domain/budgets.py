"""Default run budgets per profile (AGENT_SYSTEM §11). Domain-level so the API can stamp a
budget on a new run without importing the agents package."""

from querycure.core.config import Profile
from querycure.domain.investigation import RunBudget

_DEFAULTS = {
    Profile.LOCAL: RunBudget(
        llm_calls=40,
        total_tokens=400_000,
        tool_calls=80,
        tool_calls_per_agent=8,
        wall_clock_seconds=20 * 60,
    ),
    Profile.DEMO: RunBudget(
        llm_calls=20,
        total_tokens=150_000,
        tool_calls=40,
        tool_calls_per_agent=6,
        wall_clock_seconds=5 * 60,
        candidates_per_round=3,
        max_optimization_rounds=1,
    ),
}
CONCURRENT_RUNS_PER_USER = {Profile.LOCAL: 2, Profile.DEMO: 1}


def default_budget(profile: Profile) -> RunBudget:
    return _DEFAULTS[profile]
