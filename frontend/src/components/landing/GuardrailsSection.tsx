import { LpIcon, type LpIconName } from "./LpIcon";
import { Reveal } from "./Reveal";

const SECURITY_DOC = "https://github.com/yuvrajsatyapal/QueryCure/blob/main/docs/architecture/SECURITY.md";

type Guard = { icon: LpIconName; tone: "read" | "approval" | "sandbox" | "verified"; title: string; body: string; fine: string };

const GUARDS: Guard[] = [
  {
    icon: "eye",
    tone: "read",
    title: "Your database is only read",
    body: "Live inspection uses plain EXPLAIN in a read-only transaction with short timeouts. It never runs EXPLAIN ANALYZE, and the AI never receives a database connection.",
    fine: "Inspection only",
  },
  {
    icon: "hand",
    tone: "approval",
    title: "No candidate runs without approval",
    body: "You see the exact SQL, its target and its risk before any candidate runs. Declining everything still produces a report.",
    fine: "Every decision is recorded with the exact SQL it covered.",
  },
  {
    icon: "lock",
    tone: "sandbox",
    title: "Candidates run in a disposable copy",
    body: "Each candidate is measured in its own throwaway database clone, one experiment at a time, as a restricted role limited to an allowlist of statements. In the local setup the sandbox server has no outbound network.",
    fine: "Your database is not touched.",
  },
  {
    icon: "shieldCheck",
    tone: "verified",
    title: "Verified means audited",
    body: "Fixed code decides verdicts, and the AI can only make one weaker. A result counts as verified only after its audit has run. If the audit is skipped or interrupted, the candidate stays inconclusive and the report says why.",
    fine: "No audit, no verified recommendation.",
  },
];

const LIMITS = [
  ["Scope", "A verdict covers the tested workload, parameters and sandbox, not every workload."],
  ["Your database", "QueryCure proposes SQL. It never applies a change to a database you own."],
  ["Replay", "Replay re-checks stored fingerprints for consistency. It does not prove authenticity."],
] as const;

/** The safety and approval model, up front: what is read, what needs a person, what is isolated, what "verified" requires. */
export function GuardrailsSection() {
  return (
    <section className="sec gr" id="safety" style={{ paddingTop: 104, paddingBottom: 24 }}>
      <div className="wrap">
        <Reveal className="sec-head center">
          <p className="eyebrow">Safety model</p>
          <h2>
            A person approves every experiment. <span>Rules decide what counts.</span>
          </h2>
          <p>The AI can investigate, suggest and explain. It cannot run candidate SQL on its own, and it cannot call a result verified.</p>
        </Reveal>
        <ul className="gr-grid">
          {GUARDS.map((g) => (
            <li key={g.title} className={`gr-card gr-${g.tone}`}>
              <Reveal>
                <span className="gr-ic">
                  <LpIcon name={g.icon} size={18} />
                </span>
                <h3>{g.title}</h3>
                <p>{g.body}</p>
                <p className="gr-fine">{g.fine}</p>
              </Reveal>
            </li>
          ))}
        </ul>
        <Reveal className="gr-limits">
          <dl>
            {LIMITS.map(([k, v]) => (
              <div key={k}>
                <dt className="eyebrow">{k}</dt>
                <dd>{v}</dd>
              </div>
            ))}
          </dl>
          <a className="gr-more" href={SECURITY_DOC}>
            Read the security model <LpIcon name="arrowRight" size={13} />
          </a>
        </Reveal>
      </div>
    </section>
  );
}
