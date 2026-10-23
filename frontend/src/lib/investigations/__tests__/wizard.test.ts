import { describe, expect, test } from "vitest";
import { buildCreateInput, modeOptions, resolveMode } from "../wizard";

describe("modeOptions", () => {
  test("offline is always available; live needs a chosen connection; sandbox needs a workload", () => {
    const none = modeOptions({ source: "none" });
    expect(none.map((m) => [m.mode, m.available])).toEqual([
      ["offline", true],
      ["live_inspection", false],
      ["sandbox_benchmark", false],
    ]);
    expect(none[1]?.reason).toBe("Choose a connection in Plan source.");
    expect(none[2]?.reason).toBe("Choose a demo workload in Plan source.");

    // A connection id left over from another source does not unlock live inspection.
    expect(modeOptions({ source: "upload", connectionId: "c1" })[1]?.available).toBe(false);
    expect(modeOptions({ source: "live", connectionId: "c1" })[1]?.available).toBe(true);
    expect(modeOptions({ source: "workload", workloadId: "w:sf=0.1:seed=1" })[2]?.available).toBe(true);
  });
});

describe("resolveMode", () => {
  test("defaults to the mode the source implies, as before the guided flow", () => {
    expect(resolveMode(null, { source: "upload" })).toBe("offline");
    expect(resolveMode(null, { source: "live", connectionId: "c1" })).toBe("live_inspection");
    expect(resolveMode(null, { source: "workload", workloadId: "w" })).toBe("sandbox_benchmark");
    expect(resolveMode(null, { source: "live" })).toBe("offline");
  });

  test("a chosen mode sticks only while the source still allows it", () => {
    expect(resolveMode("offline", { source: "live", connectionId: "c1" })).toBe("offline");
    expect(resolveMode("sandbox_benchmark", { source: "upload" })).toBe("offline");
  });
});

describe("buildCreateInput", () => {
  const base = { title: "t", objective: "o", query: "SELECT 1", paramSets: [] };

  test("offline sends the uploaded plan only for an upload source, never a connection", () => {
    expect(
      buildCreateInput({ ...base, mode: "offline", source: { source: "upload", connectionId: "c1" }, planArtifactSha256: "abc" }),
    ).toEqual({ ...base, modes: ["offline"], planArtifactSha256: "abc" });
    expect(
      buildCreateInput({ ...base, mode: "offline", source: { source: "live", connectionId: "c1" }, planArtifactSha256: "abc" }),
    ).toEqual({ ...base, modes: ["offline"] });
  });

  test("live inspection sends the connection; sandbox sends the workload and the pre-authorization flag", () => {
    expect(buildCreateInput({ ...base, mode: "live_inspection", source: { source: "live", connectionId: "c1" } })).toEqual({
      ...base,
      modes: ["live_inspection"],
      connectionId: "c1",
    });
    expect(
      buildCreateInput({ ...base, mode: "sandbox_benchmark", source: { source: "workload", workloadId: "w" }, preAuthorize: true }),
    ).toEqual({ ...base, modes: ["sandbox_benchmark"], workloadId: "w", preAuthorizeDemoSandbox: true });
  });
});
