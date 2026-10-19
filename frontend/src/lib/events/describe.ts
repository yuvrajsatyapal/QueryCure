import type { RunEvent } from "@/lib/api/types";

type Payload = Record<string, unknown>;

function str(value: unknown): string {
  return typeof value === "string" ? value : "";
}

/** One line per event, in words (status is never colour alone). */
export function describe(event: RunEvent): { text: string; tone: "normal" | "muted" | "error" } {
  const p = event.payload as Payload;
  switch (event.type) {
    case "run.status_changed":
      return { text: `Run ${str(p.to)}${p.outcome ? ` · ${str(p.outcome).replaceAll("_", " ")}` : ""}`, tone: "normal" };
    case "node.started":
      return { text: `${str(p.node)} started`, tone: "muted" };
    case "node.completed":
      return { text: `${str(p.node)} done · ${Number(p.durationMs ?? 0)} ms`, tone: "muted" };
    case "agent.summary":
      return { text: `${str(p.agent)}: ${str(p.text)}`, tone: "normal" };
    case "tool.started":
      return { text: `${str(p.agent)} → ${str(p.tool)}`, tone: "muted" };
    case "tool.completed": {
      const ids = Array.isArray(p.evidenceIds) ? p.evidenceIds.length : 0;
      return {
        text: `${str(p.tool)} ${str(p.status)} · ${Number(p.durationMs ?? 0)} ms · ${ids} evidence`,
        tone: p.status === "ok" ? "muted" : "error",
      };
    }
    case "evidence.created":
      return { text: `+${Array.isArray(p.evidenceIds) ? p.evidenceIds.length : 0} evidence`, tone: "muted" };
    case "finding.created":
      return { text: `Finding: ${str(p.title)}`, tone: "normal" };
    case "hypothesis.created":
      return { text: `Hypothesis: ${str(p.category)} (${str(p.confidence)})`, tone: "normal" };
    case "budget.warning":
      return { text: `Budget: ${str(p.budget)} at ${Number(p.used)}/${Number(p.limit)}`, tone: "error" };
    case "candidate.created":
      return { text: `Candidate ${str(p.key)}: ${str(p.kind).replaceAll("_", " ")}`, tone: "normal" };
    case "approval.requested":
      return {
        text: p.status === "pending" ? `Approval needed for round ${Number(p.round ?? 0) + 1}` : `Approval recorded (${str(p.decidedBy)})`,
        tone: "normal",
      };
    case "approval.decided":
      return { text: `Approval ${str(p.status).replaceAll("_", " ")}`, tone: "normal" };
    case "benchmark.progress": {
      const block = typeof p.block === "number" && typeof p.blocksTotal === "number" ? ` · block ${p.block}/${p.blocksTotal}` : "";
      return { text: `Benchmark ${str(p.state).replaceAll("_", " ")}${block}`, tone: "muted" };
    }
    case "verification.completed": {
      const reasons = Array.isArray(p.reasons) && p.reasons.length ? ` (${str((p.reasons[0] as Payload).code)})` : "";
      return { text: `${str(p.candidateKey)}: ${str(p.verdict)}${reasons}`, tone: p.verdict === "rejected" ? "error" : "normal" };
    }
    case "run.concluded":
      return { text: `Concluded: ${str(p.finalStatus)}${p.outcome ? ` · ${str(p.outcome).replaceAll("_", " ")}` : ""}`, tone: "normal" };
    case "report.ready":
      return { text: "Final report sealed", tone: "normal" };
    case "replay.status_changed":
      return { text: `Replay ${str(p.to).replaceAll("_", " ")}${p.failureCode ? ` (${str(p.failureCode)})` : ""}`, tone: p.to === "failed" ? "error" : "normal" };
    case "replay.compared":
      return { text: `Replay compared: ${str(p.status).replaceAll("_", " ")} (${str(p.comparisonMode).replaceAll("_", " ")})`, tone: "normal" };
    case "error":
      return { text: `Error in ${str(p.node)}: ${str(p.code)} — ${str(p.message)}`, tone: "error" };
    default:
      return { text: event.type, tone: "muted" };
  }
}
