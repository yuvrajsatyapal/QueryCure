import { describe, expect, test } from "vitest";
import { toCamel, toSnake } from "../case";

describe("case conversion", () => {
  test("converts nested keys to camelCase", () => {
    expect(
      toCamel({ run_id: "r1", last_event_seq: 3, items: [{ evidence_ids: ["ev_1"] }], nested: { p95_ms: 2 } }),
    ).toEqual({ runId: "r1", lastEventSeq: 3, items: [{ evidenceIds: ["ev_1"] }], nested: { p95Ms: 2 } });
  });

  test("converts nested keys to snake_case", () => {
    expect(toSnake({ runId: "r1", paramSets: [{ valueList: [1] }] })).toEqual({
      run_id: "r1",
      param_sets: [{ value_list: [1] }],
    });
  });

  test("round-trips API-shaped payloads", () => {
    const wire = { investigation_id: "i", budget: { max_llm_calls: 40 }, modes: ["sandbox_benchmark"] };

    expect(toSnake(toCamel(wire))).toEqual(wire);
  });

  test("leaves values alone, including enum-like strings", () => {
    expect(toCamel({ status: "awaiting_approval", count: 0, ok: false, none: null })).toEqual({
      status: "awaiting_approval",
      count: 0,
      ok: false,
      none: null,
    });
  });

  test("does not walk into non-plain objects", () => {
    const date = new Date(0);

    expect(toCamel({ created_at: date }).createdAt).toBe(date);
  });
});
