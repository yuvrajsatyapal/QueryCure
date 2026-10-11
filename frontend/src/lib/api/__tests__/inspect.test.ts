import { afterEach, expect, test, vi } from "vitest";
import { inspectPlan } from "../inspect";

afterEach(() => vi.unstubAllGlobals());

test("plan uploads are sent verbatim, without key case conversion", async () => {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ artifact_sha256: "a", plan: {}, metrics: [] }), {
      status: 200,
      headers: { "content-type": "application/json" },
    }),
  );
  vi.stubGlobal("fetch", fetchMock);
  const plan = '[{"Plan": {"Node Type": "Seq Scan", "Plan Rows": 5}}]';

  const result = await inspectPlan(plan);

  expect(fetchMock.mock.calls[0]![1].body).toBe(plan);
  expect(result.artifactSha256).toBe("a");
});
