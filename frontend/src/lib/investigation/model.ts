import type { RunDetail } from "@/lib/api/types";
import { TERMINAL } from "@/lib/events/runEvents";

/** The run header's model line, from what the run records. An experiment replay re-measures an
 * approved experiment in the sandbox and never calls a model (REPLAY_ENGINE §8.2), so its missing
 * model is not "not assigned yet"; a finished run that recorded none used none. */
export function runModelLabel(run: Pick<RunDetail, "kind" | "status" | "llmModel" | "llmProvider">): string {
  if (run.llmModel) return `${run.llmModel} via ${run.llmProvider}`;
  if (run.kind === "experiment_replay") return "No model calls · Sandbox replay";
  return TERMINAL.has(run.status) ? "No model used" : "Model not assigned yet";
}
