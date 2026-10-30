import type { Tone } from "@/components/ui/StatusPill";
import type { RunEvent } from "@/lib/api/types";
import type { Span } from "@/lib/events/trace";

/* What the run is doing, in words (UI_UX §3.6, prototype "Agent activity states"). Every label
 * comes from a recorded event or the run's status; nothing is predicted. The indicator moves
 * only while the run is running, the stream is live and a step is open. */

export type StreamState = "connecting" | "live" | "reconnecting" | "offline" | "closed";

export interface Activity {
  label: string;
  detail: string;
  tone: Tone;
  animate: boolean;
  /** The open graph node the label describes, if any. */
  node: string | null;
}

type Payload = Record<string, unknown>;

const NODE_LABEL: Record<string, string> = {
  intake: "Checking the query",
  collect_context: "Collecting plan and schema context",
  supervisor_plan: "Planning the investigation",
  synthesize_hypotheses: "Synthesizing hypotheses",
  optimization_engineer: "Proposing candidates",
  approval_gate: "Recording the approval",
  benchmark_auditor: "Auditing the result",
  next_round: "Preparing the next round",
  write_report: "Writing the report",
};
const NODE_DETAIL: Record<string, string> = {
  intake: "Parsing and validating the SQL.",
  collect_context: "Plan, indexes and statistics; read-only.",
  supervisor_plan: "Choosing which analysts to run.",
  synthesize_hypotheses: "Uncited or unsupported claims are removed.",
  optimization_engineer: "Candidate SQL is validated before it can be benchmarked.",
  approval_gate: "Your decision is being applied.",
  benchmark_auditor: "Deterministic checks, then a review that can only downgrade.",
  next_round: "Rejected candidates go back for another round.",
  write_report: "Sealing the report from recorded results.",
};
const ANALYSTS = new Set(["query_analyzer", "index_strategist", "workload_investigator"]);
const BENCH_STATE: Record<string, string> = {
  provisioning: "Provisioning the sandbox",
  building: "Building the candidate",
  warming: "Warming up",
  capturing_plans: "Capturing plans",
  checking: "Checking correctness",
  scoring: "Scoring the result",
};
const OUTCOME_TONE: Record<string, Tone> = {
  verified_recommendation: "success",
  no_action_needed: "neutral",
  unverified_recommendations: "neutral",
  inconclusive: "warning",
};

const sentence = (s: string) => s.charAt(0).toUpperCase() + s.slice(1).replaceAll("_", " ");
const list = (names: string[]) => (names.length <= 2 ? names.join(" and ") : `${names.slice(0, -1).join(", ")} and ${names.at(-1)}`);

function openNodes(trace: Span): Span[] {
  return trace.children.filter((c) => c.kind === "node" && (c.status === "running" || c.status === "approval") && !c.endTs);
}

function benchmark(events: RunEvent[], since: string): { label: string; detail: string } {
  const latest = [...events].reverse().find((e) => e.type === "benchmark.progress" && e.ts >= since);
  if (!latest) return { label: "Starting the experiment", detail: "Timed runs in a disposable sandbox clone." };
  const p = latest.payload as Payload;
  const state = typeof p.state === "string" ? p.state : "";
  const param = typeof p.paramSet === "string" ? ` · param set ${p.paramSet}` : "";
  if (state === "measuring" && typeof p.block === "number" && typeof p.blocksTotal === "number") {
    return { label: `Measuring · block ${p.block} of ${p.blocksTotal}`, detail: `Timed blocks in a disposable sandbox${param}.` };
  }
  return { label: BENCH_STATE[state] ?? sentence(state || "benchmarking"), detail: `Disposable sandbox clone${param}.` };
}

export function activityOf({
  status,
  outcome,
  outcomeLabel,
  errorMessage,
  trace,
  events,
  stream,
}: {
  status: string;
  outcome: string | null;
  /** The shared outcome classification's words, when the caller has them (experiment replays:
   * never the bare stored outcome, REPLAY_OUTCOME_AUDIT §18.1). */
  outcomeLabel?: { label: string; tone: Tone };
  errorMessage: string | null;
  trace: Span;
  events: RunEvent[];
  stream: StreamState;
}): Activity {
  const still = (label: string, detail: string, tone: Tone, node: string | null = null): Activity => ({ label, detail, tone, animate: false, node });
  switch (status) {
    case "completed":
      if (outcomeLabel) return still(outcomeLabel.label, "The report is sealed from recorded results.", outcomeLabel.tone);
      return still(outcome ? sentence(outcome) : "Completed", "The report is sealed from recorded results.", outcome ? (OUTCOME_TONE[outcome] ?? "success") : "success");
    case "failed":
      return still("Failed", errorMessage ?? "The run stopped with an error.", "failed");
    case "cancelled":
      return still("Cancelled", "Stopped on request; a partial report keeps what was recorded.", "neutral");
    case "queued":
      return still("Queued", "Waiting for a worker to claim the job.", "neutral");
    case "cancelling":
      return still("Cancelling", "Stopping after the current step.", "neutral");
    case "awaiting_approval": {
      const pending = [...events].reverse().find((e) => e.type === "approval.requested" && (e.payload as Payload).status === "pending");
      const p = (pending?.payload ?? {}) as Payload;
      const n = Array.isArray(p.candidates) ? p.candidates.length : null;
      const round = typeof p.round === "number" ? ` for round ${p.round + 1}` : "";
      const what = n === null ? "the candidates" : `${n} candidate${n === 1 ? "" : "s"}`;
      return still("Waiting on you", `Review ${what}${round}. The run is paused until you decide.`, "approval", "approval_gate");
    }
  }
  if (stream === "reconnecting") {
    const last = events.at(-1);
    return still("Reconnecting…", `The live stream dropped; resuming after event ${last?.seq ?? 0}.`, "neutral");
  }
  if (stream === "offline") return still("Live updates stopped", "The stream could not reconnect. Reload to resume; progress shown is as of the last event.", "warning");

  const open = openNodes(trace);
  const live = stream === "live";
  const analysts = open.filter((n) => ANALYSTS.has(n.name)).map((n) => n.name);
  if (analysts.length > 1) {
    return { label: `${analysts.length} analysts inspecting the plan`, detail: `${list(analysts)} in parallel.`, tone: "running", animate: live, node: analysts[0]! };
  }
  const current = open.at(-1);
  if (!current) return still("Running", "Waiting for the next step to start.", "running");
  if (ANALYSTS.has(current.name)) {
    return { label: `${current.name} inspecting the plan`, detail: "Reading recorded evidence through its allowed tools.", tone: "running", animate: live, node: current.name };
  }
  if (current.name === "run_experiment") return { ...benchmark(events, current.startTs), tone: "running", animate: live, node: current.name };
  return {
    label: NODE_LABEL[current.name] ?? current.name,
    detail: NODE_DETAIL[current.name] ?? "Step in progress.",
    tone: "running",
    animate: live,
    node: current.name,
  };
}
