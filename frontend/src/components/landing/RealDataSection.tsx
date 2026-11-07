import { LpIcon } from "./LpIcon";
import { Reveal } from "./Reveal";

/* Values pinned in the workload registry and checked on every load (backend/src/querycure/workloads/registry.py). */
const LEDGER = [
  ["Transaction lines", "1,067,371"],
  ["Sum of quantity", "10,608,492"],
  ["Sum of quantity × unit price", "19,287,250.568"],
  ["Lines without a customer id", "243,007"],
  ["Lines without a description", "4,382"],
] as const;

const STEPS = [
  ["Pinned by content", "The reference carries the first 12 hex digits of the file's SHA-256. The full digest is checked before anything is written to a database."],
  ["Loaded as published", "Duplicates, cancellations, negative quantities and missing customer ids are kept. One transaction, streamed with COPY, with no server file access."],
  ["Reconciled or rolled back", "Row count, sums and NULL counts must equal the pinned values. Any difference rolls the whole load back."],
  ["Ready to investigate", "A sandbox template is built once, locally. Three registered queries cover a customer's newest lines, the lines of an invoice, and totals in a date window."],
] as const;

/** A concrete workload on real data. Every number here is pinned in the registry; nothing on this section is a measurement. */
export function RealDataSection() {
  return (
    <section className="sec rd" id="data" style={{ paddingTop: 120, paddingBottom: 40 }}>
      <div className="wrap">
        <Reveal className="sec-head center">
          <p className="eyebrow">Real data</p>
          <h2>
            Real data, <span>loaded exactly as published.</span>
          </h2>
          <p className="rd-lede">QueryCure supports the UCI Online Retail II dataset: 1,067,371 real invoice lines, loaded exactly as published and checked against pinned totals before it can be used.</p>
        </Reveal>
        <div className="rd-grid">
          <Reveal>
            <ol className="rd-steps">
              {STEPS.map(([title, body], i) => (
                <li key={title}>
                  <span className="rd-n mono">{String(i + 1).padStart(2, "0")}</span>
                  <div>
                    <h3>{title}</h3>
                    <p>{body}</p>
                  </div>
                </li>
              ))}
            </ol>
          </Reveal>
          <Reveal className="rd-ledger">
            <div className="rd-lh">
              <span className="tag">
                <LpIcon name="database" size={12} />
                online_retail_ii@v1:data=b3471c34b273
              </span>
              <span className="eyebrow">Pinned values</span>
            </div>
            <dl>
              {LEDGER.map(([k, v]) => (
                <div key={k}>
                  <dt>{k}</dt>
                  <dd className="mono">{v}</dd>
                </div>
              ))}
            </dl>
            <p className="rd-lf">Checked on every load. A mismatch rolls the load back.</p>
          </Reveal>
        </div>
        <div className="rd-notes">
          <span className="tag">
            <LpIcon name="lock" size={12} />
            The file stays on your machine.
          </span>
          <span className="tag">Provisioning and query workload supported · not yet benchmarked for performance</span>
        </div>
        <p className="rd-cite">
          Chen, D. (2012). <i>Online Retail II</i>. UCI Machine Learning Repository, CC BY 4.0.{" "}
          <a className="mono" href="https://doi.org/10.24432/C5CG6D" target="_blank" rel="noopener noreferrer">
            doi.org/10.24432/C5CG6D
          </a>
          . Converted from the published workbook; rows are kept as published.
        </p>
      </div>
    </section>
  );
}
