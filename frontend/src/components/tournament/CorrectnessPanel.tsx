import { Icon, type IconName } from "@/components/ui/Icon";
import type { ExperimentResult } from "@/lib/benchmark/analysis";
import { correctnessView, type CorrectnessStatus } from "@/lib/benchmark/correctness";
import { REASON_TEXT } from "@/lib/report/labels";

const OUTCOME: Record<CorrectnessStatus, { icon: IconName; label: string; tone: string }> = {
  passed: { icon: "check", label: "Same rows as the baseline on every param set", tone: "text-verified" },
  failed: { icon: "xCircle", label: "Results differ from the baseline", tone: "text-rejected" },
  inconclusive: { icon: "alert", label: "Correctness could not be decided", tone: "text-inconclusive" },
  not_reached: { icon: "alert", label: "Not checked: the candidate stopped at an earlier gate", tone: "text-muted" },
  not_evaluated: { icon: "alert", label: "Not checked: no rule verdict recorded", tone: "text-muted" },
};

const yesNo = (v: boolean | null, yes: string, no: string) => (v === null ? "unknown" : v ? yes : no);
const short = (h: string | null) => (h ? h.slice(0, 12) : "—");

/** UI_UX §3.8: recorded result fingerprints and the correctness gate, never "equivalent". */
export function CorrectnessPanel({ result, arm }: { result: ExperimentResult; arm: string }) {
  const v = correctnessView(result, arm);
  const o = OUTCOME[v.outcome.status];
  return (
    <section aria-label={`Result correctness · ${arm}`} className="flex flex-col gap-2 rounded-md border border-border bg-surface-2 p-3 text-sm">
      <h3 className="font-semibold">Result correctness</h3>
      <p className={`flex items-start gap-2 ${o.tone}`}>
        <Icon name={o.icon} size={14} className="mt-0.5 shrink-0" />
        <span>
          {o.label}
          {v.outcome.code ? (
            <span className="text-muted">
              {" "}
              · {REASON_TEXT[v.outcome.code] ?? v.outcome.code} (<span className="font-mono text-xs">{v.outcome.code}</span>)
            </span>
          ) : null}
        </span>
      </p>
      {v.outcome.detail ? <p className="text-xs text-muted">Recorded detail: {v.outcome.detail}. Only the first failing param set is recorded.</p> : null}
      <p className="text-xs text-muted">{v.orderRule}</p>
      <div className="overflow-x-auto" tabIndex={0} role="region" aria-label="Result fingerprints table">
        <table className="w-full min-w-[560px] text-left text-xs">
          <caption className="sr-only">Result fingerprints of the baseline and {arm} per param set</caption>
          <thead className="font-mono text-[11px] uppercase text-muted">
            <tr>
              <th className="py-1 pr-2">Param set</th>
              <th className="py-1 pr-2">Rows (base / cand.)</th>
              <th className="py-1 pr-2">Same rows</th>
              <th className="py-1 pr-2">Same order</th>
              <th className="py-1 pr-2">Repeatable</th>
              <th className="py-1">Row hash (base / cand.)</th>
            </tr>
          </thead>
          <tbody>
            {v.rows.map((r) => (
              <tr key={r.paramSet} className="border-t border-border align-top">
                <td className="py-1 pr-2 font-mono">{r.paramSet}</td>
                <td className="py-1 pr-2 font-mono">
                  {r.baselineRows ?? "—"} / {r.candidateRows ?? "—"}
                  {r.truncated ? <span className="block font-sans text-inconclusive">over the hash cap: not fully compared</span> : null}
                </td>
                <td className="py-1 pr-2">{r.sameRows === null ? "unknown · no successful execution" : yesNo(r.sameRows, "yes", "no")}</td>
                <td className="py-1 pr-2">{yesNo(r.sameOrder, "yes", "no")}</td>
                <td className="py-1 pr-2">
                  {yesNo(r.baselineConsistent, "yes", "no")} / {yesNo(r.candidateConsistent, "yes", "no")}
                </td>
                <td className="py-1 font-mono">
                  <span aria-label={`baseline row hash ${r.baselineMultiset ?? "not recorded"}`} title={r.baselineMultiset ?? undefined}>
                    {short(r.baselineMultiset)}
                  </span>
                  {" / "}
                  <span aria-label={`candidate row hash ${r.candidateMultiset ?? "not recorded"}`} title={r.candidateMultiset ?? undefined}>
                    {short(r.candidateMultiset)}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-muted">
        Same rows means the same row count and the same hash of every returned row, on the tested data and parameters. It is
        not a proof that the two queries are equivalent on other data.
      </p>
    </section>
  );
}
