"use client";

import { useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore, type CSSProperties, type KeyboardEvent, type ReactNode } from "react";
import { ILLUSTRATIVE_BENCH as B, logPosition, pct } from "@/lib/landing/bench";
import { DEMO_SQL_PLAIN, Check, DemoSql, Ddl, EvChip, Spin } from "./atoms";
import { BenchChart } from "./BenchmarkSection";
import { useInView, useReducedMotion } from "./hooks";
import { LpIcon } from "./LpIcon";
import { Reveal } from "./Reveal";
import { useRoll, useStream, useSteps, useTyped } from "./timeline";

const SPD = [0.5, 10] as const;
const f2 = (v: number) => v.toFixed(2);
type Body = (p: { reduced: boolean }) => ReactNode;
type Stage = { t: string; d: string; eye: string; tone?: "approval"; body: Body; foot: string; ms: number };

const InputsBody: Body = ({ reduced }) => {
  const [typed, done] = useTyped(DEMO_SQL_PLAIN, 200, reduced);
  return (
    <>
      <div className="hw-two">
        <div className="hw-blk">
          <div className="hw-lbl">
            <LpIcon name="code" size={12} />
            query.sql
          </div>
          <div className="code" style={{ minHeight: 122 }}>
            {done ? <DemoSql /> : <>{typed}<span className="caret" /></>}
          </div>
        </div>
        <div className="hw-blk">
          <div className="hw-lbl">
            <LpIcon name="node" size={12} />
            EXPLAIN plan
          </div>
          <div className="hw-plan seq">
            <div style={{ "--d": 9 } as CSSProperties}>
              <span>Limit</span>
              <i style={{ "--w": "2%" } as CSSProperties} />
            </div>
            <div style={{ "--d": 11 } as CSSProperties}>
              <span>&nbsp;&nbsp;Sort · top-N</span>
              <i style={{ "--w": "6%" } as CSSProperties} />
            </div>
            <div className="hot" style={{ "--d": 13 } as CSSProperties}>
              <span>&nbsp;&nbsp;&nbsp;&nbsp;Seq Scan on orders</span>
              <i style={{ "--w": "92%" } as CSSProperties} />
            </div>
          </div>
        </div>
      </div>
      <div className="hw-sup">
        <div className="hw-lbl">
          <LpIcon name="lock" size={12} />
          Stored as fingerprinted artifacts
        </div>
        <div className="hw-arts">
          {[["query.sql", "5c1e…a91f"], ["plan.json", "d40b…77c2"], ["schema.json", "77e1…3b08"]].map(([n, h], k) => (
            <span key={n} className="hw-art" style={{ "--k": k } as CSSProperties}>
              <b>{n}</b>
              <span className="mono">sha256:{h}</span>
            </span>
          ))}
        </div>
      </div>
    </>
  );
};

function Agent({ name, text, ev, start, reduced }: { name: string; text: string; ev: string; start: number; reduced: boolean }) {
  const [shown, done] = useStream(text, start, reduced);
  return (
    <div className={`hw-ag${done ? " done" : ""}`}>
      <span className="hw-ast">{done ? <Check /> : <Spin />}</span>
      <span className="hw-an">{name}</span>
      <span className="hw-at">{shown}</span>
      <span className="hw-ae">
        <EvChip id={ev} />
      </span>
    </div>
  );
}

const INVESTIGATE_T = [2900];
const InvestigateBody: Body = ({ reduced }) => {
  const hyp = useSteps(INVESTIGATE_T, reduced) > 0;
  return (
    <>
      <div className="hw-ags">
        <Agent name="Query Analyzer" text="The Seq Scan reads all 2M rows to return 47." ev="ev_31a7" start={250} reduced={reduced} />
        <Agent name="Index Strategist" text="No index starts with customer_id." ev="ev_8c02" start={1500} reduced={reduced} />
        <div className="hw-ag off">
          <span className="hw-ast" style={{ color: "var(--faint)", display: "inline-flex" }}>
            <LpIcon name="dashed" size={13} />
          </span>
          <span className="hw-an">Workload Investigator</span>
          <span className="hw-at">Not routed: no live connection in this run.</span>
        </div>
      </div>
      <div className={`hw-hyp${hyp ? " on" : ""}`}>
        <span className="pill t-hypothesis sm">
          <LpIcon name="dashed" size={11} />
          Hypothesis · high
        </span>
        <span>A composite index on (customer_id, created_at) removes the scan and the sort.</span>
        <span className="hw-ae">
          <EvChip id="ev_31a7" />
          <EvChip id="ev_8c02" />
        </span>
      </div>
      <div className="hw-sup">
        <div className="hw-lbl">
          <LpIcon name="gauge" size={12} />
          Run budget · hard limits, checked between steps
        </div>
        <div className="hw-meters">
          {([["LLM calls", 4, 12, ""], ["Tool calls", 6, 24, ""], ["Tokens", 18, 60, "k"]] as const).map(([n, v, m, u], k) => (
            <div key={n} className="hw-m">
              <span>{n}</span>
              <span className="mono">
                {v}
                {u} / {m}
                {u}
              </span>
              <i style={{ "--p": `${Math.round((v / m) * 100)}%`, "--k": k } as CSSProperties} />
            </div>
          ))}
        </div>
      </div>
    </>
  );
};

