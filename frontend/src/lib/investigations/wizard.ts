/* Mode rules for the guided New investigation flow (UI_UX §3.14). The request body is the one the
 * pre-Pass-3 form sent; the server still enforces every rule, this only keeps the UI from offering a
 * mode the chosen plan source cannot satisfy. */
import type { CreateInvestigationInput, ParamSetInput } from "@/lib/api/types";

export type PlanSource = "upload" | "live" | "workload" | "none";
export type Mode = "offline" | "live_inspection" | "sandbox_benchmark";

export interface SourceChoice {
  source: PlanSource;
  connectionId?: string;
  workloadId?: string;
}

export interface ModeOption {
  mode: Mode;
  available: boolean;
  reason?: string;
}

export function modeOptions(choice: SourceChoice): ModeOption[] {
  const live = choice.source === "live" && Boolean(choice.connectionId);
  const sandbox = choice.source === "workload" && Boolean(choice.workloadId);
  return [
    { mode: "offline", available: true },
    live
      ? { mode: "live_inspection", available: true }
      : { mode: "live_inspection", available: false, reason: "Choose a connection in Plan source." },
    sandbox
      ? { mode: "sandbox_benchmark", available: true }
      : { mode: "sandbox_benchmark", available: false, reason: "Choose a demo workload in Plan source." },
  ];
}

/** The chosen mode if the source allows it, else the strongest mode the source supports. */
export function resolveMode(chosen: Mode | null, choice: SourceChoice): Mode {
  const options = modeOptions(choice);
  if (chosen && options.find((o) => o.mode === chosen)?.available) return chosen;
  return [...options].reverse().find((o) => o.available)?.mode ?? "offline";
}

export function buildCreateInput(input: {
  title: string;
  objective: string;
  query: string;
  paramSets: ParamSetInput[];
  mode: Mode;
  source: SourceChoice;
  planArtifactSha256?: string;
  preAuthorize?: boolean;
}): CreateInvestigationInput {
  const { mode, source } = input;
  return {
    title: input.title,
    objective: input.objective,
    modes: [mode],
    query: input.query,
    paramSets: input.paramSets,
    ...(mode === "live_inspection" && source.connectionId ? { connectionId: source.connectionId } : {}),
    ...(mode === "sandbox_benchmark" && source.workloadId
      ? { workloadId: source.workloadId, preAuthorizeDemoSandbox: input.preAuthorize ?? false }
      : {}),
    ...(mode === "offline" && source.source === "upload" && input.planArtifactSha256
      ? { planArtifactSha256: input.planArtifactSha256 }
      : {}),
  };
}
