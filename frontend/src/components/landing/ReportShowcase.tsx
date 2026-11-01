"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { ILLUSTRATIVE_BENCH as B, pct } from "@/lib/landing/bench";
import { useReducedMotion } from "./hooks";
import { LpIcon } from "./LpIcon";
import { Reveal } from "./Reveal";

const f = (v: number) => v.toFixed(2);
// Space the page's floating nav occupies at the top of the viewport.
const NAV_CLEARANCE = 88;
// Pinned-card layout (must match landing.css): breakpoint and the card's top offset.
const PIN_MIN_WIDTH = 861;
const CARD_STICK = 96;
// Page-scroll pixels spent per pixel of report content, so the card reads slowly instead of flying by.
const SCROLL_DRAG = 2.4;
const TOC = [
  "Summary",
  "Findings",
  "Recommendation",
  "Benchmark",
  "Limitations",
  "Integrity",
];
const TABS = ["Original report", "Replay", "Evidence details"] as const;
const DDL = "CREATE INDEX ON orders (customer_id, created_at DESC);";
const EVIDENCE = [
  [
    "ev_31a7",
    "plan_node",
    "Node 3: Seq Scan on orders",
    "art_d40b · plan.json",
  ],
  ["ev_8c02", "index_list", "orders indexes: (status)", "art_77e1 · schema"],
  [
    "ev_2f19",
    "column_stats",
    "customer_id n_distinct ≈ 41k",
    "art_77e1 · stats",
  ],
  ["ev_b6d0", "benchmark", "40 + 40 samples, p1", "exp_c3a0 · result"],
  ["ev_e512", "plan_diff", "Index Scan using new index", "exp_c3a0 · plans"],
  ["ev_09fd", "correctness", "row digests equal · 3 / 3", "exp_c3a0 · rows"],
] as const;

export function SqlDdl() {
  return (
    <>
      <span className="k">CREATE INDEX</span> <span className="k">ON</span>{" "}
      orders (customer_id, created_at <span className="k">DESC</span>);
    </>
  );
}

function Ev({ id, onShow }: { id: string; onShow: (id: string) => void }) {
  return (
    <button
      type="button"
      className="chip-ev"
      aria-label={`Show evidence ${id} in Evidence details`}
      onClick={() => onShow(id)}
    >
      <LpIcon name="layers" size={11} />
      {id}
    </button>
  );
}

function Section({
  n,
  title,
  children,
}: {
  n: number;
  title: string;
  children: ReactNode;
}) {
  return (
    <section className="rp-s" data-sec={n}>
      <h4>
        <span className="n">{n}</span>
        {title}
      </h4>
      {children}
    </section>
  );
}