const APPROVE_T = [1900];
const ApproveBody: Body = ({ reduced }) => {
  const pressed = useSteps(APPROVE_T, reduced) > 0;
  return (
    <div className="hw-gate">
      <h4>Review the proposed SQL</h4>
      <div className="code">
        <Ddl />
      </div>
      <div className="hw-lock">
        <LpIcon name="lock" size={13} />
        Runs only in a disposable sandbox · your database is not touched
      </div>
      <div className="hw-meta">
        <span>Target</span>
        <b className="mono">sandbox_db · orders_demo, seed 42</b>
        <span>Risk</span>
        <b>Index build on 2M seeded rows</b>
        <span>Expires</span>
        <b className="mono">14:52</b>
      </div>
      <div className="hw-acts">
        <span className="hw-dec">Decline</span>
        <span className={`hw-cta${pressed ? " ok pressed" : ""}`} aria-hidden="true">
          <LpIcon name={pressed ? "checkCircle" : "hand"} size={15} />
          {pressed ? "Demo approval granted" : "Approve experiment"}
        </span>
      </div>
      <p className="hw-fine">Scripted demo: this button is pressed automatically; nothing is approved or run here.</p>
    </div>
  );
};

const SANDBOX_STEPS = ["fresh sandbox", "seed workload", "apply SQL", "warm up", "measure"];
const EXPERIMENT_T = [150, 410, 670, 930, 1190, 1300];
const ExperimentBody: Body = ({ reduced }) => {
  const n = useSteps(EXPERIMENT_T, reduced);
  return (
    <>
      <div className="hw-res">
        <div>
          <span className="hw-rl">Baseline median</span>
          <b className="mono">{f2(B.baselineMedian)} ms</b>
        </div>
        <span className="hw-arrow">
          <LpIcon name="arrowRight" size={16} />
        </span>
        <div>
          <span className="hw-rl">Candidate median</span>
          <b className="mono" style={{ color: "var(--accent)" }}>
            {f2(B.candidateMedian)} ms
          </b>
        </div>
        <div className="hw-x">
          <b className="mono">≈{f2(B.ratio)}×</b>
          <span>faster · illustrative sandbox test</span>
        </div>
      </div>
      <div className="hw-sb">
        {SANDBOX_STEPS.map((l, k) => (
          <span key={l} style={{ display: "contents" }}>
            {k > 0 && (
              <i>
                <LpIcon name="arrowRight" size={11} />
              </i>
            )}
            <span className={n > k ? "on" : undefined}>{l}</span>
          </span>
        ))}
      </div>
      <div className="hw-chart">{n >= 6 && <BenchChart compact progressive={!reduced} />}</div>
    </>
  );
};

