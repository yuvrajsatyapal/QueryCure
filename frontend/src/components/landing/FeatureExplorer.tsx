"use client";

import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type KeyboardEvent, type ReactNode } from "react";
import { Logo } from "@/components/ui/Logo";
import { ILLUSTRATIVE_BENCH as B, logPosition, pct, median, mulberry32, quantile } from "@/lib/landing/bench";
import { Check, EvChip, Spin } from "./atoms";
import { useInView, useReducedMotion } from "./hooks";
import { LpIcon, type LpIconName } from "./LpIcon";
import { Reveal } from "./Reveal";
import { useRoll } from "./timeline";
import { comet, flash } from "./wire";

const NS = "http://www.w3.org/2000/svg";
const LAT = [0.5, 50] as const;
const SPD = [0.5, 10] as const;

function Caption({ steps, on }: { steps: string[]; on: number }) {
  return (
    <div className="scap">
      {steps.map((t, k) => (
        <span key={t} className={k === on ? "on" : k < on ? "done" : undefined}>
          <b>{k + 1}</b>
          {t}
        </span>
      ))}
    </div>
  );
}

/* ---------- 1. Investigate ---------- */
function drawInvestigate(box: HTMLElement, reduced: boolean) {
  const svg = box.querySelector<SVGSVGElement>(".iv-svg");
  const stage = box.closest<HTMLElement>(".fx-stage");
  if (!svg || !stage) return;
  svg.replaceChildren();
  const narrow = stage.clientWidth < 640;
  box.classList.toggle("stack", narrow);
  const bx = box.getBoundingClientRect();
  const rel = (q: DOMRect) => ({ l: q.left - bx.left, r: q.right - bx.left, t: q.top - bx.top, b: q.bottom - bx.top, cx: q.left + q.width / 2 - bx.left, cy: q.top + q.height / 2 - bx.top });
  const core = box.querySelector(".iv-agent .core");
  const agent = box.querySelector(".iv-agent");
  if (!core || !agent) return;
  const C = rel(core.getBoundingClientRect());
  const A = rel(agent.getBoundingClientRect());
  const el = (tag: string, attrs: Record<string, string | number>) => {
    const e = document.createElementNS(NS, tag);
    Object.entries(attrs).forEach(([k, v]) => e.setAttribute(k, String(v)));
    svg.appendChild(e);
    return e;
  };
  // Each wire carries a glowing pulse on a loop; the far port flashes as it lands.
  let n = 0;
  const add = (d: string, g: string, ends: [number, number][]) => {
    const path = el("path", { d, class: g }) as SVGPathElement;
    const co = g === "g-src" ? "" : g === "g-bad" ? " co cb" : " co";
    ends.forEach(([x, y]) => el("circle", { cx: x, cy: y, r: 3.2, class: `port p-${g}` }));
    if (!reduced) {
      const o = { ms: 1500, gap: 1200, delay: (g === "g-src" ? 0 : 1100) + n++ * 230, cls: co.trim() };
      comet(svg, path, o);
      const end = ends[ends.length - 1];
      if (end) flash(svg, end[0], end[1], o);
    }
  };
  const srcs = [...box.querySelectorAll(".src")].map((e) => rel(e.getBoundingClientRect()));
  const cards = [...box.querySelectorAll<HTMLElement>(".fcard")];
  const tone = (e: HTMLElement) => (e.dataset.bad ? "g-bad" : "g-out");
  if (narrow) {
    const V = (x1: number, y1: number, x2: number, y2: number) => {
      const m = (y2 - y1) / 2;
      return `M${x1},${y1} C${x1},${y1 + m} ${x2},${y2 - m} ${x2},${y2}`;
    };
    srcs.forEach((S) => add(V(S.cx, S.b, C.cx, C.t), "g-src", [[S.cx, S.b], [C.cx, C.t]]));
    const out = box.querySelector(".iv-out");
    if (!out) return;
    const O = rel(out.getBoundingClientRect());
    const sx = O.l + 8;
    const yT = O.t - 14;
    const r = 10;
    cards.forEach((e) => {
      const F = rel(e.getBoundingClientRect());
      add(`M${A.cx},${A.b + 6} V${yT - r} Q${A.cx},${yT} ${A.cx - r},${yT} H${sx + r} Q${sx},${yT} ${sx},${yT + r} V${F.cy - r} Q${sx},${F.cy} ${sx + r},${F.cy} H${F.l}`, tone(e), [[F.l, F.cy]]);
    });
    return;
  }
  // Inputs converge on one point on the agent's left edge; outputs branch from one point on its right.
  const curveH = (x1: number, y1: number, x2: number, y2: number) => {
    const w = (x2 - x1) * 0.5;
    return `M${x1},${y1} C${x1 + w},${y1} ${x2 - w},${y2} ${x2},${y2}`;
  };
  srcs.forEach((S) => add(curveH(S.r, S.cy, C.l, C.cy), "g-src", [[S.r, S.cy], [C.l, C.cy]]));
  cards.forEach((e) => {
    const F = rel(e.getBoundingClientRect());
    add(curveH(C.r, C.cy, F.l, F.cy), tone(e), [[C.r, C.cy], [F.l, F.cy]]);
  });
}

