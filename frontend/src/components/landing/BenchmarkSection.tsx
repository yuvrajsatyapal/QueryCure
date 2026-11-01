"use client";

import { useState, type ReactNode } from "react";
import { ILLUSTRATIVE_BENCH as B, logPosition, pct, median, mulberry32, quantile } from "@/lib/landing/bench";
import { LpIcon } from "./LpIcon";
import { Reveal } from "./Reveal";

const LAT = [0.5, 50] as const;
const SPD = [0.5, 10] as const;
const f = (v: number) => v.toFixed(2);

function Term({ children, tip }: { children: ReactNode; tip: string }) {
  return (
    <span className="term" tabIndex={0}>
      {children}
      <span className="tip" role="tooltip">
        {tip}
      </span>
    </span>
  );
}

/** One arm on the latency axis: whisker, interquartile box, every sample, median. */
export function ArmRow({ name, sub, data, color, hidden, seed, delayBase }: { name: string; sub: string; data: number[]; color: string; hidden?: boolean; seed: number; delayBase?: number }) {
  const r = mulberry32(seed);
  const q1 = quantile(data, 0.25);
  const q3 = quantile(data, 0.75);
  const mn = Math.min(...data);
  const mx = Math.max(...data);
  const tops = data.map(() => 14 + Math.floor(r() * 5) * 9);
  return (
    <div className="axis-row">
      <div className="lbl-arm" style={{ color: color === "var(--muted)" ? "var(--ink)" : color }}>
        {name}
        <small>{sub}</small>
      </div>
      <div className={`plot${hidden ? " arm-hidden" : ""}`}>
        {[0.5, 1, 2, 5, 10, 20, 50].map((t) => (
          <span key={t} className="grid-v" style={{ left: pct(logPosition(t, LAT)) }} />
        ))}
        <span className="floor" style={{ left: pct(logPosition(B.transportFloorMs, LAT)) }} />
        <span className="whisk" style={{ left: pct(logPosition(mn, LAT)), width: pct(logPosition(mx, LAT) - logPosition(mn, LAT)) }} />
        <span
          className="box"
          style={{ left: pct(logPosition(q1, LAT)), width: pct(logPosition(q3, LAT) - logPosition(q1, LAT)), borderColor: color, backgroundColor: `color-mix(in srgb,${color} 10%,transparent)` }}
        />
        {data.map((v, k) => (
          <span
            key={k}
            className={`dot${delayBase === undefined ? "" : " in"}`}
            style={{ left: pct(logPosition(v, LAT)), top: tops[k], backgroundColor: color, animationDelay: delayBase === undefined ? undefined : `${k * 70 + delayBase}ms` }}
          />
        ))}
        <span className="med" style={{ left: pct(logPosition(median(data), LAT)) }} />
      </div>
    </div>
  );
}

