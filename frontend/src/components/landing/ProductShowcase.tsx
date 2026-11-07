"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode, type RefObject } from "react";
import { ILLUSTRATIVE_BENCH as B } from "@/lib/landing/bench";
import { SAMPLE_SQL_PLAIN, Check, SampleSql, Ddl, EvChip, Spin } from "./atoms";
import { BenchChart } from "./BenchmarkSection";
import { useReducedMotion } from "./hooks";
import { LpIcon } from "./LpIcon";
import { Logo } from "@/components/ui/Logo";
import { Reveal } from "./Reveal";
import { useCountUp, useRoll, useStream, useSteps, useTyped } from "./timeline";

const f2 = (v: number) => v.toFixed(2);
const d = (n: number) => ({ "--d": n }) as CSSProperties;

/* The workspace replica: an illustrative fixture, not a recorded run. Each stage is a self-contained body
 * whose scripted timeline restarts on mount; the simulated pointer is shared and cleared on every change. */
type Cursor = { click: (target: RefObject<HTMLElement | null>, at: number, onClick: () => void) => void };
type StageProps = { reduced: boolean; cursor: Cursor; onApproved: () => void };

const SPANS = [
  { n: "intake", st: 0, ev: 2 },
  { n: "collect_context", st: 1, ev: 5 },
  { n: "explain_plan", st: 1, tool: 1 },
  { n: "supervisor_plan", st: 2 },
  { n: "query_analyzer", st: 2, ev: 3 },
  { n: "get_plan_node", st: 2, tool: 1 },
  { n: "index_strategist", st: 2, ev: 2 },
  { n: "list_indexes", st: 2, tool: 1 },
  { n: "synthesize_hypotheses", st: 2, ev: 4 },
  { n: "optimization_engineer", st: 3, ev: 1 },
  { n: "validate_sql", st: 3, tool: 1 },
  { n: "approval_gate", st: 3, approval: 1 },
  { n: "run_experiment", st: 4, ev: 6 },
  { n: "benchmark_auditor", st: 5, ev: 3 },
  { n: "write_report", st: 6 },
] as { n: string; st: number; ev?: number; tool?: number; approval?: number }[];
const SC = ["Query", "Plan", "Agents", "Sandbox", "Benchmark", "Verify", "Report"];
const STAGE_MS = [4400, 4000, 5600, 5000, 4600, 4800, 4200];

function QueryStage({ reduced, cursor }: StageProps) {
  const [typed, done] = useTyped(SAMPLE_SQL_PLAIN, 450, reduced);
  const start = useRef<HTMLButtonElement>(null);
  const [starting, setStarting] = useState(false);
  useEffect(() => cursor.click(start, 2250, () => setStarting(true)), [cursor]);
  return (
    <div className="seq">
      <div style={d(0)} className="eyebrow">
        New investigation
      </div>
      <div style={{ ...d(1), margin: "10px 0 14px", fontSize: 15, fontWeight: 500 }}>Why is the customer orders page slow?</div>
      <div style={d(2)} className="panel">
        <div className="panel-h">
          <LpIcon name="code" size={14} />
          Query<span className="cap">illustrative orders workload · PostgreSQL 17</span>
        </div>
        <div className="panel-b">
          <div className="code" style={{ minHeight: 122 }}>
            {done ? <SampleSql /> : <>{typed}<span className="caret" /></>}
          </div>
        </div>
      </div>
      <div style={{ ...d(3), display: "flex", justifyContent: "flex-end", marginTop: 12 }}>
        <button ref={start} className={`btn btn-primary btn-sm${starting ? " pressed ripple" : ""}`} tabIndex={-1} aria-hidden="true">
          {starting ? <><span className="spin" style={{ display: "inline-flex" }}><LpIcon name="loader" size={13} /></span>Starting…</> : <><LpIcon name="play" size={12} />Start investigation</>}
        </button>
      </div>
      <div style={d(21)} className="app-foot">
        <span className="tag">
          <LpIcon name="checkCircle" size={12} />
          parsed · SQLGlot
        </span>
        <span className="tag">art_5c1e…a91f · query</span>
        <span className="tag">art_d40b…77c2 · plan.json</span>
      </div>
      <div style={{ ...d(23), marginTop: 14, fontSize: 12.5, color: "var(--muted)" }}>Inputs validated and fingerprinted. Nothing has touched a database yet.</div>
    </div>
  );
}