const VERIFY_CHECKS: [string, string][] = [
  ["Result rows identical to baseline", "3 / 3 param sets"],
  ["Plan uses the new index", "Index Scan"],
  ["Speed-up clears the minimum effect", `${f2(B.ciLow)}× > 1.10×`],
  ["Timings stable enough", `CV ${f2(B.candidateCv)} · max 0.25`],
];
const VERIFY_T = [300, 820, 1340, 1860, 2500];
const VerifyBody: Body = ({ reduced }) => {
  const n = useSteps(VERIFY_T, reduced);
  return (
    <>
      <div className="hw-checks">
        {VERIFY_CHECKS.map(([t, r], k) => (
          <div key={t} className={`hw-chk${n > k ? " on" : ""}`}>
            <span className="hw-ci">{n > k ? <Check /> : <Spin />}</span>
            <span>{t}</span>
            <span className="hw-cr">{r}</span>
          </div>
        ))}
      </div>
      <div className={`hw-verdict${n >= 5 ? " on" : ""}`}>
        <span className="pill t-verified" style={{ height: 28, fontSize: 13 }}>
          <LpIcon name="checkCircle" size={14} />
          Verified · within tested scope
        </span>
        <p>
          Every check passed and the whole range clears the 1.10× minimum (chart below). The claim holds for this workload, these parameter sets and this sandbox. Had the range
          dipped under, or the timings been too noisy, the verdict would be inconclusive.
        </p>
      </div>
      <div className="hw-sup">
        <div className="hw-lbl">
          <LpIcon name="gauge" size={12} />
          Speed-up range vs the rule · illustrative
        </div>
        <div className="hw-iv">
          <span className="hw-ivg" style={{ left: pct(logPosition(1, SPD)) }} />
          <span className="hw-ivt" style={{ left: pct(logPosition(1.1, SPD)) }} />
          <span className="hw-ivb" style={{ left: pct(logPosition(B.ciLow, SPD)), width: pct(logPosition(B.ciHigh, SPD) - logPosition(B.ciLow, SPD)) }} />
          <span className="hw-ivp" style={{ left: pct(logPosition(B.ratio, SPD)) }} />
          {[0.5, 1, 2, 5, 10].map((t) => (
            <span key={t} className="hw-ivx" style={{ left: pct(logPosition(t, SPD)) }}>
              {t}×
            </span>
          ))}
        </div>
        <div className="hw-ivl">
          <span>│ 1× no change</span>
          <span style={{ color: "var(--verified)" }}>┆ 1.10× minimum effect</span>
          <span style={{ color: "var(--accent)" }}>
            ▬ {f2(B.ciLow)}×–{f2(B.ciHigh)}× measured range
          </span>
        </div>
      </div>
    </>
  );
};

const OUTCOMES: [string, string][] = [
  ["Verified recommendation", "A change was measured and passed every rule."],
  ["Unverified recommendations", "Ideas that couldn't be measured in this run."],
  ["No action needed", "Nothing material was worth changing."],
  ["Inconclusive", "The evidence wasn't strong enough either way."],
];
const REPORT_T = [2100];
const ReportBody: Body = ({ reduced }) => {
  const [digest, sealed] = useRoll("sha256:", "9f1c…e04a", 300, 900, reduced);
  const replayed = useSteps(REPORT_T, reduced) > 0;
  return (
    <div className="hw-rep">
      <div className="hw-rh">
        <span className="pill t-verified sm">
          <LpIcon name="checkCircle" size={11} />
          Verified recommendation
        </span>
        <h4>A composite index removes the sequential scan</h4>
        <p>
          Measured {f2(B.ratio)}× faster ({f2(B.ciLow)}×–{f2(B.ciHigh)}×) in the sandbox ·{" "}
          <span className="illus" style={{ padding: "2px 6px" }}>
            ◆ illustrative
          </span>
        </p>
      </div>
      <div className="hw-int">
        <span className="hw-ii">
          <LpIcon name="lock" size={14} />
        </span>
        <div>
          <div className="mono hw-dig">{digest}</div>
          <div className="hw-is">
            {replayed ? (
              <>
                <span style={{ color: "var(--verified)" }}>Integrity check passed against stored digests</span> · 0 LLM calls · experiments not re-run
              </>
            ) : sealed ? (
              "Sealed · manifest, events and report digests stored"
            ) : (
              "Fingerprinting the report…"
            )}
          </div>
        </div>
        <span className={`xa-b${replayed ? " pressed" : ""}`} aria-hidden="true">
          <LpIcon name="replay" size={11} />
          Replay report · integrity only
        </span>
      </div>
      <div className="hw-lbl" style={{ margin: "4px 0 0" }}>
        Every run ends in exactly one of these four outcomes
      </div>
      <ul className="hw-outs">
        {OUTCOMES.map(([o, h], k) => (
          <li key={o} className={k ? undefined : "cur"}>
            <b>
              {o}
              {k ? null : <em>this run</em>}
            </b>
            <span>{h}</span>
          </li>
        ))}
      </ul>
    </div>
  );
};