export function ReportShowcase() {
  const reduced = useReducedMotion();
  const [tab, setTab] = useState(0);
  const [tocOn, setTocOn] = useState(0);
  const [copy, setCopy] = useState("Copy SQL");
  const [flash, setFlash] = useState<string | null>(null);
  const mainRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const slideRef = useRef<HTMLDivElement>(null);
  const barRef = useRef<HTMLDivElement>(null);
  const tabsRef = useRef<HTMLDivElement>(null);
  const pending = useRef<(() => void) | null>(null);

  // Wide screens: the card keeps a fixed size and pins under the nav while page scrolling slides the report through it
  // (no inner scrollbar, nothing trapped: the stage just adds scroll distance). Narrow screens: plain flow.
  const pinned = () => window.innerWidth >= PIN_MIN_WIDTH;
  const stickTop = useCallback(
    () =>
      pinned()
        ? CARD_STICK
        : NAV_CLEARANCE + (barRef.current?.offsetHeight ?? 0),
    [],
  );
  const slide = useCallback(() => {
    const stage = stageRef.current;
    const wrap = wrapRef.current;
    const pane = slideRef.current;
    if (!stage || !wrap || !pane) return;
    if (!pinned()) {
      stage.style.height = "";
      pane.style.transform = "";
      stage.firstElementChild?.classList.remove("engaged");
      return;
    }
    const overflow = Math.max(0, pane.scrollHeight - wrap.clientHeight);
    const card = stage.firstElementChild as HTMLElement | null;
    stage.style.height = `${(card?.offsetHeight ?? 0) + overflow * SCROLL_DRAG}px`;
    const start =
      stage.getBoundingClientRect().top + window.scrollY - CARD_STICK;
    const off = Math.min(
      overflow,
      Math.max(0, (window.scrollY - start) / SCROLL_DRAG),
    );
    pane.style.transform = `translate3d(0,${-off}px,0)`;
    // Pop out while the card is pinned and the report is moving through it.
    const scrolled = window.scrollY - start;
    stage.firstElementChild?.classList.toggle(
      "engaged",
      scrolled > 2 && scrolled < overflow * SCROLL_DRAG - 2,
    );
  }, []);
  const go = useCallback(
    (el: Element) => {
      const stage = stageRef.current;
      const pane = slideRef.current;
      const behavior: ScrollBehavior = reduced ? "auto" : "smooth";
      if (stage && pane && pinned() && stage.contains(el)) {
        const overflow = Math.max(
          0,
          pane.scrollHeight - (wrapRef.current?.clientHeight ?? 0),
        );
        const inPane = pane.contains(el)
          ? el.getBoundingClientRect().top - pane.getBoundingClientRect().top
          : 0;
        const start =
          stage.getBoundingClientRect().top + window.scrollY - CARD_STICK;
        window.scrollTo({
          top:
            start + Math.min(overflow, Math.max(0, inPane - 8)) * SCROLL_DRAG,
          behavior,
        });
        return;
      }
      const offset =
        el === mainRef.current ? NAV_CLEARANCE + 8 : stickTop() + 8;
      window.scrollTo({
        top: el.getBoundingClientRect().top + window.scrollY - offset,
        behavior,
      });
    },
    [reduced, stickTop],
  );

  useEffect(() => {
    const pane = slideRef.current;
    if (!pane) return;
    let raf = 0;
    const run = () => {
      raf = 0;
      slide();
    };
    const queue = () => {
      if (!raf) raf = requestAnimationFrame(run);
    };
    const ro = new ResizeObserver(queue);
    ro.observe(pane);
    window.addEventListener("scroll", queue, { passive: true });
    window.addEventListener("resize", queue);
    slide();
    return () => {
      ro.disconnect();
      window.removeEventListener("scroll", queue);
      window.removeEventListener("resize", queue);
      cancelAnimationFrame(raf);
    };
  }, [slide, tab]);

  // Highlight the section whose heading has most recently passed the top of the visible report area.
  useEffect(() => {
    const main = mainRef.current;
    if (!main || tab !== 0) return;
    let raf = 0;
    const track = () => {
      raf = 0;
      const secs = [...main.querySelectorAll(".rp-s")];
      const line =
        (pinned()
          ? (wrapRef.current?.getBoundingClientRect().top ?? 0)
          : stickTop()) + 40;
      let n = 0;
      secs.forEach((s, k) => {
        if (s.getBoundingClientRect().top <= line) n = k;
      });
      const stage = stageRef.current;
      const pane = slideRef.current;
      let done =
        window.innerHeight + window.scrollY >=
        document.documentElement.scrollHeight - 2;
      if (pinned() && stage && pane) {
        const overflow = Math.max(
          0,
          pane.scrollHeight - (wrapRef.current?.clientHeight ?? 0),
        );
        done =
          window.scrollY -
            (stage.getBoundingClientRect().top + window.scrollY - CARD_STICK) >=
          overflow * SCROLL_DRAG - 2;
      }
      if (done) n = secs.length - 1;
      setTocOn(n);
    };
    const onScroll = () => {
      if (!raf) raf = requestAnimationFrame(track);
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    track();
    return () => {
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
      cancelAnimationFrame(raf);
    };
  }, [tab, stickTop]);

  // Run a scroll once the pane for the new tab has rendered.
  useEffect(() => {
    pending.current?.();
    pending.current = null;
  }, [tab]);

  const select = (i: number, then?: () => void) => {
    if (i !== 0) setTocOn(i === 1 ? 5 : 1);
    // Panes differ in height, so bring the tab bar back into view if the page is scrolled past it.
    pending.current =
      then ??
      (() => {
        const main = mainRef.current;
        if (main && main.getBoundingClientRect().top < NAV_CLEARANCE) go(main);
      });
    if (i === tab) {
      pending.current?.();
      pending.current = null;
    } else setTab(i);
  };
  const jump = (i: number) =>
    select(0, () => {
      const s = mainRef.current?.querySelector(`.rp-s[data-sec="${i + 1}"]`);
      if (s) go(s);
    });
  const onTabKey = (e: KeyboardEvent) => {
    const d = ({ ArrowRight: 1, ArrowLeft: -1 } as Record<string, number>)[
      e.key
    ];
    if (!d) return;
    const n = (tab + d + TABS.length) % TABS.length;
    select(n);
    tabsRef.current?.querySelectorAll<HTMLButtonElement>(".rp-tab")[n]?.focus();
  };
  const showEvidence = (id: string) =>
    select(2, () => {
      const row = document.getElementById(`evrow-${id}`);
      if (!row) return;
      go(row);
      setFlash(id);
      window.setTimeout(() => setFlash(null), 1600);
    });
  const copySql = () => {
    const done = (ok: boolean) => {
      setCopy(ok ? "Copied" : "Copy failed");
      window.setTimeout(() => setCopy("Copy SQL"), 1500);
    };
    if (!navigator.clipboard) return done(false);
    navigator.clipboard.writeText(DDL).then(
      () => done(true),
      () => done(false),
    );
  };
  const top = Math.ceil((B.baselineMedian * 1.15) / 4) * 4;

  return (
    <section className="sec" id="report" style={{ padding: "8px 0 40px" }}>
      <div className="wrap">
        <Reveal className="sec-head center">
          <p className="eyebrow">Sealed · the report</p>
          <h2>
            <span style={{ display: "block", color: "inherit" }}>A report you can re-check.</span>
            <span>
              Findings, evidence, limitations, and a{" "}
              <span className="term" tabIndex={0}>
                fingerprint
                <span className="tip" role="tooltip">
                  A digest (SHA-256) is a fingerprint of a file. Change one byte
                  and the fingerprint changes.
                </span>
              </span>{" "}
              of every artifact.
            </span>
          </h2>
        </Reveal>
        <div className="rp-stage" ref={stageRef}>
          <Reveal className="rp">
            <aside className="rp-toc">
              <div className="rp-toc-in">
                <div className="eyebrow">On this page</div>
                <ol>
                  {TOC.map((t, i) => (
                    <li key={t} className={tocOn === i ? "on" : undefined}>
                      <button
                        type="button"
                        aria-current={
                          tab === 0 && tocOn === i ? "location" : undefined
                        }
                        onClick={() => jump(i)}
                      >
                        <span
                          className="mono"
                          style={{ color: "var(--faint)", marginRight: 8 }}
                        >
                          {i + 1}
                        </span>
                        {t}
                      </button>
                    </li>
                  ))}
                </ol>
              </div>
            </aside>
            <div className="rp-main" ref={mainRef}>
              <div className="rp-bar" ref={barRef}>
                <div
                  className="rp-tabs"
                  role="tablist"
                  aria-label="Report view"
                  ref={tabsRef}
                  onKeyDown={onTabKey}
                >
                  {TABS.map((t, i) => (
                    <button
                      key={t}
                      type="button"
                      className="rp-tab"
                      role="tab"
                      id={`rp-tab-${i}`}
                      aria-selected={tab === i}
                      aria-controls="rp-pane"
                      tabIndex={tab === i ? 0 : -1}
                      onClick={() => select(i)}
                    >
                      {t}
                    </button>
                  ))}
                </div>
                {tab === 0 && (
                  <nav className="rp-chips" aria-label="Report sections">
                    {TOC.map((t, i) => (
                      <button
                        key={t}
                        type="button"
                        className={tocOn === i ? "on" : undefined}
                        aria-current={tocOn === i ? "location" : undefined}
                        onClick={() => jump(i)}
                      >
                        {t}
                      </button>
                    ))}
                  </nav>
                )}
              </div>
              <div
                id="rp-pane"
                className="rp-panewrap"
                ref={wrapRef}
                role="tabpanel"
                aria-labelledby={`rp-tab-${tab}`}
              >
                <div className="rp-slide" ref={slideRef}>
                  <div className="rp-pane">
                    {tab === 0 && (
                      <>
                        <div className="rx">
                          <div className="rx-top">
                            <span className="pill t-verified">
                              <LpIcon name="checkCircle" size={12} />
                              Verified · within tested scope
                            </span>
                            <span className="illus">◆ illustrative</span>
                          </div>
                          <h3>
                            A composite index removes the sequential scan on
                            orders
                          </h3>
                          <div className="rx-meta">
                            Slow orders lookup · PostgreSQL · Run #1
                          </div>
                          <div className="rx-stats">
                            <div>
                              <div className="k">Median latency · p1</div>
                              <div className="v">{f(B.candidateMedian)} ms</div>
                              <div className="s">
                                from {f(B.baselineMedian)} ms baseline
                              </div>
                            </div>
                            <div>
                              <div className="k">Median ratio</div>
                              <div
                                className="v"
                                style={{ color: "var(--accent)" }}
                              >
                                {f(B.ratio)}×
                              </div>
                              <div className="s">
                                95% CI {f(B.ciLow)}×–{f(B.ciHigh)}×
                              </div>
                            </div>
                            <div>
                              <div className="k">Tested scope</div>
                              <div className="v">3 param sets</div>
                              <div className="s">
                                1 workload · 1 sandbox image
                              </div>
                            </div>
                          </div>
                        </div>
                        <div
                          className="callout t-running"
                          style={{ marginTop: 14, background: "transparent" }}
                        >
                          <LpIcon name="flask" size={15} />
                          <span>
                            Measured in a disposable sandbox on a seeded
                            workload, not on your data.
                          </span>
                        </div>
                        <Section n={1} title="Summary">
                          <div className="ai">
                            <div className="eyebrow">AI-written</div>
                            <p className="b">
                              The query scans all of orders to find one
                              customer&apos;s rows and sorts them. An index on
                              (customer_id, created_at DESC) lets PostgreSQL
                              read the 20 newest rows directly.
                            </p>
                          </div>
                        </Section>
                        <Section n={2} title="Findings">
                          <div className="rf">
                            <div className="rf-row">
                              <span className="pill t-neutral">
                                <LpIcon name="eye" size={12} />
                                Observed
                              </span>
                              <span>
                                Seq Scan on orders removes 1,999,953 rows by
                                filter.
                              </span>
                              <Ev id="ev_31a7" onShow={showEvidence} />
                            </div>
                            <div className="rf-row">
                              <span className="pill t-neutral">
                                <LpIcon name="eye" size={12} />
                                Observed
                              </span>
                              <span>
                                orders has one index, on (status); none starts
                                with customer_id.
                              </span>
                              <Ev id="ev_8c02" onShow={showEvidence} />
                            </div>
                            <div className="rf-row">
                              <span className="pill t-hypothesis">
                                <LpIcon name="dashed" size={12} />
                                Supports H1
                              </span>
                              <span>No index fits this filter and sort.</span>
                              <span className="rf-sub">
                                Tested in section 4.
                              </span>
                            </div>
                          </div>
                        </Section>
                        <Section n={3} title="Recommendation">
                          <div className="rc-h">
                            <span>Proposed SQL</span>
                            <button
                              type="button"
                              className="btn btn-ghost btn-sm"
                              onClick={copySql}
                              aria-live="polite"
                            >
                              {copy}
                            </button>
                          </div>
                          <div className="code">
                            <SqlDdl />
                          </div>
                          <p className="rc-n">
                            <LpIcon name="flask" size={13} />
                            <span>
                              Proposed change. Tested in a disposable sandbox;
                              not applied to your database.
                            </span>
                          </p>
                        </Section>
                        <Section n={4} title="Benchmark">
                          <div className="rb">
                            <div className="rb-h">
                              <span>
                                Median latency · param set p1 · {B.n} measured
                                runs per arm
                              </span>
                              <span>lower is better</span>
                            </div>
                            <div className="rb-g">
                              <span className="rb-l">Baseline</span>
                              <div className="rb-t">
                                <span
                                  className="rb-b"
                                  style={{
                                    width: pct((B.baselineMedian / top) * 100),
                                  }}
                                />
                              </div>
                              <span className="rb-v">
                                {f(B.baselineMedian)} ms
                              </span>
                              <span className="rb-l">Candidate</span>
                              <div className="rb-t">
                                <span
                                  className="rb-b c"
                                  style={{
                                    width: pct((B.candidateMedian / top) * 100),
                                  }}
                                />
                              </div>
                              <span
                                className="rb-v"
                                style={{ color: "var(--accent)" }}
                              >
                                {f(B.candidateMedian)} ms
                              </span>
                              <span />
                              <div className="rb-ax">
                                {[0, 1, 2, 3, 4].map((k) => (
                                  <span key={k}>{(top * k) / 4}</span>
                                ))}
                              </div>
                              <span
                                className="rb-ax"
                                style={{ justifyContent: "flex-end" }}
                              >
                                ms
                              </span>
                            </div>
                            <dl className="rb-f">
                              <dt>Performance</dt>
                              <dd>
                                Median ratio {f(B.ratio)}× · 95% CI {f(B.ciLow)}
                                ×–{f(B.ciHigh)}×{" "}
                                <Ev id="ev_b6d0" onShow={showEvidence} />
                                <span className="rb-n">
                                  The interval is a bootstrap of the ratio of
                                  medians (2,000 resamples of all {B.n} runs per
                                  arm), not read off the two bars.
                                </span>
                              </dd>
                              <dt>Correctness</dt>
                              <dd>
                                Results match on 3 / 3 parameter sets{" "}
                                <Ev id="ev_09fd" onShow={showEvidence} />
                              </dd>
                            </dl>
                            <div style={{ marginTop: 8, textAlign: "right" }}>
                              <button
                                type="button"
                                className="lnk"
                                onClick={() => {
                                  const t = document.getElementById("bench");
                                  if (t) go(t);
                                }}
                              >
                                See every timing ↑
                              </button>
                            </div>
                          </div>
                        </Section>
                        <Section n={5} title="Limitations">
                          <dl className="rl">
                            <dt>Scope</dt>
                            <dd>
                              One workload, three parameter sets, one sandbox
                              image.
                            </dd>
                            <dt>Reproducibility</dt>
                            <dd>
                              One experiment on one host; no replicate
                              experiments.
                            </dd>
                            <dt>Not measured</dt>
                            <dd>Write overhead of the new index.</dd>
                            <dt>Other hypotheses</dt>
                            <dd>
                              H2 rejected (
                              <span className="mono">result_mismatch</span>); H3
                              inconclusive. Both stay in the report with their
                              reasons.
                            </dd>
                          </dl>
                        </Section>
                        <Section n={6} title="Integrity">
                          <div className="ri">
                            <div>
                              <div className="ri-st">
                                <span className="pill t-verified">
                                  <LpIcon name="checkCircle" size={12} />
                                  Stored evidence matches recorded fingerprints
                                </span>
                                <span className="illus">
                                  ◆ illustrative result
                                </span>
                              </div>
                              <div className="s">
                                Every stored file gets a fingerprint when the
                                report is sealed. Replay fingerprints the files
                                again and compares; it does not re-run anything
                                or prove authenticity. In this demo the result
                                is prerecorded, not computed in your browser.
                              </div>
                              <dl className="ri-kv">
                                <dt>Manifest</dt>
                                <dd>sha256:9f1c…e04a · 14 artifacts</dd>
                                <dt>Outcome</dt>
                                <dd>verified_recommendation</dd>
                                <dt>Sealed by</dt>
                                <dd>report-builder@1</dd>
                              </dl>
                            </div>
                            <button
                              type="button"
                              className="btn btn-secondary btn-sm"
                              onClick={() =>
                                select(
                                  1,
                                  () => mainRef.current && go(mainRef.current),
                                )
                              }
                            >
                              <LpIcon name="replay" size={13} />
                              Replay report
                            </button>
                          </div>
                        </Section>
                      </>
                    )}
                    {tab === 1 && (
                      <>
                        <div className="vh">
                          <div>
                            <span className="pill t-verified">
                              <LpIcon name="checkCircle" size={12} />
                              verified
                            </span>
                            <h3>
                              Integrity check passed against stored digests
                            </h3>
                            <div
                              style={{ fontSize: 12.5, color: "var(--muted)" }}
                            >
                              Report replay · 0 LLM calls · agents were not run
                              again
                            </div>
                          </div>
                          <div className="m">
                            <div
                              className="mono"
                              style={{ fontSize: 12, color: "var(--muted)" }}
                            >
                              replay attempt #1
                            </div>
                          </div>
                        </div>
                        <div className="checks" style={{ marginTop: 14 }}>
                          {[
                            ["Manifest digest matches", "sha256:9f1c…e04a"],
                            ["Events digest up to cutoff", "seq 0–184"],
                            ["Report JSON digest", "sha256:41be…0c7d"],
                            ["Artifacts re-hashed", "14 / 14"],
                            [
                              "Redisplayed from stored evidence",
                              "no recomputation",
                            ],
                          ].map(([a, b]) => (
                            <div className="check" key={a}>
                              <span
                                style={{
                                  color: "var(--verified)",
                                  display: "inline-flex",
                                }}
                              >
                                <LpIcon name="checkCircle" size={15} />
                              </span>
                              {a}
                              <span className="r">{b}</span>
                            </div>
                          ))}
                        </div>
                        <div className="plain" style={{ marginTop: 14 }}>
                          <LpIcon name="bulb" size={15} />
                          <span>
                            <b>In plain terms:</b> every stored file was
                            fingerprinted again and every fingerprint matched.
                            Nothing was re-run.
                          </span>
                        </div>
                        <p className="b" style={{ marginTop: 12 }}>
                          Replay shows the stored report is consistent with what
                          was recorded. It is not a proof of authenticity. To
                          measure again, use experiment replay; to rethink the
                          problem, start a re-investigation.
                        </p>
                      </>
                    )}
                    {tab === 2 && (
                      <>
                        <div
                          style={{
                            border: "1px solid var(--border)",
                            borderRadius: 10,
                            overflow: "auto",
                          }}
                        >
                          <table className="dt">
                            <thead>
                              <tr>
                                <th>Evidence</th>
                                <th>Kind</th>
                                <th>Fact</th>
                                <th>Source</th>
                              </tr>
                            </thead>
                            <tbody>
                              {EVIDENCE.map(([id, kind, fact, src]) => (
                                <tr
                                  key={id}
                                  id={`evrow-${id}`}
                                  className={flash === id ? "hl" : undefined}
                                >
                                  <td>
                                    <span className="chip-ev">{id}</span>
                                  </td>
                                  <td>{kind}</td>
                                  <td
                                    style={{ fontFamily: "var(--font-sans)" }}
                                  >
                                    {fact}
                                  </td>
                                  <td style={{ color: "var(--muted)" }}>
                                    {src}
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                        <p className="b" style={{ marginTop: 12 }}>
                          Every finding cites evidence IDs. Each one resolves to
                          a hashed artifact or measurement.
                        </p>
                      </>
                    )}
                  </div>
                </div>
              </div>
            </div>
          </Reveal>
        </div>
      </div>
    </section>
  );
}