function PlanStage({ reduced }: StageProps) {
  const rows = useCountUp(1999953, 550, 1300, reduced);
  return (
    <div className="seq">
      <div style={{ ...d(0), position: "relative", overflow: "hidden" }} className="panel">
        <div className="scanline" />
        <div className="panel-h">
          <LpIcon name="node" size={14} />
          Execution plan<span className="cap mono">3 nodes · ANALYZE · 1 expensive</span>
        </div>
        <div className="plan-row h">
          <span>Node</span>
          <span>Est. rows</span>
          <span>Actual</span>
          <span>Self time</span>
        </div>
        {(
          [
            ["Limit", "20", "20", "2%", false],
            ["  Sort · top-N heapsort", "51", "47", "6%", false],
            ["    Seq Scan on orders", "51", "47", "92%", true],
          ] as const
        ).map(([n, e, a, w, hot]) => (
          <div key={n} className={`plan-row${hot ? " hot" : ""}`}>
            <span>
              {n}
              {hot && (
                <>
                  {" "}
                  <span className="tag" style={{ height: 18 }}>
                    expensive
                  </span>
                </>
              )}
            </span>
            <span>{e}</span>
            <span>{a}</span>
            <div className="selfbar">
              <i style={{ width: w }} />
            </div>
          </div>
        ))}
        <div className="panel-b" style={{ fontSize: 12.5, color: "var(--muted)" }}>
          Filter <span className="mono">customer_id = $1</span> · rows removed by filter:{" "}
          <span className="mono" style={{ color: "var(--ink)" }}>
            {rows.toLocaleString("en-US")}
          </span>
        </div>
      </div>
      <div style={d(12)} className="app-foot">
        <EvChip id="ev_31a7" />
        <span style={{ fontSize: 12.5, color: "var(--muted)" }}>plan node 3 reads the whole table to find 47 rows</span>
      </div>
      <div style={d(14)} className="app-foot">
        <EvChip id="ev_8c02" />
        <span style={{ fontSize: 12.5, color: "var(--muted)" }}>
          orders has an index on <span className="mono">(status)</span> only
        </span>
      </div>
    </div>
  );
}

function AgentCard({ k, name, text, evs, reduced }: { k: number; name: string; text: string; evs: ReactNode; reduced: boolean }) {
  const [shown, done] = useStream(text, 350 + k * 1150, reduced);
  return (
    <div className="agent" style={d(k)}>
      <div className="nm">
        <LpIcon name="bot" size={14} />
        {name}
        <span className="ast" style={{ marginLeft: "auto", display: "inline-flex" }}>
          {done ? <Check size={13} /> : <Spin />}
        </span>
      </div>
      <p style={{ minHeight: 57 }}>{shown}</p>
      <div className="evs" style={{ opacity: done ? 1 : 0, transition: "opacity .4s" }}>
        {evs}
      </div>
    </div>
  );
}

function AgentsStage({ reduced }: StageProps) {
  return (
    <div className="seq">
      <div className="agents3">
        <AgentCard k={0} name="Query Analyzer" text="The Seq Scan reads all 2M rows to return 47, then sorts them." evs={<EvChip id="ev_31a7" />} reduced={reduced} />
        <AgentCard
          k={1}
          name="Index Strategist"
          text="No index starts with customer_id, so neither the filter nor the ordering can use one."
          evs={
            <>
              <EvChip id="ev_8c02" /> <EvChip id="ev_2f19" />
            </>
          }
          reduced={reduced}
        />
        <div className="agent" style={{ ...d(2), borderStyle: "dashed", color: "var(--muted)" }}>
          <div className="nm">
            <LpIcon name="bot" size={14} />
            Workload Investigator
          </div>
          <p>Not routed: no live connection in this run (Mode B off).</p>
          <div>
            <span className="tag">skipped</span>
          </div>
        </div>
      </div>
      <div style={{ ...d(21), margin: "18px 0 8px" }} className="eyebrow">
        Hypotheses
      </div>
      <div className="hyp" style={d(22)}>
        <span className="pill t-hypothesis">
          <LpIcon name="dashed" size={12} />
          Hypothesis · high
        </span>
        <span className="txt">A composite index on (customer_id, created_at DESC) removes both the scan and the sort.</span>
        <EvChip id="ev_31a7" />
        <EvChip id="ev_8c02" />
      </div>
      <div className="hyp" style={{ ...d(24), marginTop: 8 }}>
        <span className="pill t-hypothesis">
          <LpIcon name="dashed" size={12} />
          Hypothesis · low
        </span>
        <span className="txt">Planner statistics on orders are stale.</span>
        <EvChip id="ev_2f19" />
      </div>
    </div>
  );
}

