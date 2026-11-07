"use client";

import Image from "next/image";
import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { Reveal } from "./Reveal";

/* Product screens: clips of a stored QueryCure investigation, captured by
 * frontend/scripts/capture-landing-shots.cjs. Nothing is drawn or edited. Sizes are CSS pixels (the files are 2x). */

type Shot = { name: string; w: number; h: number; alt: string; label?: string; max?: number };
type Fact = { k: string; v: string; note: string; tone?: "inconclusive" | "verified" };
type Screen = { tab: string; title: string; body: string; points: string[]; shots: Shot[]; facts?: Fact[]; shift?: boolean };

const DEFAULT_TAB = 2; // Approval & audit: the screen that shows the safety model

const SCREENS: Screen[] = [
  {
    tab: "Investigation",
    title: "Start from the query and its plan",
    body: "QueryCure reads the SQL and its EXPLAIN plan, checks whether the problem is material, and points at where the time goes. Here a sequential scan accounts for 91.1% of the runtime and removes 989,988 rows by filter.",
    points: ["The exact query under investigation", "Plan facts tagged imported, with estimated and actual rows", "A materiality check before any fix is considered"],
    shots: [
      {
        name: "investigation",
        w: 756,
        h: 346,
        alt: "The query SELECT * FROM orders WHERE customer_id = $1 ORDER BY created_at DESC LIMIT 20, and the observed problem: a material scan of 1,000,002 rows, with the sequential scan on orders as the hottest node, 989,988 rows removed by filter.",
      },
    ],
  },
  {
    tab: "Hypotheses",
    title: "Causes are hypotheses, not conclusions",
    body: "Each likely cause is stated with a confidence and labelled AI-written. Facts taken from the plan are labelled imported. Nothing here was benchmarked, so the report says no change is recommended as verified.",
    points: ["A confidence per hypothesis", "AI-written claims and imported plan facts are labelled apart", "No benchmark means no verified recommendation"],
    shots: [
      {
        name: "hypotheses",
        w: 756,
        h: 384,
        alt: "Three AI-written hypotheses (missing index, cardinality misestimate, inefficient sort) each with a confidence, followed by the recommendation: no change is recommended as verified.",
      },
    ],
  },
  {
    tab: "Approval & audit",
    title: "Approval on record, then an audit",
    body: "Each candidate's exact SQL is recorded with its approval (here pre-authorized for this workload). After measurement the Benchmark Auditor runs deterministic checks. The auditor can downgrade a verdict, never upgrade one.",
    points: ["Candidate SQL shown exactly, with its approval", "Re-scoring, approval digest, environment, provenance, dispersion, correctness and plan change are checked", "A failed check downgrades the verdict"],
    shift: true,
    shots: [
      {
        name: "audit",
        label: "Benchmark Auditor checks for the composite-index candidate",
        max: 840,
        w: 722,
        h: 412,
        alt: "The Benchmark Auditor's checks for one candidate: rescore, approval, config, environment, samples, param sets, dispersion, correctness and plan change pass; provenance fails because the samples are stored rather than freshly measured. The verdict goes from Verified to Inconclusive.",
      },
      {
        name: "approval",
        label: "Approval record and exact candidate SQL",
        max: 840,
        w: 756,
        h: 337,
        alt: "Round 1: approval approved by pre_authorized, and two candidate index definitions with their exact CREATE INDEX SQL, both marked Inconclusive.",
      },
    ],
  },
  {
    tab: "Report",
    title: "A report that states its limits",
    body: "The report gives the verdict, what was and was not measured, its limitations and its provenance. “Check stored digests” recomputes the SHA-256 of every shipped artifact and compares it with the manifest.",
    points: [],
    facts: [
      { k: "Final verdict", v: "Inconclusive", note: "The investigation could not reach a verified conclusion.", tone: "inconclusive" },
      { k: "Stored artifacts", v: "17 of 17 match the manifest", note: "A consistency check of stored digests. It is not a full report replay and not proof of authenticity.", tone: "verified" },
      { k: "Limitations", v: "Sandbox-only · stored samples", note: "Measured on a disposable copy of the sample workload; only the listed parameter sets were tested." },
    ],
    shots: [
      {
        name: "report-header",
        max: 840,
        w: 872,
        h: 530,
        alt: "The report header: Inconclusive, with a sandbox-only banner and a stored-measurements banner, above the result of the stored digest check: all 17 shipped artifacts match the manifest, which shows consistency and not proof of authenticity.",
      },
      {
        name: "report-body",
        max: 840,
        w: 756,
        h: 743,
        alt: "The report's limitations, next steps, and provenance and integrity sections, including the model calls made and the sealed event digest.",
      },
    ],
  },
];

