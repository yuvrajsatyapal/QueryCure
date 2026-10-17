import { expect, test } from "vitest";
import { manifestModelRows } from "../manifestModels";

const row = (agent: string, promptVersion: string, calls = 1) => ({
  agent,
  model: "m:free",
  promptVersion,
  calls,
});

test("repeated agent/model/prompt entries merge into one row with summed calls", () => {
  // A sealed manifest can list the same agent twice (e.g. two executions of one analyst).
  const rows = manifestModelRows([row("index_strategist", "index_strategist@1"), row("supervisor", "supervisor_plan@1"), row("index_strategist", "index_strategist@1", 2)]);

  expect(rows).toEqual([
    { key: "index_strategist|m:free|index_strategist@1", ...row("index_strategist", "index_strategist@1", 3) },
    { key: "supervisor|m:free|supervisor_plan@1", ...row("supervisor", "supervisor_plan@1") },
  ]);
});

test("a missing or malformed list yields no rows", () => {
  expect(manifestModelRows(undefined)).toEqual([]);
  expect(manifestModelRows("nope")).toEqual([]);
});