const SANDBOX = ["fresh sandbox", "seed workload", "apply DDL", "warm up", "measure"];
function SandboxStage({ reduced, cursor, onApproved }: StageProps) {
  const btn = useRef<HTMLButtonElement>(null);
  const [approvedAt, setApprovedAt] = useState(reduced ? 0 : -1);
  useEffect(
    () =>
      cursor.click(btn, 1100, () => {
        setApprovedAt(performance.now());
        onApproved();
      }),
    [cursor, onApproved],
  );
  return (
    <div className="seq">
      <div className="approval" style={d(0)}>
        <div className="panel-h" style={{ borderColor: "var(--border)" }}>
          <LpIcon name="hand" size={14} />
          Approval required
          <span className={`pill ${approvedAt >= 0 ? "t-verified" : "t-approval"}`} style={{ marginLeft: 8 }}>
            {approvedAt >= 0 ? "Approved" : "Waiting on you"}
          </span>
          <span className="cap">{approvedAt >= 0 ? "approval granted" : "expires in 14:52"}</span>
        </div>
        <div className="panel-b">
          <div className="code">
            <Ddl />
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "120px 1fr", gap: "6px 12px", fontSize: 12.5, marginTop: 12 }}>
            <span style={{ color: "var(--muted)" }}>Target</span>
            <span className="mono">sandbox_db · illustrative orders table, seed 42</span>
            <span style={{ color: "var(--muted)" }}>Your database</span>
            <span>not touched</span>
            <span style={{ color: "var(--muted)" }}>Risk</span>
            <span>Index build on 2M seeded rows</span>
          </div>
          <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 14 }}>
            <button className="btn btn-secondary btn-sm" tabIndex={-1} aria-hidden="true">
              Decline
            </button>
            <button ref={btn} className={`btn btn-primary btn-sm${approvedAt >= 0 && !reduced ? " pressed ripple" : ""}`} tabIndex={-1} aria-hidden="true">
              {approvedAt >= 0 ? <><LpIcon name="checkCircle" size={13} />Approved</> : "Approve selected"}
            </button>
          </div>
        </div>
      </div>
      <SandboxPipe started={approvedAt >= 0} reduced={reduced} />
    </div>
  );
}

const PIPE_T = [350, 730, 1110, 1490, 1870];
function SandboxPipeRun({ reduced }: { reduced: boolean }) {
  const n = useSteps(PIPE_T, reduced);
  return (
    <>
      {SANDBOX.map((s, k) => (
        <span key={s} style={{ display: "contents" }}>
          {k > 0 && "→"}
          <span className={n > k ? "on" : undefined}>{s}</span>
        </span>
      ))}
    </>
  );
}
function SandboxPipe({ started, reduced }: { started: boolean; reduced: boolean }) {
  return (
    <div style={{ ...d(2), marginTop: 16 }} className="pipe-mini">
      {started ? (
        <SandboxPipeRun reduced={reduced} />
      ) : (
        SANDBOX.map((s, k) => (
          <span key={s} style={{ display: "contents" }}>
            {k > 0 && "→"}
            <span>{s}</span>
          </span>
        ))
      )}
    </div>
  );
}

function BenchmarkStage({ reduced }: StageProps) {
  const n = useCountUp(B.n, 150, B.n * 70, reduced);
  return (
    <div className="seq">
      <div style={d(0)} className="panel">
        <div className="panel-h">
          <LpIcon name="gauge" size={14} />
          Latency · param set p1
          <span className="cap mono">
            n = {n} / {B.n} per arm
          </span>
        </div>
        <div className="panel-b" style={{ position: "relative", paddingTop: 38 }}>
          <BenchChart compact progressive={!reduced} />
        </div>
      </div>
      <div style={d(22)} className="app-foot">
        <span className="tag">baseline median {f2(B.baselineMedian)} ms</span>
        <span className="tag" style={{ color: "var(--accent)" }}>
          candidate median {f2(B.candidateMedian)} ms
        </span>
        <EvChip id="ev_b6d0" />
      </div>
    </div>
  );
}