// Pinned-card layout (must match landing.css): breakpoint and the card's top offset, and the page-scroll pixels spent
// per pixel of screenshot so the long screens read slowly instead of flying by.
const PIN_MIN_WIDTH = 861;
const CARD_STICK = 96;
const SCROLL_DRAG = 1.8;

/** Wide screens: the caption and frame pin under the nav at a fixed height while page scrolling slides the stacked
 * screenshots through the frame (no inner scrollbar, nothing trapped: the stage just adds scroll distance). Narrow
 * screens: plain flow. Only used for screens with more than one stacked shot. */
function PinnedBody({ active, children }: { active: boolean; children: (slideRef: React.RefObject<HTMLDivElement | null>, viewRef: React.RefObject<HTMLDivElement | null>) => React.ReactNode }) {
  const stageRef = useRef<HTMLDivElement>(null);
  const viewRef = useRef<HTMLDivElement>(null);
  const slideRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const stage = stageRef.current;
    const view = viewRef.current;
    const slide = slideRef.current;
    if (!active || !stage || !view || !slide) return;
    const card = stage.firstElementChild as HTMLElement | null;
    let raf = 0;
    const run = () => {
      raf = 0;
      if (window.innerWidth < PIN_MIN_WIDTH) {
        stage.style.height = "";
        slide.style.transform = "";
        card?.classList.remove("engaged");
        return;
      }
      const overflow = Math.max(0, slide.scrollHeight - view.clientHeight);
      stage.style.height = `${(card?.offsetHeight ?? 0) + overflow * SCROLL_DRAG}px`;
      const start = stage.getBoundingClientRect().top + window.scrollY - CARD_STICK;
      const scrolled = window.scrollY - start;
      const off = Math.min(overflow, Math.max(0, scrolled / SCROLL_DRAG));
      slide.style.transform = `translate3d(0,${-off}px,0)`;
      card?.classList.toggle("engaged", scrolled > 2 && scrolled < overflow * SCROLL_DRAG - 2);
    };
    const queue = () => {
      if (!raf) raf = requestAnimationFrame(run);
    };
    const ro = new ResizeObserver(queue);
    ro.observe(slide);
    ro.observe(view);
    window.addEventListener("scroll", queue, { passive: true });
    window.addEventListener("resize", queue);
    run();
    return () => {
      ro.disconnect();
      window.removeEventListener("scroll", queue);
      window.removeEventListener("resize", queue);
      cancelAnimationFrame(raf);
    };
  }, [active]);

  return (
    <div className="ps-stage" ref={stageRef}>
      <div className="ps-body ps-pin">{children(slideRef, viewRef)}</div>
    </div>
  );
}

/** The key transition in the audit screenshot, restated from its text: Verified, then a failed provenance check, then Inconclusive. */
function VerdictShift() {
  return (
    <div className="ps-shift">
      <ol aria-label="Verdict transition for candidate oc_07150a9c30d7">
        <li>
          <span className="pill t-verified">✓ Verified · tested scope</span>
          <span className="ps-sub">Initial verdict for the composite-index candidate</span>
        </li>
        <li className="ps-arrow" aria-hidden="true">→</li>
        <li>
          <span className="pill t-rejected">✕ provenance check fails</span>
          <span className="ps-sub">Only freshly measured samples pass the provenance check.</span>
        </li>
        <li className="ps-arrow" aria-hidden="true">→</li>
        <li>
          <span className="pill t-inconclusive">? Inconclusive</span>
          <span className="ps-sub">Downgraded by the Benchmark Auditor</span>
        </li>
      </ol>
      <p>An initially verified candidate is downgraded when the auditor finds the evidence insufficient. The other nine checks passed and one was skipped; the auditor can only downgrade a verdict, never upgrade it.</p>
    </div>
  );
}