/** The latency chart: both arms on a log axis, plus (unless compact) the speed-up interval against the rule. */
export function BenchChart({ compact = false, progressive = false, show = { base: true, cand: true, ci: true } }: { compact?: boolean; progressive?: boolean; show?: { base: boolean; cand: boolean; ci: boolean } }) {
  const ticks = [0.5, 1, 2, 5, 10, 20, 50];
  const summary = `Illustrative benchmark. Baseline median ${f(B.baselineMedian)} ms, candidate median ${f(B.candidateMedian)} ms, ${B.n} samples each. Median ratio ${f(B.ratio)} times, 95% bootstrap interval ${f(B.ciLow)} to ${f(B.ciHigh)}, above the 1.10 minimum effect.`;
  return (
    <div className="chart" role="img" aria-label={summary}>
      <span className="illus chart-badge">◆ Illustrative data</span>
      <ArmRow name="Baseline" sub={`median ${f(B.baselineMedian)} ms`} data={B.baseline} color="var(--muted)" hidden={!show.base && !compact} seed={3} delayBase={progressive ? 0 : undefined} />
      <ArmRow name="Candidate" sub={`median ${f(B.candidateMedian)} ms`} data={B.candidate} color="var(--accent)" hidden={!show.cand && !compact} seed={5} delayBase={progressive ? 35 : undefined} />
      <div className="axis-row" style={{ height: 22 }}>
        <div />
        <div className="plot" style={{ height: 22 }}>
          {ticks.map((t) => (
            <span key={t} className="tick" style={{ left: pct(logPosition(t, LAT)), top: 4 }}>
              {t}
            </span>
          ))}
        </div>
      </div>
      <div className="axis-row" style={{ height: 18 }}>
        <div />
        <div style={{ fontSize: 11, color: "var(--muted)" }}>
          latency, ms · log scale ·{" "}
          <span style={{ color: "var(--hypothesis)" }}>
            ┆ <Term tip="The fastest a round trip to the database can be. Timings close to it are mostly network, not the query.">transport floor</Term> {B.transportFloorMs} ms
          </span>
        </div>
      </div>
      {!compact && show.ci && (
        <>
          <div style={{ height: 1, background: "var(--border)", margin: "14px 0" }} />
          <div className="axis-row">
            <div className="lbl-arm">
              Speed-up<small>median ratio, 95% CI</small>
            </div>
            <div className="plot">
              {[0.5, 1, 2, 5, 10].map((t) => (
                <span key={t} className="grid-v" style={{ left: pct(logPosition(t, SPD)) }} />
              ))}
              <span className="thr" style={{ left: pct(logPosition(0.95, SPD)), borderColor: "var(--rejected)" }} />
              <span className="thr" style={{ left: pct(logPosition(1.1, SPD)), borderColor: "var(--verified)" }} />
              <span className="ref1" style={{ left: pct(logPosition(1, SPD)) }} />
              <span
                className="ci"
                style={{ left: pct(logPosition(B.ciLow, SPD)), width: pct(logPosition(B.ciHigh, SPD) - logPosition(B.ciLow, SPD)), backgroundColor: "color-mix(in srgb,var(--accent) 60%,transparent)" }}
              />
              <span className="ci-pt" style={{ left: pct(logPosition(B.ratio, SPD)) }} />
            </div>
          </div>
          <div className="axis-row" style={{ height: 22 }}>
            <div />
            <div className="plot" style={{ height: 22 }}>
              {[0.5, 1, 2, 5, 10].map((t) => (
                <span key={t} className="tick" style={{ left: pct(logPosition(t, SPD)), top: 4 }}>
                  {t}×
                </span>
              ))}
            </div>
          </div>
          <div className="axis-row">
            <div />
            <div style={{ fontSize: 11, color: "var(--muted)", display: "flex", flexWrap: "wrap", gap: 12 }}>
              <span>│ 1× no change</span>
              <span style={{ color: "var(--verified)" }}>
                ┆ <Term tip="The smallest speed-up worth calling an improvement. The whole range has to clear it.">min_effect</Term> 1.10×
              </span>
              <span style={{ color: "var(--rejected)" }}>┆ max_regression 0.95×</span>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

const TOGGLES = [
  ["base", "Baseline", "var(--muted)"],
  ["cand", "Candidate optimization", "var(--accent)"],
  ["ci", "Show uncertainty", undefined],
  ["det", "Show measurement details", undefined],
] as const;

export function BenchmarkSection() {
  const [on, setOn] = useState({ base: true, cand: true, ci: true, det: false });
  const rows: [string, number[], number][] = [
    ["Baseline", B.baseline, B.baselineCv],
    ["Candidate", B.candidate, B.candidateCv],
  ];
  return (
    <section className="sec" id="bench" style={{ padding: "8px 0 0" }}>
      <div className="wrap">
        <Reveal className="sec-head center how-head">
          <p className="eyebrow">Zoomed in · H1, measured</p>
          <h2>
            <span className="l1" style={{ color: "inherit" }}>Not just a speed-up number.</span> <span>A distribution, an interval, and a rule.</span>
          </h2>
          <p>
            One fast run can be luck. QueryCure times both versions across repeated runs, keeps every measurement, and reports an{" "}
            <Term tip="A 95% confidence interval: the range the true speed-up very likely falls in, given the samples.">interval</Term> for the speed-up. A fixed rule, not the AI,
            determines whether the result qualifies as a verified improvement.
          </p>
        </Reveal>
        <Reveal className="bm">
          <div>
            <div className="bm-ctrls" role="group" aria-label="Chart options">
              {TOGGLES.map(([k, label, color]) => (
                <button key={k} type="button" className="tog" aria-pressed={on[k]} style={k === "base" ? { color: "var(--muted)" } : undefined} onClick={() => setOn((s) => ({ ...s, [k]: !s[k] }))}>
                  <span className="sw" style={color && k === "cand" ? { color } : undefined} />
                  {label}
                </button>
              ))}
            </div>
            <BenchChart show={on} />
            <div className={`details-wrap${on.det ? " open" : ""}`}>
              <div>
                <div style={{ marginTop: 12, border: "1px solid var(--border)", borderRadius: 10, overflow: "auto" }}>
                  <table className="dt">
                    <caption className="sr">Measurement details</caption>
                    <thead>
                      <tr>
                        {["Arm", "n", "min", "p25", "median", "p75", "p95", "CV"].map((h, i) => (
                          <th key={h} className={i ? "n" : undefined}>
                            {h}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map(([n, d, cv]) => (
                        <tr key={n}>
                          <td style={{ fontFamily: "var(--font-sans)" }}>{n}</td>
                          <td className="n">{d.length}</td>
                          <td className="n">{f(Math.min(...d))}</td>
                          <td className="n">{f(quantile(d, 0.25))}</td>
                          <td className="n">{f(median(d))}</td>
                          <td className="n">{f(quantile(d, 0.75))}</td>
                          <td className="n">{f(quantile(d, 0.95))}</td>
                          <td className="n">{f(cv)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          </div>
          <div className="bm-side">
            <div className="stat">
              <div className="k">Median ratio</div>
              <div className="v">
                {f(B.ratio)}
                <small>×</small>
              </div>
              <div className="mono" style={{ fontSize: 12, color: "var(--muted)" }}>
                95% <Term tip="Confidence interval: the range the true speed-up very likely falls in, given these samples.">CI</Term> {f(B.ciLow)}×–{f(B.ciHigh)}× · 2,000 resamples
              </div>
            </div>
            <div className="plain">
              <LpIcon name="bulb" size={15} />
              <span>
                <b>In plain terms:</b> the candidate was about {B.ratio.toFixed(1)}× faster, and the true speed-up very likely lies between {B.ciLow.toFixed(1)}× and{" "}
                {B.ciHigh.toFixed(1)}×.
              </span>
            </div>
            <div className="stat">
              <div className="k">Correctness</div>
              <div style={{ marginTop: 8 }}>
                <span className="pill t-verified">
                  <LpIcon name="checkCircle" size={12} />
                  Rows identical · 3 / 3
                </span>
              </div>
            </div>
            <div className="stat">
              <div className="k">Verdict</div>
              <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 8 }}>
                <span className="pill t-verified" style={{ width: "max-content" }}>
                  <LpIcon name="checkCircle" size={12} />
                  Verified · within tested scope
                </span>
                <span style={{ fontSize: 12.5, color: "var(--muted)" }}>CI lower bound clears min_effect and results match. Scope: this workload, these parameters, this sandbox.</span>
              </div>
            </div>
            <span className="illus" style={{ alignSelf: "flex-start" }}>
              ◆ Synthetic samples (seeded PRNG)
            </span>
          </div>
        </Reveal>
      </div>
    </section>
  );
}
