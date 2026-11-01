"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { ILLUSTRATIVE_BENCH as B } from "@/lib/landing/bench";
import { curve } from "@/lib/landing/geometry";
import { useReducedMotion } from "./hooks";
import { LpIcon } from "./LpIcon";
import { Reveal } from "./Reveal";
import { burst, comet } from "./wire";

type Tone = "ok" | "bad" | "unk";
const ratio = `◆ ${B.ratio.toFixed(2)}× (${B.ciLow.toFixed(2)}×–${B.ciHigh.toFixed(2)}×)`;
const BRANCHES: { tone: Tone; conf: string; by: string; t: string; steps: [string, string][]; foot: ReactNode }[] = [
  {
    tone: "ok",
    conf: "high",
    by: "Index Strategist",
    t: "No index fits this filter and sort.",
    steps: [["Candidate", "CREATE INDEX (customer_id, created_at DESC)"], ["Experiment", "done · 3 param sets"], ["Evidence", "plan now uses the index"], ["Measurement", ratio]],
    foot: (
      <span className="pill t-verified">
        <LpIcon name="checkCircle" size={12} />
        Verified · within tested scope
      </span>
    ),
  },
  {
    tone: "bad",
    conf: "medium",
    by: "Query Analyzer",
    t: "A rewrite can skip the sort.",
    steps: [["Candidate", "keyset rewrite (LATERAL)"], ["Experiment", "done · 3 param sets"], ["Evidence", "rows differ on p2"], ["Measurement", "not used: results differ"]],
    foot: (
      <span className="pill t-rejected">
        <LpIcon name="xCircle" size={12} />
        Rejected · <span className="mono">result_mismatch</span>
      </span>
    ),
  },
  {
    tone: "unk",
    conf: "low",
    by: "Supervisor",
    t: "Planner statistics are stale.",
    steps: [["Candidate", "ANALYZE orders"], ["Experiment", "done · 3 param sets"], ["Evidence", "estimates unchanged"], ["Measurement", "◆ 1.02× (0.94×–1.11×)"]],
    foot: (
      <span className="pill t-inconclusive">
        <LpIcon name="help" size={12} />
        Inconclusive · interval includes 1×
      </span>
    ),
  },
];
const STAGES = ["Query received", "Hypotheses formed", "Testing each in a sandbox", "Fixed rules decide", "Summary"];
const STAGE_AT = [0, 1450, 2500, 4250, 5450];
const NS = "http://www.w3.org/2000/svg";
// A step passes unless it is the rejected branch's evidence/measurement or the inconclusive branch's measurement.
const stepOk = (tone: Tone, s: number) => !(tone === "bad" && s >= 2) && !(tone === "unk" && s === 3);
const GLYPH: Record<Tone, ReactNode> = {
  ok: <span style={{ color: "var(--verified)", display: "inline-flex" }}><LpIcon name="checkCircle" size={13} /></span>,
  bad: <span style={{ color: "var(--rejected)", display: "inline-flex" }}><LpIcon name="xCircle" size={13} /></span>,
  unk: <span style={{ color: "var(--inconclusive)", display: "inline-flex" }}><LpIcon name="help" size={13} /></span>,
};