function Caption({ s }: { s: Screen }) {
  return (
    <div className="ps-cap">
      <h3>{s.title}</h3>
      <p>{s.body}</p>
      {s.points.length > 0 && (
        <ul>
          {s.points.map((p) => (
            <li key={p}>{p}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Frame({ s, slideRef, viewRef }: { s: Screen; slideRef?: React.RefObject<HTMLDivElement | null>; viewRef?: React.RefObject<HTMLDivElement | null> }) {
  return (
    <figure className="ps-frame">
      <figcaption>
        <span className="tag">Inside QueryCure</span>
        {slideRef && <span className="ps-hint">Keep scrolling to read on</span>}
      </figcaption>
      <div className="ps-view" ref={viewRef}>
        <div className="ps-shots" ref={slideRef}>
          {s.shots.map((shot) => (
            <div key={shot.name} className="ps-shot" style={{ maxWidth: shot.max ?? shot.w }}>
              {shot.label && <div className="ps-lbl">{shot.label}</div>}
              <Image className="ps-d" src={`/landing/product/${shot.name}-dark.png`} alt={shot.alt} width={shot.w} height={shot.h} sizes="(max-width: 900px) 100vw, 780px" unoptimized />
              <Image className="ps-l" src={`/landing/product/${shot.name}-light.png`} alt={shot.alt} width={shot.w} height={shot.h} sizes="(max-width: 900px) 100vw, 780px" unoptimized />
            </div>
          ))}
        </div>
      </div>
    </figure>
  );
}

/** The four real product screens, in tabs (opens on Approval & audit). Arrow keys, Home and End move between tabs; no motion beyond the shared reveal. */
export function ProductScreens() {
  const [active, setActive] = useState(DEFAULT_TAB);
  const uid = useId();
  const tabs = useRef<(HTMLButtonElement | null)[]>([]);

  function onKey(event: KeyboardEvent<HTMLDivElement>) {
    const last = SCREENS.length - 1;
    const next = { ArrowRight: active === last ? 0 : active + 1, ArrowLeft: active === 0 ? last : active - 1, Home: 0, End: last }[event.key];
    if (next === undefined) return;
    event.preventDefault();
    setActive(next);
    tabs.current[next]?.focus();
  }

  return (
    <section className="sec ps" id="screens" style={{ paddingTop: 96, paddingBottom: 32 }}>
      <div className="wrap">
        <Reveal className="sec-head center">
          <p className="eyebrow">Inside QueryCure</p>
          <h2>
            An investigation,
            <br />
            <span>from query to evidence backed report.</span>
          </h2>
          <p>Explore how QueryCure investigates database performance, evaluates candidate fixes and produces evidence-backed reports.</p>
          <p className="ps-note">Product walkthrough using representative investigation records and stored measurements.</p>
        </Reveal>
        <div className="ps-tabs" role="tablist" aria-label="Product screens" onKeyDown={onKey}>
          {SCREENS.map((s, i) => (
            <button
              key={s.tab}
              ref={(el) => {
                tabs.current[i] = el;
              }}
              id={`${uid}-tab-${i}`}
              type="button"
              role="tab"
              aria-selected={i === active}
              aria-controls={`${uid}-panel-${i}`}
              tabIndex={i === active ? 0 : -1}
              className="ps-tab"
              onClick={() => setActive(i)}
            >
              <span className="mono">{String(i + 1).padStart(2, "0")}</span>
              {s.tab}
            </button>
          ))}
        </div>
        {SCREENS.map((s, i) => (
          <div key={s.tab} id={`${uid}-panel-${i}`} role="tabpanel" aria-labelledby={`${uid}-tab-${i}`} hidden={i !== active} className="ps-panel">
            {s.shift && <VerdictShift />}
            {s.facts && (
              <dl className="ps-facts">
                {s.facts.map((f) => (
                  <div key={f.k}>
                    <dt>{f.k}</dt>
                    <dd className={f.tone ? `t-${f.tone}` : undefined}>{f.v}</dd>
                    <dd className="n">{f.note}</dd>
                  </div>
                ))}
              </dl>
            )}
            {s.shots.length > 1 ? (
              <PinnedBody active={i === active}>
                {(slideRef, viewRef) => (
                  <>
                    <Caption s={s} />
                    <Frame s={s} slideRef={slideRef} viewRef={viewRef} />
                  </>
                )}
              </PinnedBody>
            ) : (
              <div className="ps-body">
                <Caption s={s} />
                <Frame s={s} />
              </div>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}
