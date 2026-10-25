import { Icon } from "@/components/ui/Icon";
import type { Finding, FindingsResponse } from "@/lib/api/types";
import { agentLabel } from "@/lib/investigation/agents";
import type { StepMatch } from "@/lib/investigation/links";
import { ClaimBadge } from "./ClaimBadge";
import { EvidenceChip } from "./EvidenceChip";

/** Jumps to the trace row that recorded this claim; says so when no event carries its key. */
function ShowStep({ match, onShowStep }: { match: StepMatch; onShowStep: (spanId: string) => void }) {
  if (match.status === "missing") {
    return (
      <span className="ml-auto text-xs text-muted" title="No trace event carries this key (an older run, or events still loading).">
        Step not recorded
      </span>
    );
  }
  return (
    <button type="button" onClick={() => onShowStep(match.spanId)} className="qc-btn-ghost ml-auto px-2 py-0.5 text-xs">
      <Icon name="node" size={12} />
      Show step{match.matches > 1 ? ` (1 of ${match.matches})` : ""}
    </button>
  );
}

export function FindingsPanel({
  data,
  onEvidence,
  activeEvidence,
  stepFor,
  onShowStep,
}: {
  data: FindingsResponse | undefined;
  onEvidence: (id: string) => void;
  activeEvidence: string | null;
  stepFor?: (key: string) => StepMatch;
  onShowStep?: (spanId: string) => void;
}) {
  const step = (key: string) => (stepFor && onShowStep ? <ShowStep match={stepFor(key)} onShowStep={onShowStep} /> : null);
  if (!data || (data.hypotheses.length === 0 && data.findings.length === 0)) {
    return <p className="qc-panel p-6 text-muted">No findings yet.</p>;
  }
  const byAgent = data.findings.reduce<Record<string, Finding[]>>((acc, f) => {
    (acc[f.agent] ??= []).push(f);
    return acc;
  }, {});
  const chips = (ids: string[]) =>
    ids.map((id) => <EvidenceChip key={id} id={id} onOpen={onEvidence} active={id === activeEvidence} />);
  return (
    <div className="flex flex-col gap-6">
      <section aria-labelledby="hypotheses-heading">
        <h2 id="hypotheses-heading" className="mb-2 text-lg font-semibold">
          Hypotheses
        </h2>
        {data.hypotheses.length === 0 ? (
          <p className="text-sm text-muted">No hypotheses were produced.</p>
        ) : (
          <ol className="flex flex-col gap-3">
            {data.hypotheses.map((h) => (
              <li key={h.key} data-claim={h.key} tabIndex={-1} className="qc-panel scroll-mt-24 p-4">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-xs text-muted">#{h.rank}</span>
                  <span className="font-mono text-xs">{h.category}</span>
                  <ClaimBadge confidence={h.confidence} />
                  {step(h.key)}
                </div>
                <p className="mt-2">{h.statement}</p>
                <div className="mt-2 flex flex-wrap items-center gap-1 text-xs text-muted">
                  Supporting: {chips(h.supportingEvidence)}
                  {(h.contradictingEvidence ?? []).length > 0 ? (
                    <> · Contradicting: {chips(h.contradictingEvidence ?? [])}</>
                  ) : null}
                </div>
                {h.uncertaintyNotes ? <p className="mt-2 text-sm text-muted">Uncertain: {h.uncertaintyNotes}</p> : null}
                <p className="mt-1 text-xs text-muted">Verify by: {h.verificationMethod.replace("_", " ")}</p>
              </li>
            ))}
          </ol>
        )}
      </section>
      <section aria-labelledby="findings-heading">
        <h2 id="findings-heading" className="mb-2 text-lg font-semibold">
          Findings by agent
        </h2>
        {Object.entries(byAgent).map(([agent, findings]) => (
          <div key={agent} className="mb-4">
            <h3 className="mb-1 qc-eyebrow">{agentLabel(agent)}</h3>
            <ul className="flex flex-col gap-2">
              {findings.map((f) => (
                <li key={f.key} data-claim={f.key} tabIndex={-1} className="scroll-mt-24 rounded-md border border-border bg-surface p-3">
                  <div className="flex flex-wrap items-start gap-2">
                    <p className="font-medium">
                      {f.title} <span className="font-mono text-[11px] text-muted">({f.severity})</span>
                    </p>
                    {step(f.key)}
                  </div>
                  <p className="text-sm">{f.detail}</p>
                  <div className="mt-1 flex flex-wrap gap-1">{chips(f.evidenceIds)}</div>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </section>
    </div>
  );
}
