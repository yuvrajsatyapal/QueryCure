import { afterEach, beforeAll, describe, expect, test, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { CtaSection, FlowStrip, Hero } from "../StaticSections";
import { GuardrailsSection } from "../GuardrailsSection";
import { RealDataSection } from "../RealDataSection";

/* The static landing sections make claims about the product. These tests keep those claims honest: the
 * workflow and safety model are stated as implemented, the dataset numbers equal the backend's pinned
 * values, and wording that would overstate the product (guarantees, tamper-proofing, speed-up figures) cannot return. */

beforeAll(() => {
  globalThis.IntersectionObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
    takeRecords() {
      return [];
    }
  } as unknown as typeof IntersectionObserver;
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
  vi.stubGlobal(
    "matchMedia",
    vi.fn().mockImplementation(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })),
  );
});
afterEach(cleanup);

function pageText(): string {
  const { container } = render(
    <>
      <Hero />
      <FlowStrip />
      <GuardrailsSection />
      <RealDataSection />
      <CtaSection />
    </>,
  );
  return container.textContent ?? "";
}

test("the workflow is investigate, hypothesize, approve, verify, report, with the human gate marked", () => {
  render(<FlowStrip />);

  const steps = screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent);
  expect(steps).toEqual(["Investigate", "Hypothesize", "Approve", "Verify", "Report"]);
  const gate = screen.getByText("Human gate");
  expect(gate.closest("li")?.textContent).toContain("Approve");
});

test("the safety model states approval before execution and an audit before 'verified'", () => {
  render(<GuardrailsSection />);

  expect(screen.getByRole("heading", { name: "No candidate runs without approval" })).toBeDefined();
  expect(screen.getByRole("heading", { name: "Verified means audited" })).toBeDefined();
  expect(screen.getByText(/A result counts as verified only after its audit has run/)).toBeDefined();
  expect(screen.getByText(/stays inconclusive and the report says why/)).toBeDefined();
  expect(screen.getByText(/never applies a change to a database you own/)).toBeDefined();
  expect(screen.getByText(/does not prove authenticity/)).toBeDefined();
});

describe("the dataset section", () => {
  test("shows the pinned values and says what is not claimed", () => {
    render(<RealDataSection />);

    for (const value of ["1,067,371", "10,608,492", "19,287,250.568", "243,007", "4,382"]) {
      expect(screen.getByText(value)).toBeDefined();
    }
    expect(screen.getByText("online_retail_ii@v1:data=b3471c34b273")).toBeDefined();
    expect(screen.getByText(/not yet benchmarked for performance/)).toBeDefined();
    expect(screen.getByText("The file stays on your machine.")).toBeDefined();
    expect(screen.getByText("doi.org/10.24432/C5CG6D")).toBeDefined();
    expect(screen.getByText(/CC BY 4\.0/)).toBeDefined();
  });

  const registry = resolve(process.cwd(), "../backend/src/querycure/workloads/registry.py");
  test.skipIf(!existsSync(registry))("equals the values pinned in the backend registry", () => {
    const source = readFileSync(registry, "utf8");
    render(<RealDataSection />);
    const text = document.body.textContent ?? "";

    for (const pinned of ["rows=1_067_371", "sum_quantity=10_608_492", 'sum_quantity_times_price="19287250.568"', "null_customers=243_007", "null_descriptions=4_382"]) {
      expect(source).toContain(pinned);
    }
    expect(source).toContain("b3471c34b27325f6f68aa58184689a076669885e27d15ebde92dcb198efd9840");
    expect(text).toContain("b3471c34b273");
  });
});

test("no section overstates the product: no guarantee, certification, tamper-proof or autonomy claim", () => {
  const text = pageText();

  expect(text).not.toMatch(/guarantee|tamper|certif|cryptographic|fully autonomous|production[- ]ready|prove the fix|reproducible evidence/i);
});

test("the new sections state no speed-up or timing figure", () => {
  const { container } = render(
    <>
      <FlowStrip />
      <GuardrailsSection />
      <RealDataSection />
      <CtaSection />
    </>,
  );

  expect(container.textContent).not.toMatch(/\d\s?×|\d\s?ms\b|faster|speed-?up of/i);
});

test("a speed-up figure in the hero's example is always labelled as a measured run, never as a QueryCure verdict", () => {
  const { container } = render(<Hero />);
  const text = container.textContent ?? "";

  if (/\d\s?×/.test(text)) {
    expect(text).toMatch(/Measured on PostgreSQL/);
    expect(text).toMatch(/independently of QueryCure.s investigation verdict/);
    expect(text).toMatch(/excludes network and client overhead/);
  }
});

test("the hero says what QueryCure does without promising an outcome", () => {
  render(<Hero />);

  expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Find out why your PostgreSQL queries are slow. Then test the fix first.");
  expect(screen.getByText(/only after your approval\. Every result is evaluated using measured\s+performance and supporting evidence/)).toBeDefined();
});