const INPUTS: Stage = { t: "Inputs", d: "Your SQL, its plan, the schema", eye: "Inputs", body: InputsBody, foot: "Inputs are validated and fingerprinted. A live connection is only ever read with plain EXPLAIN.", ms: 3800 };
const STAGES: Stage[] = [
  INPUTS,
  { t: "Investigate", d: "Specialist agents, every claim cited", eye: "Investigation", body: InvestigateBody, foot: "Agents exchange typed, cited findings. A claim without evidence is dropped before anyone sees it.", ms: 4400 },
  { t: "Approve", d: "You review the exact SQL", eye: "Approval gate", tone: "approval", body: ApproveBody, foot: "Nothing runs until you approve. Declining everything still produces a report.", ms: 3600 },
  { t: "Experiment", d: "Measured in a throwaway sandbox", eye: "Sandbox experiment", body: ExperimentBody, foot: "Baseline and candidate run under identical conditions. Every timing is kept, not just the best one.", ms: 4400 },
  { t: "Verify", d: "Fixed rules decide, not the AI", eye: "Verification", body: VerifyBody, foot: "A recommendation is only called verified when correctness and statistics both pass.", ms: 4200 },
  { t: "Report", d: "Sealed, explained, replayable", eye: "Sealed report", body: ReportBody, foot: "Report replay re-checks stored evidence only. To measure again, start an experiment replay; to rethink the problem, a re-investigation.", ms: 4400 },
];

const narrowQuery = "(max-width: 900px)";
const subscribeNarrow = (cb: () => void) => {
  const mq = window.matchMedia(narrowQuery);
  mq.addEventListener("change", cb);
  return () => mq.removeEventListener("change", cb);
};

