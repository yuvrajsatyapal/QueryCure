"""Versioned prompts, one module per agent (CLAUDE.md §4: bump the version on any change)."""

from querycure.agents.prompts import (
    benchmark_auditor,
    index_strategist,
    optimization_engineer,
    query_analyzer,
    supervisor,
    workload_investigator,
)

# Every prompt version in use, recorded with eval results so a result names its prompts.
PROMPT_VERSIONS: dict[str, str] = {
    "benchmark_auditor": benchmark_auditor.PROMPT_VERSION,
    "index_strategist": index_strategist.PROMPT_VERSION,
    "optimization_engineer": optimization_engineer.PROMPT_VERSION,
    "query_analyzer": query_analyzer.PROMPT_VERSION,
    "supervisor_plan": supervisor.PLAN_PROMPT_VERSION,
    "supervisor_synthesis": supervisor.SYNTHESIS_PROMPT_VERSION,
    "workload_investigator": workload_investigator.PROMPT_VERSION,
}
