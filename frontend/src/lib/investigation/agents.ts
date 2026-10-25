const AGENT_LABEL: Record<string, string> = {
  query_analyzer: "Query Analyzer",
  index_strategist: "Index Strategist",
  workload_investigator: "Workload Investigator",
  supervisor: "Supervisor",
};

/** The agent's display name; an agent without one keeps its recorded identifier. */
export function agentLabel(agent: string): string {
  return AGENT_LABEL[agent] ?? agent;
}