export function HowItWorks() {
  const reduced = useReducedMotion();
  const narrow = useSyncExternalStore(subscribeNarrow, () => window.matchMedia(narrowQuery).matches, () => false);
  const boxRef = useRef<HTMLDivElement>(null);
  const stepsRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLOListElement>(null);
  const measureRef = useRef<HTMLDivElement>(null);
  const visible = useInView(boxRef, 0.3);
  const [i, setI] = useState(0);
  const [auto, setAuto] = useState(true);
  const [run, setRun] = useState(0);
  const [minH, setMinH] = useState<number | undefined>(undefined);
  const autoOn = auto && !reduced;

  // Autoplay advances while the section is on screen; it stops at the last stage.
  useEffect(() => {
    if (!autoOn || !visible) return;
    const id = window.setTimeout(() => {
      if (i < STAGES.length - 1) setI(i + 1);
      else setAuto(false);
    }, STAGES[i]?.ms ?? 4000);
    return () => clearTimeout(id);
  }, [autoOn, visible, i, run]);

  // The first stage restarts its timeline when the section first comes into view.
  useEffect(() => {
    const el = boxRef.current;
    if (!el) return;
    const io = new IntersectionObserver(
      (es) => {
        if (!es[0]?.isIntersecting) return;
        setRun((r) => r + 1);
        io.disconnect();
      },
      { threshold: 0.3 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  // Rail: from the first dot to the last; the fill and pulse reach the active stage.
  useLayoutEffect(() => {
    const steps = stepsRef.current;
    const list = listRef.current;
    if (!steps || !list) return;
    const place = () => {
      const dots = [...list.querySelectorAll<HTMLElement>(".hw-dot")];
      const first = dots[0];
      const last = dots[dots.length - 1];
      const active = dots[i];
      if (!first || !last || !active) return;
      const b = steps.getBoundingClientRect();
      const cy = (d: HTMLElement) => d.getBoundingClientRect().top + d.offsetHeight / 2 - b.top;
      const rail = steps.querySelector<HTMLElement>(".hw-rail");
      const fill = steps.querySelector<HTMLElement>(".hw-rail i");
      const pulse = steps.querySelector<HTMLElement>(".hw-pulse");
      if (!rail || !fill || !pulse) return;
      const y0 = cy(first);
      Object.assign(rail.style, { top: `${y0}px`, height: `${cy(last) - y0}px`, left: `${first.getBoundingClientRect().left + first.offsetWidth / 2 - b.left - 1}px` });
      const h = cy(active) - y0;
      fill.style.height = `${h}px`;
      pulse.style.top = `${h}px`;
      pulse.classList.toggle("on", i > 0);
    };
    place();
    const ro = new ResizeObserver(place);
    ro.observe(steps);
    return () => ro.disconnect();
  }, [i, narrow]);

  // Lock the preview body to its tallest stage (measured from a hidden final-state copy).
  useLayoutEffect(() => {
    const m = measureRef.current;
    if (!m) return;
    const measure = () => {
      const pb = boxRef.current?.querySelector<HTMLElement>(".hw-prev .hw-pb");
      if (pb) m.style.width = `${pb.clientWidth}px`;
      setMinH(Math.max(...[...m.children].map((c) => (c as HTMLElement).scrollHeight)));
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(m);
    return () => ro.disconnect();
  }, [narrow]);

  const select = (n: number) => {
    setAuto(false);
    setI(n);
    setRun((r) => r + 1);
  };
  const onListKey = (e: KeyboardEvent) => {
    const d = ({ ArrowDown: 1, ArrowUp: -1 } as Record<string, number>)[e.key];
    if (!d) return;
    e.preventDefault();
    const n = Math.min(STAGES.length - 1, Math.max(0, i + d));
    select(n);
    listRef.current?.querySelectorAll<HTMLButtonElement>(".hw-row")[n]?.focus();
  };
  const end = i === STAGES.length - 1 && !autoOn;
  const onPlay = () => {
    if (autoOn) return setAuto(false);
    if (reduced) return;
    setAuto(true);
    if (i === STAGES.length - 1) {
      setI(0);
      setRun((r) => r + 1);
    }
  };
  const stage = STAGES[i] ?? INPUTS;
  const StageBody = stage.body;

  const preview = (
    <section className="hw-prev" data-tone={stage.tone ?? ""} aria-labelledby="hw-eye">
      <header className="hw-ph">
        <span className="hw-eye" id="hw-eye">
          {stage.eye}
        </span>
        <span className="illus hw-demo">◆ Scripted demo</span>
        <span className="hw-count">
          0{i + 1} / 0{STAGES.length}
        </span>
        <span className="hw-nav">
          <button type="button" className="hw-ib prev" aria-label="Previous stage" disabled={i <= 0} onClick={() => select(Math.max(0, i - 1))}>
            <LpIcon name="arrowRight" size={13} />
          </button>
          <button type="button" className="hw-ib" aria-label="Next stage" disabled={i >= STAGES.length - 1} onClick={() => select(Math.min(STAGES.length - 1, i + 1))}>
            <LpIcon name="arrowRight" size={13} />
          </button>
          <button
            type="button"
            className={`hw-pp${autoOn ? " on" : ""}`}
            aria-label={autoOn ? "Pause autoplay" : end ? "Replay from the first stage" : "Resume autoplay"}
            onClick={onPlay}
          >
            <LpIcon name={autoOn ? "pause" : end ? "replay" : "play"} size={autoOn || !end ? 11 : 12} />
            {autoOn ? "Pause" : end ? "Replay" : "Play"}
          </button>
        </span>
      </header>
      <div className="hw-pb" style={{ minHeight: minH }}>
        <div className="hw-anim" key={`${i}-${run}`}>
          <StageBody reduced={reduced} />
        </div>
      </div>
      <footer className="hw-pf">{stage.foot}</footer>
    </section>
  );

  return (
    <section className="sec" id="how" style={{ paddingTop: 40, paddingBottom: 0 }}>
      <div className="wrap">
        <Reveal className="sec-head center how-head">
          <p className="eyebrow">How it works</p>
          <h2>
            <span className="l1" style={{ color: "inherit" }}>What happens after you hand QueryCure a slow query.</span> <span>Six stages, one human gate.</span>
          </h2>
          <p>Select a stage to see it happen. Not every run reaches every stage, and not every run ends in a recommendation.</p>
        </Reveal>
        <div className="hw reveal in" ref={boxRef}>
          <div className="hw-steps" ref={stepsRef}>
            <span className="hw-rail" aria-hidden="true">
              <i />
              <b className="hw-pulse" />
            </span>
            <ol className="hw-list" ref={listRef} onKeyDown={onListKey}>
              {STAGES.map((st, n) => (
                <li key={st.t}>
                  <button type="button" className={`hw-row${n === i ? " on" : n < i ? " done" : ""}`} data-tone={st.tone} aria-current={n === i ? "step" : undefined} onClick={() => select(n)}>
                    <span className="hw-dot" />
                    <span className="hw-n">0{n + 1}</span>
                    <span className="hw-tx">
                      <span className="hw-t">{st.t}</span>
                      <span className="hw-d">{st.d}</span>
                    </span>
                  </button>
                  {narrow && n === i && preview}
                </li>
              ))}
            </ol>
          </div>
          <div className="hw-col">{!narrow && preview}</div>
        </div>
        {/* Hidden final-state copies, measured once to reserve the preview's height. */}
        <div ref={measureRef} aria-hidden="true" style={{ position: "absolute", visibility: "hidden", pointerEvents: "none", left: -9999, top: 0 }} className="hw-pb">
          {STAGES.map((st) => (
            <div key={st.t}>
              <st.body reduced />
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
