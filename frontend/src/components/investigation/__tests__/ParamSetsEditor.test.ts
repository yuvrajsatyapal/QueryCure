import { expect, test } from "vitest";
import { parseParamSets } from "../ParamSetsEditor";

test("rows become typed parameter sets; empty rows are skipped", () => {
  const { sets, error } = parseParamSets([
    { name: "hot", values: "[1024]" },
    { name: "", values: "" },
    { name: "text_key", values: '["feature_17", null, true]' },
  ]);

  expect(error).toBeNull();
  expect(sets).toEqual([
    { name: "hot", values: [1024] },
    { name: "text_key", values: ["feature_17", null, true] },
  ]);
});

test.each([
  [{ name: "bad name", values: "[1]" }, /name/],
  [{ name: "ok", values: "1024" }, /JSON array/],
  [{ name: "ok", values: "[[1]]" }, /numbers, strings/],
  [{ name: "ok", values: "{" }, /JSON array/],
])("invalid row %o is explained", (row, message) => {
  expect(parseParamSets([row]).error).toMatch(message);
});
