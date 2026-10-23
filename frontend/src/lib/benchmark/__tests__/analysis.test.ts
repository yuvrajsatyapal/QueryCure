import { describe, expect, test } from "vitest";
import type { ExperimentDetail, OptimizationCandidate, Verification } from "@/lib/api/types";
import {
  armDistribution,
  armsOf,
  classifyRecommendation,
  logTicks,
  measurementWarnings,
  paramSetsOf,
  quartiles,
  speedupRow,
  thresholdsOf,
} from "../analysis";
// A real bench@2 result recorded on 2026-10-23 from a local Docker stub-model run
// (orders_ecommerce@v1:sf=0.01, sandbox relay path). Samples and statistics are as stored.
import recorded from "./recorded-result.json";

type Result = NonNullable<ExperimentDetail["result"]>;
const result = recorded as unknown as Result;
const ARM = "oc_70a238eea02a";
const config = { minEffect: 1.1, maxRegression: 0.95, maxCv: 0.25, paramSets: [{ name: "hot_customer" }, { name: "regular_customer" }] };

describe("quartiles", () => {
  test("match the engine's inclusive method, so the box agrees with the stored IQR", () => {
    for (const s of result.stats) {
      for (const [arm, summary] of [["baseline", s.baseline], [s.arm, s.candidate]] as const) {
        const d = armDistribution(result, arm, s.paramSet);
        expect(d).not.toBeNull();
        expect(d!.q3Ns - d!.q1Ns).toBeCloseTo(summary.iqrNs, 6);
        expect(d!.medianNs).toBe(summary.medianNs);
      }
    }
  });

  test("small inputs follow Python's statistics.quantiles(method='inclusive')", () => {
    // statistics.quantiles([1, 2, 3, 4], n=4, method="inclusive") == [1.75, 2.5, 3.25]
    expect(quartiles([1, 2, 3, 4])).toEqual([1.75, 2.5, 3.25]);
    expect(quartiles([5])).toEqual([5, 5, 5]);
  });
});

test("armDistribution keeps arm and param set apart and never invents samples", () => {
  const d = armDistribution(result, ARM, "hot_customer");
  expect(d?.n).toBe(30);
  expect(d?.samplesNs).toHaveLength(30);
  expect(d?.failures).toEqual([]);
  expect(armDistribution(result, ARM, "no_such_set")).toBeNull();
  expect(armDistribution(result, "oc_unknown", "hot_customer")).toBeNull();
});

test("arms list the baseline first, then the tournament order; param sets follow the config", () => {
  expect(armsOf(result)).toEqual(["baseline", ARM]);
  expect(paramSetsOf(result, { paramSets: [{ name: "regular_customer" }, { name: "hot_customer" }] })).toEqual(["regular_customer", "hot_customer"]);
  expect(paramSetsOf(result, null)).toEqual(["hot_customer", "regular_customer"]);
});

describe("speedupRow", () => {
  test("shows the recorded speedup and CI for a comparable arm", () => {
    const row = speedupRow(result, ARM, "hot_customer");
    expect(row.status).toBe("shown");
    if (row.status !== "shown") return;
    expect(row.speedup).toBeCloseTo(1.585, 3);
    expect(row.ciLow).toBeCloseTo(1.472, 3);
    expect(row.ciHigh).toBeCloseTo(1.694, 3);
  });

  test("no statistic recorded: says so instead of computing one", () => {
    expect(speedupRow(result, ARM, "edge")).toEqual({ status: "absent", reason: "No speedup statistic recorded for this candidate and param set." });
  });

  test("results that differ from the baseline make the speedup not comparable", () => {
    const mismatch = { ...result, verdicts: [{ arm: ARM, verdict: "rejected", gate: 3, reasons: [{ code: "result_mismatch", detail: "row count differs" }] }] } as Result;
    expect(speedupRow(mismatch, ARM, "hot_customer")).toEqual({
      status: "absent",
      reason: "Not comparable: results differ from the baseline (result_mismatch).",
    });
  });

  test("a malformed statistic is not drawn", () => {
    const bad = { ...result, stats: result.stats.map((s) => ({ ...s, ciLow: s.speedup + 1 })) } as Result;
    expect(speedupRow(bad, ARM, "hot_customer").status).toBe("absent");
    const nan = { ...result, stats: result.stats.map((s) => ({ ...s, speedup: Number.NaN })) } as Result;
    expect(speedupRow(nan, ARM, "hot_customer").status).toBe("absent");
  });
});