const AUDIT: [string, string][] = [
  ["Result rows identical to baseline", "3 / 3 param sets"],
  ["Plan uses the candidate index", "Index Scan · plan diff"],
  ["CI lower bound above min_effect", `${f2(B.ciLow)}× > 1.10×`],
  ["Sample quality within max_cv", `CV ${f2(B.candidateCv)} · max 0.25`],
];
const AUDIT_T = [450, 1070, 1690, 2310];
function VerifyStage({ reduced }: StageProps) {
  const n = useSteps(AUDIT_T, reduced);
  return (
    <div className="seq">
      <div style={d(0)} className="eyebrow">
        Benchmark Auditor · deterministic checks first
      </div>
      <div className="checks" style={{ ...d(1), marginTop: 8 }}>
        {AUDIT.map(([t, r], k) => (
          <div key={t} className="check">
            <span className="chk-i">
              {n > k ? <Check size={15} /> : <Spin />}
            </span>
            {t}
            <span className="r" style={{ opacity: n > k ? 1 : 0, transition: "opacity .3s" }}>
              {r}
            </span>
          </div>
        ))}
      </div>
      <div style={{ ...d(22), display: "flex", flexWrap: "wrap", gap: 10, alignItems: "center", marginTop: 18 }}>
        <span className="pill t-verified" style={{ height: 26, fontSize: 13 }}>
          <LpIcon name="checkCircle" size={14} />
          Verified · within tested scope
        </span>
        <span style={{ fontSize: 12.5, color: "var(--muted)" }}>
          Every gate passed in this one experiment. Scope: this workload, these 3 param sets, this sandbox. The auditor can downgrade this, never upgrade it.
        </span>
      </div>
    </div>
  );
}

function ReportStage({ reduced }: StageProps) {
  const [hash, sealed] = useRoll("manifest sha256:", "9f1c…e04a", 500, 1000, reduced);
  return (
    <div className="seq">
      <div className="vh" style={d(0)}>
        <div>
          <span className="pill t-verified">
            <LpIcon name="checkCircle" size={12} />
            verified_recommendation
          </span>
          <h3 style={{ fontSize: 17 }}>A composite index removes the sequential scan</h3>
          <div style={{ fontSize: 12.5, color: "var(--muted)" }}>Tested in a sandbox on a seeded workload, not on your data.</div>
        </div>
        <div className="m">
          <div className="v">{f2(B.ratio)}×</div>
          <div className="mono" style={{ fontSize: 11, color: "var(--muted)" }}>
            {f2(B.ciLow)}×–{f2(B.ciHigh)}× · illustrative
          </div>
        </div>
      </div>
      <div style={d(3)} className="app-foot">
        <span className="tag" style={{ opacity: sealed ? 1 : 0, transition: "opacity .4s" }}>
          <LpIcon name="lock" size={12} />
          sealed · report-builder@2
        </span>
        <span className="tag">{hash}</span>
        <button className="btn btn-secondary btn-sm" tabIndex={-1} aria-hidden="true">
          Export Markdown
        </button>
        <button className="btn btn-secondary btn-sm" tabIndex={-1} aria-hidden="true">
          Verify report
        </button>
      </div>
    </div>
  );
}

const STAGES = [QueryStage, PlanStage, AgentsStage, SandboxStage, BenchmarkStage, VerifyStage, ReportStage];

function Glyph({ s, i }: { s: (typeof SPANS)[number]; i: number }) {
  const faint = (
    <span style={{ color: "var(--faint)", display: "inline-flex" }}>
      <LpIcon name="wrench" size={12} />
    </span>
  );
  if (s.st < i || i === 6) return s.tool ? faint : <Check size={13} />;
  if (s.approval)
    return (
      <span style={{ color: "var(--approval)", display: "inline-flex" }}>
        <LpIcon name="hand" size={13} />
      </span>
    );
  if (s.tool) return faint;
  return <span className="orb live" />;
}

