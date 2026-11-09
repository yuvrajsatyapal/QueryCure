import Link from "next/link";
import { Logo } from "@/components/ui/Logo";
import { FooterTile } from "./FooterTile";
import { FinalCtas, FooterAuthLink, HeroCta } from "./LandingAuth";
import { LpIcon } from "./LpIcon";
import { QueryXRay } from "./QueryXRay";
import { Reveal } from "./Reveal";

export function Hero() {
  return (
    <section className="hero">
      <div className="wrap hero-grid">
        <div>
          <p className="eyebrow">PostgreSQL performance, with evidence</p>
          <h1>
            Find out why your PostgreSQL queries are slow. <em>Then test the fix first.</em>
          </h1>
          <p className="hero-sub">
            QueryCure uses AI to investigate SQL performance, identify likely causes, and propose evidence-backed fixes. Each candidate is tested in an isolated sandbox, only after your approval. Every result is evaluated using measured
            performance and supporting evidence.
          </p>
          <div className="hero-ctas">
            <HeroCta />
            <a href="#how" className="btn btn-secondary">
              See how it works
            </a>
          </div>
        </div>
        <QueryXRay />
      </div>
    </section>
  );
}

const FLOW = [
  ["search", "Investigate", "Reads your SQL, execution plan, and schema. Live database inspection is read-only."],
  ["dashed", "Hypothesize", "Proposes likely causes, each one a hypothesis backed by cited evidence."],
  ["hand", "Approve", "Review the exact SQL for each candidate. Nothing runs without your approval."],
  ["gauge", "Verify", "Approved candidates are tested in an isolated sandbox. Benchmark rules check correctness and measured performance."],
  ["fileText", "Report", "A sealed report preserving findings, evidence, and the limits of the investigation."],
] as const;

/** The whole workflow in five steps, with the one human gate called out. */
export function FlowStrip() {
  return (
    <section className="flow" aria-label="The workflow in five steps">
      <div className="wrap">
        <ol className="flow-list">
          {FLOW.map(([icon, title, body], i) => {
            const gate = title === "Approve";
            return (
              <li key={title} className={gate ? "flow-gate" : undefined}>
                <Reveal>
                  <span className="flow-ic">
                    <LpIcon name={icon} size={16} />
                  </span>
                  <p className="eyebrow">
                    {String(i + 1).padStart(2, "0")}
                    {gate ? <span className="pill t-approval sm">Human gate</span> : null}
                  </p>
                  <h3>{title}</h3>
                  <p>{body}</p>
                </Reveal>
              </li>
            );
          })}
        </ol>
      </div>
    </section>
  );
}

const PROBLEMS = [
  ["01 · The plan", "A plan shows what ran, not why.", "Seq scans, sorts and misestimates are symptoms. Finding the cause means reading the plan against the schema, the indexes and the statistics together."],
  ["02 · The advice", "Suggestions are cheap. Measurements aren't.", "An index that looks right can do nothing, slow down writes, or change results. It has to be tested before anyone calls it a fix."],
  ["03 · The proof", "One fast run isn't evidence.", "Noise, warm caches and small samples can make a change look faster than it is. A claim needs repeated measurements and a stated uncertainty."],
] as const;

export function ProblemBand() {
  return (
    <section className="band" aria-label="Why slow queries are hard">
      <div className="wrap band-grid">
        {PROBLEMS.map(([eyebrow, title, body]) => (
          <Reveal key={eyebrow}>
            <p className="eyebrow">{eyebrow}</p>
            <h3>{title}</h3>
            <p>{body}</p>
          </Reveal>
        ))}
      </div>
    </section>
  );
}

/** Dashed connector between two zoom levels of the story ("Zoom into · …"). */
export function Bridge({ icon, title, sub }: { icon: "dashed" | "gauge" | "fileText"; title: string; sub: string }) {
  return (
    <div className="wrap">
      <Reveal className="bridge" aria-hidden="true">
        <span className="bl" />
        <span className="pkt" />
        <span className="bp">
          <LpIcon name={icon} size={14} />
          {title}
          <span className="bs">{sub}</span>
        </span>
        <span className="bl b2" />
      </Reveal>
    </div>
  );
}

export function CtaSection() {
  return (
    <section className="cta">
      <div className="wrap">
        <h2>
          Stop guessing.
          <br />
          <span>Start investigating.</span>
        </h2>
        <p>Understand slow PostgreSQL queries with measured experiments and evidence you can re-check.</p>
        <div className="hero-ctas">
          <FinalCtas />
        </div>
      </div>
    </section>
  );
}

export function LandingFooter() {
  return (
    <footer className="ft in">
      <div className="wrap ft-top">
        <div className="ft-brand">
          <Link href="/" className="brand">
            <Logo size={22} />
            QueryCure
          </Link>
        </div>
        <nav className="ft-links" aria-label="Footer">
          <a href="https://github.com/yuvrajsatyapal/QueryCure/tree/main/docs">Docs</a>
          <a href="https://github.com/yuvrajsatyapal/QueryCure">GitHub</a>
          <FooterAuthLink />
        </nav>
      </div>
      <div className="wrap ft-bottom">
        <span>© 2026 QueryCure</span>
        <span>PostgreSQL query optimization · Sandbox-first · Human-approved changes</span>
      </div>
      <div className="ft-mega" aria-hidden="true">
        <span className="ft-word">QueryCure</span>
        <FooterTile />
      </div>
    </footer>
  );
}