function InvestigateScene({ reduced }: { reduced: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  const [ph, setPh] = useState(reduced ? 2 : 0);
  const [cap, setCap] = useState(reduced ? 2 : 0);
  const [status, setStatus] = useState(reduced ? "2 findings kept" : "reading inputs");
  const [cards, setCards] = useState<{ shell: boolean; empty: boolean }[]>(() => [0, 1, 2].map(() => ({ shell: !reduced, empty: !reduced })));
  useLayoutEffect(() => {
    const box = ref.current;
    if (!box) return;
    drawInvestigate(box, reduced);
    const ro = new ResizeObserver(() => drawInvestigate(box, reduced));
    ro.observe(box.closest(".fx-stage") ?? box);
    return () => ro.disconnect();
  }, [reduced]);
  useEffect(() => {
    if (reduced) return;
    const ids: number[] = [];
    const at = (ms: number, f: () => void) => ids.push(window.setTimeout(f, ms));
    at(900, () => setStatus("plan · schema · stats"));
    // 1. the output threads draw out, 2. each box arrives with its thread, 3. its details fill in.
    at(1700, () => {
      setPh(1);
      setCap(1);
      setStatus("citing evidence");
      ref.current?.querySelectorAll<SVGPathElement>(".iv-svg path.g-out, .iv-svg path.g-bad").forEach((p, k) => {
        const L = p.getTotalLength();
        p.style.strokeDasharray = String(L);
        p.style.strokeDashoffset = String(L);
        at(40 + k * 160, () => {
          p.style.transition = "stroke-dashoffset .6s cubic-bezier(.4,0,.2,1),stroke .4s,opacity .5s";
          p.style.strokeDashoffset = "0";
        });
        // Hand the stroke back to CSS so the rejected thread keeps its dashes.
        at(40 + k * 160 + 650, () => {
          p.style.strokeDasharray = "";
          p.style.strokeDashoffset = "";
          p.style.transition = "";
        });
      });
    });
    [0, 1, 2].forEach((k) => {
      at(1740 + k * 160 + 420, () => setCards((c) => c.map((v, j) => (j === k ? { ...v, shell: false } : v))));
      at(1740 + k * 160 + 720, () => setCards((c) => c.map((v, j) => (j === k ? { ...v, empty: false } : v))));
    });
    at(3300, () => setStatus("validating citations"));
    at(4000, () => {
      setPh(2);
      setCap(2);
      setStatus("2 findings kept");
    });
    return () => ids.forEach(clearTimeout);
  }, [reduced]);
  return (
    <div style={{ width: "100%" }}>
      <div className="iv" ref={ref} data-ph={ph}>
        <svg className="iv-svg" aria-hidden="true" />
        <div className="iv-src">
          {([["node", "Plan"], ["database", "Schema"], ["gauge", "Statistics"]] as [LpIconName, string][]).map(([i, t]) => (
            <div key={t} className="src">
              <LpIcon name={i} size={14} />
              {t}
            </div>
          ))}
        </div>
        <div className="iv-agent">
          <div className="core">
            <span className="ag-i">
              <LpIcon name="search" size={15} />
            </span>
            <span className="iv-name">Query Analyzer</span>
          </div>
          <span className="iv-st">
            <span>{ph >= 2 ? <Check size={12} /> : <span className="orb live" />}</span>
            <span>{status}</span>
          </span>
        </div>
        <div className="iv-out">
          <div className={`fcard${cards[0]?.shell ? " shell" : ""}${cards[0]?.empty ? " empty" : ""}`}>
            <div className="fc-h">
              <span className="pill t-neutral sm">
                <LpIcon name="eye" size={11} />
                Observed
              </span>
              <span className="fc-ev">
                <EvChip id="ev_31a7" />
              </span>
            </div>
            <div className="fc-t">Seq Scan on orders removes 1,999,953 rows.</div>
          </div>
          <div className={`fcard${cards[1]?.shell ? " shell" : ""}${cards[1]?.empty ? " empty" : ""}`}>
            <div className="fc-h">
              <span className="pill t-hypothesis sm">
                <LpIcon name="dashed" size={11} />
                Hypothesis · high
              </span>
              <span className="fc-ev">
                <EvChip id="ev_31a7" />
                <EvChip id="ev_8c02" />
              </span>
            </div>
            <div className="fc-t">An index on (customer_id, created_at) would remove the scan.</div>
          </div>
          <div id="ivBad" data-bad="1" className={`fcard${cards[2]?.shell ? " shell" : ""}${cards[2]?.empty ? " empty" : ""}${ph >= 2 ? " strike" : ""}`}>
            <div className="fc-h">
              {ph >= 2 ? (
                <span className="pill t-rejected sm">
                  <LpIcon name="xCircle" size={11} />
                  Removed
                </span>
              ) : (
                <span className="pill t-neutral sm">
                  <LpIcon name="help" size={11} />
                  Unsupported
                </span>
              )}
              <span className="fc-ev fc-none">no evidence</span>
            </div>
            <div className="fc-t txt">The server is probably too small for this table.</div>
          </div>
        </div>
      </div>
      <Caption steps={["Read the inputs", "Cite evidence", "Drop uncited claims"]} on={cap} />
    </div>
  );
}

/* ---------- 2. Experiment safely ---------- */
function ExperimentScene({ reduced }: { reduced: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  const [cap, setCap] = useState(reduced ? 3 : 0);
  const q = <T extends Element>(s: string) => ref.current?.querySelector<T>(s) ?? null;
  // Connectors and the refusal tag are positioned in the scene's own layout space, so they stay attached to the
  // cards while the panel's entrance transform (scale) is still animating, and after any resize or font load.
  useLayoutEffect(() => {
    const box = ref.current;
    if (!box) return;
    const place = () => {
      const T = q<HTMLElement>("[data-db='target']");
      const S = q<HTMLElement>("[data-db='sandbox']");
      const top = q<HTMLElement>(".exv-top .tag");
      const blk = q<HTMLElement>(".xtag");
      const appr = q<HTMLElement>(".xappr");
      const paths = box.querySelectorAll<SVGPathElement>(".exv-svg path");
      if (!T || !S || !top || !blk || !appr) return;
      const bx = box.getBoundingClientRect();
      const k = box.offsetWidth > 0 ? bx.width / box.offsetWidth : 1;
      const rel = (r: DOMRect) => ({ x: (r.left + r.width / 2 - bx.left) / k, top: (r.top - bx.top) / k, bottom: (r.bottom - bx.top) / k });
      const g = rel(top.getBoundingClientRect());
      const t = rel(T.getBoundingClientRect());
      const s = rel(S.getBoundingClientRect());
      const narrow = window.innerWidth <= 560;
      const route = (x2: number, y2: number) => {
        const m = (y2 - g.bottom) / 2;
        return `M${g.x},${g.bottom} C${g.x},${g.bottom + m} ${x2},${y2 - m} ${x2},${y2}`;
      };
      paths[0]?.setAttribute("d", narrow ? "" : route(t.x, t.top));
      paths[1]?.setAttribute("d", narrow ? "" : route(s.x, s.top));
      if (!narrow) Object.assign(blk.style, { left: `${t.x}px`, top: `${t.top}px` });
      // The approval card sits over the gap between QueryCure and the cards, kept inside the scene.
      const width = box.offsetWidth;
      const half = Math.min(160, width * 0.46);
      Object.assign(appr.style, { left: `${Math.min(Math.max(narrow ? width / 2 : s.x - 40, half), width - half)}px`, top: `${(g.bottom + t.top) / 2}px` });
    };
    place();
    const ro = new ResizeObserver(place);
    [box, ...Array.from(box.querySelectorAll(".exv-top .tag, [data-db]"))].forEach((e) => ro.observe(e));
    document.fonts?.ready.then(place);
    return () => ro.disconnect();
  }, []);
  // The animation only reads geometry from the DOM, so a resize re-places the connectors without restarting it.
  useEffect(() => {
    const box = ref.current;
    if (!box) return;
    const one = <T extends Element>(s: string) => box.querySelector<T>(s) as T;
    const T = one<HTMLElement>("[data-db='target']");
    const S = one<HTMLElement>("[data-db='sandbox']");
    const pk = one<HTMLElement>(".xpk");
    const blk = one<HTMLElement>(".xtag");
    const appr = one<HTMLElement>(".xappr");
    const applied = one<HTMLElement>(".xapplied");
    const apT = one<HTMLElement>("[data-x='apT']");
    const apSt = one<HTMLElement>("[data-x='apSt']");
    const apBtn = one<HTMLElement>("[data-x='apBtn']");
    const tT = one<HTMLElement>("[data-x='tT']");
    const sT = one<HTMLElement>("[data-x='sT']");
    const [pT = null, pS = null] = Array.from(box.querySelectorAll<SVGPathElement>(".exv-svg path"));
    const ids: number[] = [];
    const rafs: number[] = [];
    const at = (ms: number, f: () => void) => ids.push(window.setTimeout(f, ms));
    const along = (path: SVGPathElement | null, dur: number, done: () => void) => {
      if (!path || window.innerWidth <= 560 || reduced) return done();
      const t0 = performance.now();
      const f = (now: number) => {
        const u = Math.min(1, (now - t0) / dur);
        const e = u < 0.5 ? 2 * u * u : 1 - Math.pow(-2 * u + 2, 2) / 2;
        const pt = path.getPointAtLength(e * path.getTotalLength());
        pk.style.transform = `translate(${pt.x}px,${pt.y}px) translate(-50%,-50%)`;
        if (u < 1) rafs.push(requestAnimationFrame(f));
        else done();
      };
      rafs.push(requestAnimationFrame(f));
    };
    const reset = () => {
      [T, S].forEach((e) => e.classList.remove("hit-read", "hit-ok", "hit-bad"));
      [pT, pS].forEach((p) => p?.setAttribute("class", ""));
      blk.classList.remove("on");
      pk.className = "xpk";
      appr.classList.remove("on", "ok");
      applied.classList.remove("on");
      apT.textContent = "Approval required";
      apSt.textContent = "waiting on you";
      apBtn.textContent = "Approve";
      apBtn.classList.remove("pressed");
      tT.textContent = "target · read-only";
      sT.textContent = "disposable · seeded data";
    };
    if (reduced) {
      reset();
      T.classList.add("hit-read");
      S.classList.add("hit-ok");
      applied.classList.add("on");
      return;
    }
    const cycle = () => {
      reset();
      setCap(0);
      pT?.setAttribute("class", "lit-read");
      pk.className = "xpk read on";
      along(pT, 1300, () => {
        T.classList.add("hit-read");
        tT.textContent = "read · plan returned";
        pk.classList.remove("on");
      });
      at(2900, () => {
        reset();
        setCap(1);
        appr.classList.add("on");
        at(1300, () => {
          apBtn.classList.add("pressed");
          apBtn.textContent = "✓ Approved";
          appr.classList.add("ok");
          apT.textContent = "Approved";
          apSt.textContent = "approval";
        });
        at(2300, () => {
          appr.classList.remove("on");
          pS?.setAttribute("class", "lit");
          pk.className = "xpk ddl on";
          along(pS, 1000, () => {
            S.classList.add("hit-ok");
            applied.classList.add("on");
            sT.textContent = "applied · measuring";
            pk.classList.remove("on");
          });
        });
      });
      at(7400, () => {
        reset();
        setCap(2);
        pT?.setAttribute("class", "lit-bad");
        pk.className = "xpk bad on";
        along(pT, 1200, () => {
          pk.classList.add("shake");
          T.classList.add("hit-bad");
          blk.classList.add("on");
          at(1400, () => pk.classList.remove("on"));
        });
      });
      at(11200, cycle);
    };
    const start = requestAnimationFrame(cycle);
    return () => {
      cancelAnimationFrame(start);
      ids.forEach(clearTimeout);
      rafs.forEach(cancelAnimationFrame);
    };
  }, [reduced]);
  const li = (i: LpIconName, t: string) => (
    <li key={t}>
      <LpIcon name={i} size={13} />
      {t}
    </li>
  );
  return (
    <div style={{ width: "100%" }}>
      <div className="exv" ref={ref}>
        <svg className="exv-svg" aria-hidden="true">
          <path />
          <path />
        </svg>
        <div className="exv-top">
          <span className="tag" style={{ height: 28, color: "var(--ink)", fontSize: 12 }}>
            <Logo size={15} />
            QueryCure
          </span>
        </div>
        <div className="boundary">
          <div className="db" data-db="target">
            <div className="t">
              <LpIcon name="database" size={16} />
              Your database
            </div>
            <span className="tag" data-x="tT" style={{ width: "max-content" }}>
              target · read-only
            </span>
            <ul>
              {li("eye", "Plain EXPLAIN only, never ANALYZE")}
              {li("lock", "Read-only transaction, short timeouts")}
              {li("xCircle", "Never written to")}
            </ul>
          </div>
          <div className="wall">
            <span>NEVER MIXED</span>
          </div>
          <div className="db" data-db="sandbox">
            <div className="t">
              <LpIcon name="flask" size={16} />
              Sandbox database
            </div>
            <span className="tag" data-x="sT" style={{ width: "max-content", color: "var(--accent)" }}>
              disposable · seeded data
            </span>
            <ul>
              {li("layers", "Generated workload, seed 42")}
              {li("hand", "Runs approved SQL only")}
              {li("replay", "Thrown away after the run")}
            </ul>
            <div className="xapplied">
              <LpIcon name="checkCircle" size={13} />
              <span>CREATE INDEX (customer_id, created_at DESC) · applied</span>
            </div>
          </div>
        </div>
        <div className="xappr" aria-hidden="true">
          <div className="xa-h">
            <LpIcon name="hand" size={13} />
            <span data-x="apT">Approval required</span>
            <span className="xa-st" data-x="apSt">
              waiting on you
            </span>
          </div>
          <div className="xa-sql">
            CREATE INDEX ON orders
            <br />
            (customer_id, created_at DESC);
          </div>
          <div className="xa-f">
            <span>
              runs on <b>sandbox_db</b>
            </span>
            <span className="xa-btns">
              <span className="xa-b">Decline</span>
              <span className="xa-b pri" data-x="apBtn">
                Approve
              </span>
            </span>
          </div>
        </div>
        <span className="xpk" />
        <span className="xtag">
          <LpIcon name="xCircle" size={12} />
          refused · read-only session
        </span>
      </div>
      <Caption steps={["Read your database", "Approve, then sandbox", "Writes refused"]} on={cap} />
    </div>
  );
}

/* ---------- 3. Measure performance ---------- */
const ciCache = new Map<number, [number, number, number]>();
/** Bootstrap CI of the median ratio from only the first k samples: the interval narrows as n grows. */
function ciAt(k: number): [number, number, number] {
  if (k === B.n) return [B.ratio, B.ciLow, B.ciHigh];
  const hit = ciCache.get(k);
  if (hit) return hit;
  const b = B.baseline.slice(0, k);
  const c = B.candidate.slice(0, k);
  const r = mulberry32(11 + k);
  const out: number[] = [];
  for (let q = 0; q < 600; q++) out.push(median(Array.from({ length: k }, () => b[Math.floor(r() * k)] ?? 0)) / median(Array.from({ length: k }, () => c[Math.floor(r() * k)] ?? 1)));
  const v: [number, number, number] = [median(b) / median(c), quantile(out, 0.025), quantile(out, 0.975)];
  ciCache.set(k, v);
  return v;
}

const MEASURE_START = 500;
const MEASURE_STEP = 110;

function MeasureScene({ reduced }: { reduced: boolean }) {
  const [k, setK] = useState(reduced ? B.n : 0);
  useEffect(() => {
    if (reduced) return;
    // Sample count follows the wall clock, so timer drift can't push the scene past its fixed length.
    const t0 = performance.now();
    const id = window.setInterval(() => {
      const n = Math.min(B.n, Math.max(0, Math.floor((performance.now() - t0 - MEASURE_START) / MEASURE_STEP) + 1));
      setK(n);
      if (n >= B.n) clearInterval(id);
    }, 40);
    return () => clearInterval(id);
  }, [reduced]);
  const shownK = k >= 8 ? (k === B.n ? k : k - (k % 8)) : 0;
  const stats = shownK ? { mb: median(B.baseline.slice(0, shownK)), mc: median(B.candidate.slice(0, shownK)), ci: ciAt(shownK) } : null;
  const cap = k >= 30 ? 2 : k >= 14 ? 1 : 0;
  const tops = (seed: number) => {
    const r = mulberry32(seed);
    return B.baseline.map(() => 14 + Math.floor(r() * 5) * 9);
  };
  const tb = tops(3);
  const tc = tops(5);
  const grid = [0.5, 1, 2, 5, 10, 20, 50].map((t) => <span key={t} className="grid-v" style={{ left: pct(logPosition(t, LAT)) }} />);
  const arm = (name: string, data: number[], col: string, ts: number[], med?: number) => (
    <div className="axis-row">
      <div className="lbl-arm" style={col === "var(--accent)" ? { color: col } : undefined}>
        {name}
        <small>{med === undefined ? "median —" : `median ${med.toFixed(2)} ms`}</small>
      </div>
      <div className="plot">
        {grid}
        {data.map((v, j) => (
          <span key={j} className="dot" style={{ left: pct(logPosition(v, LAT)), top: `${ts[j]}px`, backgroundColor: col, opacity: j < k ? 0.7 : 0, transition: "opacity .25s" }} />
        ))}
        <span className="med" style={{ left: med === undefined ? 0 : pct(logPosition(med, LAT)), opacity: med === undefined ? 0 : 1 }} />
      </div>
    </div>
  );
  return (
    <div className="mv">
      <div className="mv-h">
        <span className="illus">◆ Illustrative samples</span>
        <span className="mono" style={{ fontSize: 12, color: "var(--muted)" }}>
          n = {k} / {B.n}
        </span>
      </div>
      <div className="chart" style={{ background: "var(--surface)" }}>
        {arm("Baseline", B.baseline, "var(--muted)", tb, stats?.mb)}
        {arm("Candidate", B.candidate, "var(--accent)", tc, stats?.mc)}
        <div className="axis-row" style={{ height: 22 }}>
          <div />
          <div className="plot" style={{ height: 22 }}>
            {[0.5, 1, 2, 5, 10, 20, 50].map((t) => (
              <span key={t} className="tick" style={{ left: pct(logPosition(t, LAT)), top: 4 }}>
                {t}
              </span>
            ))}
          </div>
        </div>
        <div style={{ height: 1, background: "var(--border)", margin: "12px 0" }} />
        <div className="axis-row">
          <div className="lbl-arm">
            Speed-up<small>{stats ? `${stats.ci[0].toFixed(2)}× · ${stats.ci[1].toFixed(2)}–${stats.ci[2].toFixed(2)}×` : "waiting for samples"}</small>
          </div>
          <div className="plot">
            {[0.5, 1, 2, 5, 10].map((t) => (
              <span key={t} className="grid-v" style={{ left: pct(logPosition(t, SPD)) }} />
            ))}
            <span className="thr" style={{ left: pct(logPosition(1.1, SPD)), borderColor: "var(--verified)" }} />
            <span className="ref1" style={{ left: pct(logPosition(1, SPD)) }} />
            {stats && (
              <>
                <span
                  className="ci"
                  style={{ left: pct(logPosition(stats.ci[1], SPD)), width: pct(logPosition(stats.ci[2], SPD) - logPosition(stats.ci[1], SPD)), backgroundColor: "color-mix(in srgb,var(--accent) 60%,transparent)" }}
                />
                <span className="ci-pt" style={{ left: pct(logPosition(stats.ci[0], SPD)), transition: "left .8s cubic-bezier(.2,.8,.2,1)" }} />
              </>
            )}
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
      </div>
      <div className="plain" style={{ marginTop: 12 }}>
        <LpIcon name="bulb" size={15} />
        <span>
          <b>More samples, narrower range.</b> The teal bar is where the true speed-up very likely lies. Watch it shrink as timings come in.
        </span>
      </div>
      <Caption steps={["Collect timings", "Compare medians", "Read the range"]} on={cap} />
    </div>
  );
}

/* ---------- 4. Verify independently ---------- */
type Cell = "ok" | "bad" | "unk" | "warn" | "na";
const VM: [string, Cell[], "verified" | "rejected" | "inconclusive", string][] = [
  ["H1 · index", ["ok", "ok", "ok", "warn"], "verified", "Verified"],
  ["H2 · rewrite", ["bad", "na", "na", "na"], "rejected", "Rejected"],
  ["H3 · ANALYZE", ["ok", "bad", "unk", "ok"], "inconclusive", "Inconclusive"],
];
const CELL_TONE = { ok: "verified", bad: "rejected", unk: "inconclusive", warn: "inconclusive" } as const;
const CELL_ICON = { ok: "checkCircle", bad: "xCircle", unk: "help", warn: "alert" } as const;
const VERIFY_END = 350 + 12 * 240 + 200;

function VerifyScene({ reduced }: { reduced: boolean }) {
  const [t, setT] = useState(reduced ? Number.POSITIVE_INFINITY : 0);
  useEffect(() => {
    if (reduced) return;
    const t0 = performance.now();
    const id = window.setInterval(() => {
      const e = performance.now() - t0;
      setT(e);
      if (e > VERIFY_END + 3 * 260) clearInterval(id);
    }, 60);
    return () => clearInterval(id);
  }, [reduced]);
  const cap = t >= VERIFY_END ? 2 : t >= 350 + 3 * 240 ? 1 : 0;
  return (
    <div style={{ width: "100%", maxWidth: 620, margin: "0 auto" }}>
      <div style={{ overflowX: "auto" }}>
        <table className="vm">
          <caption className="sr">Verification rules for three candidates</caption>
          <thead>
            <tr>
              {["Candidate", "Same rows", "Plan changed", "Big enough", "Stable", "Verdict"].map((h) => (
                <th key={h}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {VM.map(([n, cells, tone, lbl], r) => {
              const verdict = t >= VERIFY_END + r * 260;
              return (
                <tr key={n} className={verdict && r === 0 ? "hl" : undefined}>
                  <td className="mono">{n}</td>
                  {cells.map((c, col) => {
                    const at = 350 + (col * 3 + r) * 240;
                    return (
                      <td key={col} data-v={c}>
                        {t < at ? (
                          <span className="pend" />
                        ) : t < at + 200 && c !== "na" ? (
                          <Spin />
                        ) : c === "na" ? (
                          <span style={{ color: "var(--faint)" }}>—</span>
                        ) : (
                          <span style={{ color: `var(--${CELL_TONE[c]})`, display: "inline-flex" }}>
                            <LpIcon name={CELL_ICON[c]} size={16} />
                          </span>
                        )}
                      </td>
                    );
                  })}
                  <td>
                    <span className={`pill t-${tone} vd${verdict ? " on" : ""}`}>{lbl}</span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="plain" style={{ marginTop: 12 }}>
        <LpIcon name="bulb" size={15} />
        <span>
          <b>Rules first, words second.</b> These checks are ordinary code with fixed thresholds. The AI writes the explanation afterwards and can only make a verdict weaker, never
          stronger.
        </span>
      </div>
      <Caption steps={["Results match?", "Plan, size, stability", "Verdict"]} on={cap} />
    </div>
  );
}

/* ---------- 5. Replay with evidence ---------- */
const RV: [string, string][] = [
  ["query.sql", "5c1e…a91f"],
  ["plan.json", "d40b…77c2"],
  ["schema.json", "77e1…3b08"],
  ["events 0–184", "2a6c…f13e"],
  ["report.json", "41be…0c7d"],
];
function ReplayRow({ k, name, hash, reduced }: { k: number; name: string; hash: string; reduced: boolean }) {
  const [text, done] = useRoll("", hash, 400 + k * 520, 650, reduced);
  const started = text !== "········";
  return (
    <div className={`rv-row${done ? " ok" : ""}`}>
      <span>{name}</span>
      <span className="stc" style={{ color: "var(--muted)" }}>
        {hash}
      </span>
      <span className="rc">{text}</span>
      <span className="st">
        {done ? (
          <Check size={14} />
        ) : started ? (
          <Spin />
        ) : (
          <span style={{ color: "var(--faint)", display: "inline-flex" }}>
            <LpIcon name="dashed" size={13} />
          </span>
        )}
      </span>
    </div>
  );
}
const REPLAY_END = 400 + RV.length * 520 + 700;
function ReplayScene({ reduced }: { reduced: boolean }) {
  const [cap, setCap] = useState(reduced ? 2 : 0);
  useEffect(() => {
    if (reduced) return;
    const a = window.setTimeout(() => setCap(1), 1100);
    const b = window.setTimeout(() => setCap(2), REPLAY_END);
    return () => {
      clearTimeout(a);
      clearTimeout(b);
    };
  }, [reduced]);
  return (
    <div className="rv">
      <div className="rv-h">
        <span>
          <LpIcon name="replay" size={15} />
          Report replay
        </span>
        <span className="tag">0 LLM calls · agents not run</span>
      </div>
      <div className="rv-rows">
        <div className="rv-row h">
          <span>Stored file</span>
          <span className="stc">Stored fingerprint</span>
          <span>Recomputed</span>
          <span />
        </div>
        {RV.map(([n, h], k) => (
          <ReplayRow key={n} k={k} name={n} hash={h} reduced={reduced} />
        ))}
      </div>
      <div className={`rv-ok${cap >= 2 ? " on" : ""}`}>
        <span className="pill t-verified" style={{ height: 28, fontSize: 13 }}>
          <LpIcon name="checkCircle" size={14} />
          Integrity check passed against stored digests
        </span>
      </div>
      <div className="rv-other">
        <div>
          <b>Experiment replay</b>Measures again in a fresh sandbox, same seed, and compares.
        </div>
        <div>
          <b>Re-investigation</b>Runs the agents again as a new run, then diffs the result.
        </div>
      </div>
      <Caption steps={["Re-fingerprint files", "Compare with stored", "Pass or fail"]} on={cap} />
    </div>
  );
}

// Each scene's length is the moment its last visible change settles; the bar fills linearly over exactly that.
const INVESTIGATE_END = 4000 + 700;
const REPLAY_SETTLED = REPLAY_END + 650;
const VERIFY_SETTLED = VERIFY_END + 3 * 260 + 400;
const MEASURE_SETTLED = MEASURE_START + B.n * MEASURE_STEP;
const EXPERIMENT_END = 10000;
const SCENE_MS = {
  investigate: INVESTIGATE_END,
  experiment: EXPERIMENT_END,
  measure: MEASURE_SETTLED,
  verify: VERIFY_SETTLED,
  replay: REPLAY_SETTLED,
};
const FX: { t: string; icon: LpIconName; ms: number; d: string; Scene: (p: { reduced: boolean }) => ReactNode }[] = [
  { t: "Investigate intelligently", ms: SCENE_MS.investigate, icon: "search", d: "Specialist agents read the plan, schema and statistics. Every claim has to point to evidence; claims that don't are removed.", Scene: InvestigateScene },
  { t: "Experiment safely", ms: SCENE_MS.experiment, icon: "flask", d: "Your database is only ever read, with plain EXPLAIN. Changes run in a throwaway sandbox, and only after you approve the exact SQL.", Scene: ExperimentScene },
  { t: "Measure performance", ms: SCENE_MS.measure, icon: "gauge", d: "Both versions run many times, interleaved, and every timing is kept. You get an interval for the speed-up, not a single number.", Scene: MeasureScene },
  { t: "Verify independently", ms: SCENE_MS.verify, icon: "shieldCheck", d: "Plain code checks correctness and statistics and gives the verdict, and a result is only verified once its audit has run. The AI that suggested a change can't promote it.", Scene: VerifyScene },
  { t: "Replay with evidence", ms: SCENE_MS.replay, icon: "replay", d: "Replaying a report re-checks the fingerprint of every stored file. Nothing is re-run; measuring again or re-investigating are separate actions.", Scene: ReplayScene },
];

export function FeatureExplorer() {
  const reduced = useReducedMotion();
  const stageRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const visible = useInView(stageRef, 0.35);
  const [i, setI] = useState(0);
  const [auto, setAuto] = useState(true);
  const [gen, setGen] = useState(0);
  const autoOn = auto && !reduced;
  const running = autoOn && visible;

  const select = (n: number, user: boolean) => {
    if (user) setAuto(false);
    setI(n);
    setGen((g) => g + 1);
  };
  const onKey = (e: KeyboardEvent) => {
    const k = ({ ArrowDown: 1, ArrowRight: 1, ArrowUp: -1, ArrowLeft: -1 } as Record<string, number>)[e.key];
    if (k === undefined && e.key !== "Home" && e.key !== "End") return;
    e.preventDefault();
    const n = e.key === "Home" ? 0 : e.key === "End" ? FX.length - 1 : (i + (k ?? 0) + FX.length) % FX.length;
    select(n, true);
    listRef.current?.querySelectorAll<HTMLButtonElement>(".fx-card")[n]?.focus();
  };
  // Grow (never shrink) the stage to fit the scene, so stacked layouts don't scroll inside the panel.
  useLayoutEffect(() => {
    const stage = stageRef.current;
    const panel = stage?.querySelector<HTMLElement>(".fx-panel.on");
    if (!stage || !panel) return;
    stage.style.minHeight = "";
    const need = panel.scrollHeight;
    if (need > stage.clientHeight) stage.style.minHeight = `${need}px`;
  }, [i, gen]);
  const Scene = FX[i]?.Scene ?? InvestigateScene;

  return (
    <section className="sec" id="features" style={{ paddingTop: 120, paddingBottom: 56 }}>
      <div className="wrap">
        <Reveal className="sec-head center">
          <p className="eyebrow">In short</p>
          <h2>
            Built like an instrument, <span>not a chatbot.</span>
          </h2>
        </Reveal>
        <Reveal className="fx">
          <div className="fx-stage" ref={stageRef}>
            {FX.map((f, n) => (
              <div key={f.t} className={`fx-panel${n === i ? " on" : ""}`} role="tabpanel" id={`fxp${n}`} aria-labelledby={`fxt${n}`}>
                {n === i && visible && <Scene key={gen} reduced={reduced} />}
              </div>
            ))}
          </div>
          <div>
            <div className="fx-list" role="tablist" aria-orientation="vertical" aria-label="Capabilities" ref={listRef} onKeyDown={onKey}>
              {FX.map((f, n) => (
                <button
                  key={f.t}
                  type="button"
                  className="fx-card"
                  role="tab"
                  id={`fxt${n}`}
                  aria-controls={`fxp${n}`}
                  aria-selected={n === i}
                  tabIndex={n === i ? 0 : -1}
                  style={{ "--dur": `${f.ms}ms` } as CSSProperties}
                  onClick={() => select(n, true)}
                >
                  <h3>
                    <LpIcon name={f.icon} size={17} />
                    {f.t}
                  </h3>
                  <p>{f.d}</p>
                  <span
                    key={n === i ? `${gen}-${String(running)}` : "idle"}
                    className={`pbar${n === i && running ? " run" : ""}`}
                    onAnimationEnd={() => {
                      if (autoOn) select((i + 1) % FX.length, false);
                    }}
                  />
                </button>
              ))}
            </div>
            <div className="fx-auto">
              {!autoOn && !reduced && (
                <>
                  <span>Autoplay paused.</span>
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    onClick={() => {
                      setAuto(true);
                      select((i + 1) % FX.length, false);
                    }}
                  >
                    <LpIcon name="play" size={12} />
                    Resume
                  </button>
                </>
              )}
            </div>
          </div>
        </Reveal>
      </div>
    </section>
  );
}
