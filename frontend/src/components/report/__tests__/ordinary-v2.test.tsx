import { afterEach, expect, test, vi } from "vitest";
import { cleanup, render } from "@testing-library/react";
import type { ReactElement } from "react";
import fixtures from "@/test/fixtures/report-v2-ordinary.json";
import type { ReportV1 } from "@/lib/report/types";
import { reportSections } from "@/lib/report/sections";
import { ReportView } from "../ReportView";
import { ResultSummary } from "../ResultSummary";

/* Ordinary investigations sealed with report-builder@2 (REPLAY_OUTCOME_AUDIT §18.3): real builder
 * output for every ordinary shape. Each must render exactly like its report-builder@1 twin (the
 * same JSON without the three additive fields), apart from the builder version it names. */

afterEach(cleanup);

type Name = Exclude<keyof typeof fixtures, "_note">;
const names = Object.keys(fixtures).filter((n) => n !== "_note") as Name[];
const v2 = (name: Name) => fixtures[name] as unknown as ReportV1;

/** The v1 report the same inputs produce: v2 minus schema version, builder and origin. */
function asV1(r: ReportV1): ReportV1 {
  const recommendation = { ...r.recommendation } as ReportV1["recommendation"] & { origin?: string };
  delete recommendation.origin;
  return { ...r, schemaVersion: 1, builderVersion: "report-builder@1", recommendation } as ReportV1;
}

const text = (ui: ReactElement) => {
  const { container } = render(ui);
  const out = (container.textContent ?? "").replaceAll("report-builder@2", "report-builder@1").replaceAll("schema 2", "schema 1");
  cleanup();
  return out;
};

test.each(names)("ordinary schema-2 report renders like its v1 twin: %s", (name) => {
  const r = v2(name);
  expect(r.schemaVersion).toBe(2);
  expect(r.run.kind).not.toBe("experiment_replay");
  expect(r.recommendation).toMatchObject({ origin: "run" });
  expect(reportSections(r)).toEqual(reportSections(asV1(r)));
  expect(text(<ReportView report={r} />)).toBe(text(<ReportView report={asV1(r)} />));
  const noop = vi.fn();
  expect(text(<ResultSummary report={r} onReport={noop} onBenchmark={noop} />)).toBe(text(<ResultSummary report={asV1(r)} onReport={noop} onBenchmark={noop} />));
});

test("ordinary schema-2 reports carry no replay result, legacy notice or replay wording", () => {
  for (const name of names) {
    const { container } = render(<ReportView report={v2(name)} />);
    expect(container.textContent).not.toMatch(/Earlier replay classification|Experiment replay result|reproduced by this replay/i);
    cleanup();
  }
});
