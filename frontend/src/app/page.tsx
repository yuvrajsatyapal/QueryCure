import { BenchmarkSection } from "@/components/landing/BenchmarkSection";
import { BranchingSection } from "@/components/landing/BranchingSection";
import { DotDepth } from "@/components/landing/DotDepth";
import { FeatureExplorer } from "@/components/landing/FeatureExplorer";
import { HowItWorks } from "@/components/landing/HowItWorks";
import { LandingNav } from "@/components/landing/LandingNav";
import { PauseOffscreen } from "@/components/landing/PauseOffscreen";
import { ProductShowcase } from "@/components/landing/ProductShowcase";
import { ReportShowcase } from "@/components/landing/ReportShowcase";
import { Bridge, CtaSection, Hero, LandingFooter, ProblemBand } from "@/components/landing/StaticSections";
import "@/components/landing/landing.css";

/* Public landing page, ported from the approved prototype (docs/design/prototypes/landing). Styles are
 * scoped to `.lp`; every sample value is illustrative and labelled on the page. */
export default function Home() {
  return (
    <div className="lp flex flex-1 flex-col">
      <DotDepth />
      <LandingNav />
      <main>
        <Hero />
        <ProblemBand />
        <ProductShowcase />
        <HowItWorks />
        <Bridge icon="dashed" title="Zoom into · Hypotheses" sub="Each hypothesis becomes its own experiment" />
        <BranchingSection />
        <Bridge icon="gauge" title="Zoom into · H1, measured" sub="What “verified” actually rests on" />
        <BenchmarkSection />
        <Bridge icon="fileText" title="Into the report" sub="Everything above, sealed in one place" />
        <ReportShowcase />
        <FeatureExplorer />
        <CtaSection />
      </main>
      <LandingFooter />
      <PauseOffscreen />
    </div>
  );
}
