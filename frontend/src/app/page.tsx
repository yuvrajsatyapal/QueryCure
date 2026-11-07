import { BenchmarkSection } from "@/components/landing/BenchmarkSection";
import { BranchingSection } from "@/components/landing/BranchingSection";
import { DotDepth } from "@/components/landing/DotDepth";
import { FeatureExplorer } from "@/components/landing/FeatureExplorer";
import { GuardrailsSection } from "@/components/landing/GuardrailsSection";
import { HowItWorks } from "@/components/landing/HowItWorks";
import { LandingNav } from "@/components/landing/LandingNav";
import { PauseOffscreen } from "@/components/landing/PauseOffscreen";
import { ProductScreens } from "@/components/landing/ProductScreens";
import { ProductShowcase } from "@/components/landing/ProductShowcase";
import { RealDataSection } from "@/components/landing/RealDataSection";
import { ReportShowcase } from "@/components/landing/ReportShowcase";
import { Bridge, CtaSection, FlowStrip, Hero, LandingFooter, ProblemBand } from "@/components/landing/StaticSections";
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
        <FlowStrip />
        <ProblemBand />
        <ProductScreens />
        <ProductShowcase />
        <HowItWorks />
        <GuardrailsSection />
        <Bridge icon="dashed" title="Zoom into · Hypotheses" sub="Each hypothesis becomes its own experiment" />
        <BranchingSection />
        <Bridge icon="gauge" title="Zoom into · H1, measured" sub="What “verified” actually rests on" />
        <BenchmarkSection />
        <Bridge icon="fileText" title="Into the report" sub="Everything above, sealed in one place" />
        <ReportShowcase />
        <RealDataSection />
        <FeatureExplorer />
        <CtaSection />
      </main>
      <LandingFooter />
      <PauseOffscreen />
    </div>
  );
}
