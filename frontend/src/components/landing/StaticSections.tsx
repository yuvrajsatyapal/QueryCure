import Link from "next/link";
import { Logo } from "@/components/ui/Logo";
import { FooterTile } from "./FooterTile";
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
            Find out why your PostgreSQL queries are slow. <em>Then prove the fix.</em>
          </h1>
          <p className="hero-sub">Analyze slow PostgreSQL queries, uncover bottlenecks, test potential fixes, and verify the results with reproducible evidence.</p>
          <div className="hero-ctas">
            <Link href="/demo" className="btn btn-primary">
              Explore Demo <LpIcon name="arrowRight" size={15} />
            </Link>
            <Link href="/app" className="btn btn-secondary">
              Open QueryCure
            </Link>
          </div>
          <p className="hero-note">
            <span className="dot" />
            The public demo uses prerecorded investigations, labelled as such.
          </p>
        </div>
        <QueryXRay />
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
        <p>Understand slow PostgreSQL queries with measured experiments and reproducible evidence.</p>
        <div className="hero-ctas">
          <Link href="/demo" className="btn btn-primary">
            Explore Demo <LpIcon name="arrowRight" size={15} />
          </Link>
          <Link href="/sign-in" className="btn btn-secondary">
            Get Started
          </Link>
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
          <Link href="/demo">Demo</Link>
          <a href="https://github.com/yuvrajsatyapal/QueryCure/tree/main/docs">Docs</a>
          <a href="https://github.com/yuvrajsatyapal/QueryCure">GitHub</a>
          <Link href="/sign-in">Sign in</Link>
        </nav>
      </div>
      <div className="wrap ft-bottom">
        <span>© 2026 QueryCure</span>
        <span>PostgreSQL query investigation · Sandbox-first · Sample data on this page is illustrative</span>
      </div>
      <div className="ft-mega" aria-hidden="true">
        <span className="ft-word">QueryCure</span>
        <FooterTile />
      </div>
    </footer>
  );
}