export function BranchingSection() {
  const reduced = useReducedMotion();
  const boxRef = useRef<HTMLDivElement>(null);
  const [run, setRun] = useState(0);
  const [stage, setStage] = useState(0);
  // Steps resolved per card: -1 none; index of the last revealed step.
  const [resolved, setResolved] = useState<number[]>([-1, -1, -1]);

  // Start the walk-through the first time the diagram is a third on screen.
  useEffect(() => {
    const el = boxRef.current;
    if (!el) return;
    const io = new IntersectionObserver(
      (es) => {
        if (es[0]?.isIntersecting) {
          setRun(1);
          io.disconnect();
        }
      },
      { threshold: 0.3 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  useEffect(() => {
    const box = boxRef.current;
    if (!box || run === 0) return;
    const svg = box.querySelector<SVGSVGElement>(".br-svg") as SVGSVGElement;
    const root = box.querySelector<HTMLElement>(".br-root") as HTMLElement;
    const sum = box.querySelector<HTMLElement>(".br-sum") as HTMLElement;
    const cols = box.querySelector<HTMLElement>(".br-cols") as HTMLElement;
    const cards = [...box.querySelectorAll<HTMLElement>(".br-card")];
    const timers: number[] = [];
    const at = (ms: number, f: () => void) => timers.push(window.setTimeout(f, reduced ? 0 : ms));
    let bottomDrawn = false;
    let paths: { a: SVGPathElement; b: SVGPathElement }[] = [];
    // Wires and ports keep their state across layout() rebuilds (resize).
    const aDrawn = [false, false, false];
    const lit = new Set<string>();

    // Reserve each card's final height so connectors to the summary don't move while steps unfold.
    cards.forEach((c) => {
      c.style.minHeight = "";
      c.classList.add("measure", "nt");
    });
    const hs = cards.map((c) => c.offsetHeight);
    cards.forEach((c, i) => {
      c.classList.remove("measure");
      c.style.minHeight = `${hs[i]}px`;
    });
    void cols.offsetHeight;
    cards.forEach((c) => c.classList.remove("nt"));

    const layout = () => {
      svg.replaceChildren();
      const c = box.getBoundingClientRect();
      cards.forEach((card) => {
        card.style.transition = "none";
        card.style.transform = "none";
      });
      const mk = (d: string, cls?: string) => {
        const p = document.createElementNS(NS, "path");
        p.setAttribute("d", d);
        if (cls) p.setAttribute("class", cls);
        svg.appendChild(p);
        return p;
      };
      paths = cards.map((card, i) => ({
        a: mk(curve(root.getBoundingClientRect(), card.getBoundingClientRect(), c)),
        b: mk(curve(card.getBoundingClientRect(), sum.getBoundingClientRect(), c), BRANCHES[i]?.tone),
      }));
      paths.forEach(({ a, b }, i) => {
        const La = a.getTotalLength();
        a.style.strokeDasharray = String(La);
        a.style.strokeDashoffset = aDrawn[i] ? "0" : String(La);
        const L = b.getTotalLength();
        b.style.strokeDasharray = String(L);
        b.style.strokeDashoffset = bottomDrawn ? "0" : String(L);
        const port = (key: string, at: DOMPoint, tone?: string) => {
          const dot = document.createElementNS(NS, "circle");
          dot.setAttribute("cx", String(at.x));
          dot.setAttribute("cy", String(at.y));
          dot.setAttribute("r", "3.2");
          dot.setAttribute("data-k", key);
          dot.setAttribute("class", `port${tone ? ` ${tone}` : ""}${lit.has(key) ? " lit" : ""}`);
          svg.appendChild(dot);
        };
        port(`r${i}`, a.getPointAtLength(0));
        port(`t${i}`, a.getPointAtLength(La));
        port(`c${i}`, b.getPointAtLength(0), BRANCHES[i]?.tone);
        port(`s${i}`, b.getPointAtLength(L), BRANCHES[i]?.tone);
      });
      cards.forEach((card) => (card.style.transform = ""));
      void cols.offsetHeight;
      cards.forEach((card) => (card.style.transition = ""));
    };
    const light = (key: string) => {
      lit.add(key);
      svg.querySelector(`[data-k="${key}"]`)?.classList.add("lit");
    };
    const ringAt = (key: string, color?: string) => {
      const dot = svg.querySelector(`[data-k="${key}"]`);
      if (dot) burst(svg, Number(dot.getAttribute("cx")), Number(dot.getAttribute("cy")), color);
    };
    // The wire draws itself ahead of a glowing pulse; the port it lands on lights up.
    const send = (path: SVGPathElement, ms: number, from: string, to: string, color?: string) => {
      light(from);
      const L = path.getTotalLength();
      path.style.strokeDasharray = String(L);
      path.style.strokeDashoffset = String(L);
      void path.getBoundingClientRect();
      path.style.transition = `stroke-dashoffset ${ms * 0.7}ms cubic-bezier(.3,0,.2,1)`;
      path.style.strokeDashoffset = "0";
      comet(svg, path, { ms, cls: "sig", color });
      timers.push(
        window.setTimeout(() => {
          light(to);
          ringAt(to, color);
        }, ms - 60),
      );
    };

    layout();
    setResolved([-1, -1, -1]);
    sum.classList.remove("on");
    root.classList.remove("active");
    if (!reduced) root.classList.add("pre");
    STAGE_AT.forEach((t, n) => at(t, () => setStage(n)));
    at(60, () => root.classList.remove("pre"));
    at(250, () => {
      if (!reduced) root.classList.add("active");
    });
    const SIG = 1100;
    const sigAt = (i: number) => 450 + i * 180;
    // layout() rebuilds the paths (the ResizeObserver fires on attach), so resolve them when the timer fires.
    paths.forEach((_, i) =>
      at(sigAt(i), () => {
        const a = paths[i]?.a;
        if (!a) return;
        aDrawn[i] = true;
        if (reduced) {
          a.style.strokeDashoffset = "0";
          lit.add(`r${i}`).add(`t${i}`);
          svg.querySelectorAll(`[data-k="r${i}"],[data-k="t${i}"]`).forEach((d) => d.classList.add("lit"));
        } else send(a, SIG, `r${i}`, `t${i}`);
      }),
    );
    at(2000, () => root.classList.remove("active"));
    cards.forEach((c, i) => {
      at(sigAt(i), () => c.classList.add("arming"));
      at(sigAt(i) + SIG * 0.45, () => c.classList.remove("pre", "arming"));
      at(2550 + i * 110, () => c.classList.add("testing"));
      for (let s = 0; s < 4; s++) at(2650 + s * 380 + i * 110, () => setResolved((r) => r.map((v, j) => (j === i ? Math.max(v, s) : v))));
      at(4300 + i * 380, () => {
        c.classList.remove("testing");
        c.classList.add("v");
      });
    });
    at(5500, () => {
      layout();
      bottomDrawn = true;
      paths.forEach(({ b }) => {
        void b.getBoundingClientRect();
        b.style.transition = reduced ? "none" : "stroke-dashoffset .9s cubic-bezier(.2,.8,.2,1)";
        b.style.strokeDashoffset = "0";
      });
      paths.forEach(({ b }, i) => {
        const tone = BRANCHES[i]?.tone;
        const color = tone === "ok" ? "var(--verified)" : tone === "bad" ? "var(--rejected)" : "var(--inconclusive)";
        if (reduced) ["c", "s"].forEach((k) => light(`${k}${i}`));
        else {
          light(`c${i}`);
          comet(svg, b, { ms: 900, delay: i * 90, cls: "sig", color });
          timers.push(window.setTimeout(() => (light(`s${i}`), ringAt(`s${i}`, color)), 900 + i * 90 - 60));
        }
      });
    });
    at(6300, () => sum.classList.add("on"));
    const ro = new ResizeObserver(() => layout());
    ro.observe(cols);
    return () => {
      timers.forEach(clearTimeout);
      ro.disconnect();
    };
  }, [run, reduced]);

  return (
    <section className="sec" id="verify" style={{ padding: "8px 0 0" }}>
      <div className="wrap">
        <Reveal className="sec-head center how-head">
          <p className="eyebrow">Zoomed in · hypotheses</p>
          <h2>
            <span className="l1" style={{ color: "inherit" }}>Every hypothesis gets its own test.</span> <span>Failed and inconclusive branches stay in the record.</span>
          </h2>
          <p>
            QueryCure doesn&apos;t bet on one idea. Each hypothesis is tested on its own, under the same conditions, and the ones that fail stay in the record with the reason. These are
            branches of an investigation, not copies of your database.
          </p>
        </Reveal>
        <div className="br reveal in" ref={boxRef}>
          <svg className="br-svg" aria-hidden="true" />
          <div className="br-from">From the pipeline&apos;s Hypotheses step · ◆ illustrative</div>
          <div className="br-root">
            <LpIcon name="code" size={14} />
            <span>SELECT … FROM orders WHERE customer_id = $1 ORDER BY created_at DESC LIMIT 20</span>
          </div>
          <div className="br-cols" key={run}>
            {BRANCHES.map((b, i) => (
              <div key={b.t} className={`br-card ${b.tone}${reduced || run === 0 ? "" : " pre"}`}>
                <div className="br-head">
                  <div className="lbl">
                    <span className="mono" style={{ fontSize: 11, color: "var(--faint)" }}>
                      H{i + 1}
                    </span>
                    <span className="pill t-hypothesis" style={{ height: 20, fontSize: 11 }}>
                      <LpIcon name="dashed" size={11} />
                      Hypothesis · {b.conf}
                    </span>
                  </div>
                  <div className="t">{b.t}</div>
                  <div style={{ fontSize: 11.5, color: "var(--muted)" }}>from {b.by}</div>
                </div>
                {b.steps.map(([k, v], s) => {
                  const done = (resolved[i] ?? -1) >= s;
                  return (
                    <div key={k} className={`br-step${done ? " on" : ""}`}>
                      <span className="g">
                        {done ? (
                          GLYPH[stepOk(b.tone, s) ? "ok" : b.tone]
                        ) : (
                          <span style={{ color: "var(--faint)", display: "inline-flex" }}>
                            <LpIcon name="dashed" size={13} />
                          </span>
                        )}
                      </span>
                      <span className="k">{k}</span>
                      <span className="v">{v}</span>
                    </div>
                  );
                })}
                <div className="br-foot">
                  <span className="br-wait">{(resolved[i] ?? -1) >= 0 ? "testing…" : "queued"}</span>
                  <span className="br-verdict">{b.foot}</span>
                </div>
              </div>
            ))}
          </div>
          <div className="br-sum">
            <div style={{ fontWeight: 600, fontSize: 14 }}>1 verified · 1 rejected · 1 inconclusive</div>
            <div style={{ fontSize: 13, color: "var(--muted)", marginTop: 4, lineHeight: "19px" }}>
              H1 is recommended: median latency improved{" "}
              <span className="mono" style={{ color: "var(--ink)" }}>
                {B.ratio.toFixed(2)}×
              </span>{" "}
              (95% CI {B.ciLow.toFixed(2)}×–{B.ciHigh.toFixed(2)}×) in the illustrative sandbox run. H2 was rejected because its results differed; H3&apos;s interval includes 1×.
            </div>
          </div>
        </div>
        <div className="br-ctrl">
          <span className="br-stage" aria-live="off">
            {run === 0 ? "" : `${stage + 1} / 5 · ${STAGES[stage]}`}
          </span>
          <span className="illus">◆ Illustrative fixture</span>
          <button type="button" className="btn btn-secondary btn-sm" onClick={() => setRun((r) => r + 1)}>
            <LpIcon name="replay" size={14} />
            Replay
          </button>
        </div>
      </div>
    </section>
  );
}