describe("classifyRecommendation", () => {
  const candidate = (status: string) => ({ key: ARM, status }) as OptimizationCandidate;
  const audit = (engine: string, verdict: string, downgraded: boolean) =>
    ({ candidateKey: ARM, engineVerdict: engine, verdict, auditorDowngraded: downgraded }) as Verification;

  test("uses the engine verdict when there is no audit or replication", () => {
    expect(classifyRecommendation({ candidate: candidate("verified"), ruleVerdict: "verified" }).kind).toBe("verified");
    expect(classifyRecommendation({ candidate: candidate("rejected"), ruleVerdict: "rejected" }).kind).toBe("rejected");
    expect(classifyRecommendation({ candidate: candidate("inconclusive"), ruleVerdict: "inconclusive" }).kind).toBe("inconclusive");
  });

  test("an auditor downgrade is disputed, with both verdicts named", () => {
    const c = classifyRecommendation({ candidate: candidate("inconclusive"), ruleVerdict: "verified", audit: audit("verified", "inconclusive", true) });
    expect(c.kind).toBe("disputed");
    expect(c.detail).toBe("Engine verdict verified; Benchmark Auditor downgraded it to inconclusive.");
  });

  test("replication decides over the single experiment, and keeps its noise warning", () => {
    const c = classifyRecommendation({ candidate: candidate("verified_with_noise_warning"), ruleVerdict: "inconclusive", replicationVerdict: "verified_with_noise_warning" });
    expect(c.kind).toBe("verified_noise");
  });

  test("a candidate that was never measured is unverified", () => {
    for (const status of ["declined", "expired", "proposed", "approved"]) {
      expect(classifyRecommendation({ candidate: candidate(status) }).kind).toBe("unverified");
    }
  });
});

describe("measurementWarnings", () => {
  test("names a transport-dominated measurement with the recorded share", () => {
    const w = measurementWarnings(result, config);
    const transport = w.find((x) => x.code === "transport_dominated");
    expect(transport?.text).toBe(
      "Transport floor 0.23 ms is 61% of the fastest arm's median: much of each sample is network, relay and driver, which compresses speedups (ADR-0029).",
    );
  });

  test("always states that host contention is not recorded", () => {
    expect(measurementWarnings(result, config).find((x) => x.code === "host_contention_unrecorded")).toBeDefined();
  });

  test("flags robust CV above max_cv per arm and param set, and failed samples", () => {
    const noisy = {
      ...result,
      stats: result.stats.map((s) => (s.paramSet === "hot_customer" ? { ...s, candidate: { ...s.candidate, robustCv: 0.46 } } : s)),
      measurements: result.measurements.map((x) => (x.arm === "baseline" && x.paramSet === "regular_customer" ? { ...x, failures: ["timeout", "timeout"] } : x)),
    } as Result;
    const w = measurementWarnings(noisy, config).map((x) => x.text);
    expect(w).toContain(`${ARM} · hot_customer: robust CV 0.46 above max_cv 0.25.`);
    expect(w).toContain("baseline · regular_customer: 2 failed samples (timeout), not plotted.");
  });

  test("an older result without a transport floor says it was not recorded", () => {
    const old = { ...result, transportFloor: null } as Result;
    expect(measurementWarnings(old, config).find((x) => x.code === "transport_unrecorded")).toBeDefined();
  });
});

test("thresholdsOf reads only what the config recorded", () => {
  expect(thresholdsOf(config)).toEqual({ minEffect: 1.1, maxRegression: 0.95, maxCv: 0.25 });
  expect(thresholdsOf(null)).toEqual({ minEffect: null, maxRegression: null, maxCv: null });
  expect(thresholdsOf({ minEffect: "x" })).toEqual({ minEffect: null, maxRegression: null, maxCv: null });
});

test("logTicks spans the domain on a 1-2-5 sequence", () => {
  expect(logTicks(0.3, 4.4)).toEqual([0.5, 1, 2]);
  expect(logTicks(0.9, 1.1)).toEqual([1]);
});