export function ProductShowcase() {
  const reduced = useReducedMotion();
  const appRef = useRef<HTMLDivElement>(null);
  const bodyRef = useRef<HTMLDivElement>(null);
  const cursorRef = useRef<HTMLDivElement>(null);
  const stepsRef = useRef<HTMLDivElement>(null);
  const timers = useRef<number[]>([]);
  const [i, setI] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [approved, setApproved] = useState(false);
  const [gen, setGen] = useState(0);
  const playingRef = useRef(false);

  // A simulated pointer travels to the target and "clicks" it; reduced motion applies the click at once.
  const cursor = useCallback<Cursor["click"]>(
    (target, at, onClick) => {
      if (reduced) {
        onClick();
        return;
      }
      const cur = cursorRef.current;
      const body = bodyRef.current;
      timers.current.push(
        window.setTimeout(() => {
          const el = target.current;
          if (!el || !cur || !body) return;
          const b = body.getBoundingClientRect();
          const r = el.getBoundingClientRect();
          cur.style.transition = "none";
          cur.style.transform = `translate(${b.width * 0.78}px,${b.height - 36}px)`;
          cur.classList.add("show");
          void cur.offsetWidth;
          cur.style.transition = "";
          cur.style.transform = `translate(${r.left - b.left + r.width * 0.55}px,${r.top - b.top + r.height * 0.45}px)`;
        }, at),
        window.setTimeout(() => target.current && onClick(), at + 1050),
        window.setTimeout(() => cur?.classList.remove("show"), at + 1800),
      );
    },
    [reduced],
  );
  const stableCursor = useMemo<Cursor>(() => ({ click: cursor }), [cursor]);
  const onApproved = useCallback(() => setApproved(true), []);

  const go = useCallback((n: number) => {
    timers.current.forEach(clearTimeout);
    timers.current = [];
    cursorRef.current?.classList.remove("show");
    setApproved(false);
    setI(n);
    setGen((g) => g + 1);
  }, []);

  // Step progress: the current step's bar fills over its duration while playing; pausing freezes it.
  useEffect(() => {
    const bars = [...(stepsRef.current?.querySelectorAll<HTMLElement>(".prog") ?? [])];
    bars.forEach((p, j) => {
      p.style.transition = "none";
      p.style.width = j < i ? "100%" : "0";
    });
    const cur = bars[i];
    if (!playing || !cur) return;
    const raf = requestAnimationFrame(() => {
      cur.style.transition = `width ${STAGE_MS[i]}ms linear`;
      cur.style.width = "100%";
    });
    const t = window.setTimeout(() => {
      if (i < SC.length - 1) go(i + 1);
      else setPlaying(false);
    }, STAGE_MS[i]);
    return () => {
      cancelAnimationFrame(raf);
      clearTimeout(t);
      const w = getComputedStyle(cur).width;
      cur.style.transition = "none";
      cur.style.width = w;
    };
  }, [i, playing, gen, go]);

  // Autoplay starts the first time the app is a third on screen and pauses when it leaves.
  useEffect(() => {
    playingRef.current = playing;
  }, [playing]);
  useEffect(() => {
    const el = appRef.current;
    if (!el) return;
    let started = false;
    const io = new IntersectionObserver(
      (es) => {
        const v = es[0]?.isIntersecting ?? false;
        if (v && !started && !reduced) {
          started = true;
          setPlaying(true);
          setGen((g) => g + 1);
        } else if (!v && playingRef.current) setPlaying(false);
      },
      { threshold: 0.35 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [reduced]);
  useEffect(() => () => timers.current.forEach(clearTimeout), []);

  const play = () => {
    if (playing) return setPlaying(false);
    if (i === SC.length - 1) go(0);
    setPlaying(true);
  };
  const final = i === 6;
  const pill = final ? (
    <span className="pill t-verified">
      <LpIcon name="checkCircle" size={12} />
      Completed
    </span>
  ) : i === 3 && !approved ? (
    <span className="pill t-approval">
      <LpIcon name="hand" size={12} />
      Approval required
    </span>
  ) : (
    <span className="pill t-running">
      <span className="orb live" />
      Running
    </span>
  );
  const firstOfStage = SPANS.findIndex((s) => s.st === i);
  const lastOfStage = SPANS.map((s) => s.st).lastIndexOf(i);
  const Stage = STAGES[i] ?? QueryStage;
  const meters = [9, 8, 7].map((w) => Math.min(6 + (i + 1) * w, 72) / 100);

  return (
    <section className="sec" id="product">
      <div className="showcase-bg" />
      <div className="wrap">
        <Reveal className="sec-head center how-head">
          <p className="eyebrow">The workspace · illustrative walkthrough</p>
          <h2>
            <span className="l1" style={{ color: "inherit" }}>Watch an investigation from first query to sealed report.</span> <span>Every step is visible, cited and verifiable.</span>
          </h2>
        </Reveal>
        <div className="app reveal in" ref={appRef}>
          <div className="app-grid">
            <aside className="app-side" aria-hidden="true">
              <div className="s-brand">
                <Logo size={18} />
                QueryCure
              </div>
              <div className="s-search">
                <LpIcon name="search" size={13} />
                Search<span className="mono">⌘K</span>
              </div>
              <div className="s-item">
                <LpIcon name="plus" size={14} />
                New investigation
              </div>
              <div className="s-item">
                <LpIcon name="grid" size={14} />
                Dashboard
              </div>
              <div className="s-item">
                <LpIcon name="clock" size={14} />
                History
              </div>
              <div className="s-group">Active runs</div>
              <div className="s-run">
                <span className="orb" style={{ background: final ? "var(--verified)" : "var(--running)" }} />
                Slow orders lookup
              </div>
              <div className="s-group">Workspace</div>
              <div className="s-item on">
                <LpIcon name="search" size={14} />
                Investigations
              </div>
              <div className="s-item">
                <LpIcon name="database" size={14} />
                Connections
              </div>
              <div className="s-item">
                <LpIcon name="replay" size={14} />
                Replay
              </div>
              <div style={{ marginTop: "auto" }} className="s-item">
                <LpIcon name="gear" size={14} />
                Settings
              </div>
            </aside>
            <div className="app-main">
              <div className="app-head">
                <div style={{ minWidth: 0 }}>
                  <div className="crumb">Investigations › #1</div>
                  <div className="app-title">Slow orders lookup</div>
                </div>
                {pill}
                <span className="tag">Mode A · offline</span>
                <span className="tag">Mode C · sandbox</span>
                <span className="illus">◆ Illustrative run</span>
                <div className="meters" aria-hidden="true">
                  {["LLM calls", "Tokens", "Tool calls"].map((m, k) => (
                    <div key={m} className="meter">
                      {m}
                      <div className="bar">
                        <i style={{ transform: `scaleX(${meters[k]})`, transition: `transform ${STAGE_MS[i]}ms linear` }} />
                      </div>
                    </div>
                  ))}
                </div>
              </div>
              <div className="app-body" ref={bodyRef}>
                <div className="trace">
                  <div className="trace-h">
                    <span>TRACE</span>
                    <span>evidence</span>
                  </div>
                  <ol style={{ listStyle: "none", margin: 0, padding: 0 }} aria-label="Run trace">
                    {SPANS.map((s, j) => {
                      const show = s.st <= i;
                      return (
                        <li
                          key={s.n}
                          className={`span${s.tool ? " tool" : ""}${show ? " show" : ""}${j === lastOfStage ? " cur" : ""}`}
                          style={{ paddingLeft: s.tool ? 34 : 14, transitionDelay: show && s.st === i ? `${(j - firstOfStage) * 260}ms` : "0ms" }}
                        >
                          <span className="g">{show && <Glyph s={s} i={i} />}</span>
                          <span>{s.n}</span>
                          {s.ev ? <span className="ev">{s.ev} ev</span> : null}
                        </li>
                      );
                    })}
                  </ol>
                </div>
                <div className="detail" aria-live="off">
                  <div className="detail-inner" key={`${i}-${gen}`}>
                    <Stage reduced={reduced} cursor={stableCursor} onApproved={onApproved} />
                  </div>
                </div>
                <div className="cursor" ref={cursorRef} aria-hidden="true">
                  <svg width="20" height="20" viewBox="0 0 24 24">
                    <path d="M5 3l14 8-6.2 1.6L9.6 19z" fill="#fff" stroke="#111" strokeWidth="1.3" strokeLinejoin="round" />
                  </svg>
                </div>
              </div>
            </div>
          </div>
        </div>
        <div className="ctrls">
          <button type="button" className="btn btn-secondary btn-sm" onClick={play}>
            <LpIcon name={playing ? "pause" : "play"} size={13} />
            {playing ? "Pause" : i === SC.length - 1 ? "Play again" : "Play investigation"}
          </button>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={() => {
              go(0);
              setPlaying(!reduced);
            }}
          >
            <LpIcon name="replay" size={14} />
            Replay
          </button>
          <div className="steps" ref={stepsRef} role="group" aria-label="Select stage">
            {SC.map((n, j) => (
              <button
                key={n}
                type="button"
                className={`step${j < i ? " done" : ""}`}
                aria-current={j === i ? "step" : undefined}
                onClick={() => {
                  setPlaying(false);
                  go(j);
                }}
              >
                {j + 1} · {n}
                <span className="prog" />
              </button>
            ))}
          </div>
          <span className="illus" style={{ marginLeft: "auto" }}>
            ◆ Illustrative workspace
          </span>
        </div>
      </div>
    </section>
  );
}
