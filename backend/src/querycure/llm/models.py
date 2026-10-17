"""Which free models are known to carry an investigation (ADR-0026).

A model is listed only on recorded evidence: eval recordings that replay green, and real runs
that completed with schema-valid output. One good run is not enough; the list is short on
purpose. An unlisted model still works (free-only rules apply as always) but the worker warns
at startup, and `python -m querycure.llm.probe` checks it with a single call.
"""

from dataclasses import dataclass

from querycure.core.config import FREE_ROUTER


@dataclass(frozen=True)
class ModelRecord:
    model: str
    evidence: str


TESTED_STRUCTURED_MODELS: dict[str, ModelRecord] = {
    "nvidia/nemotron-3-super-120b-a12b:free": ModelRecord(
        model="nvidia/nemotron-3-super-120b-a12b:free",
        evidence=(
            "Phase 2 free-model benchmark (smoke 5/5); every eval recording since 2026-10-12; "
            "E2E audit 2026-10-17 runs 2 and 3: 13 of 13 calls schema-valid"
        ),
    ),
}

ROUTER_WARNING = (
    "openrouter/free picks a different free model per request; in the 2026-10-17 audit it "
    "returned 1 valid structured output in 10 calls. Use it as LLM_FALLBACK_MODEL at most."
)


def model_warning(model: str) -> str | None:
    """Why a configured model is a reliability risk, or None for a tested one."""
    if model == FREE_ROUTER:
        return ROUTER_WARNING
    if model in TESTED_STRUCTURED_MODELS:
        return None
    return (
        f"{model} has no recorded structured-output evidence in QueryCure; check it with "
        "`python -m querycure.llm.probe` (one request) before relying on it."
    )
