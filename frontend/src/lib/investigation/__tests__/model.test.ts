import { expect, test } from "vitest";
import { runModelLabel } from "../model";

const base = { kind: "initial", status: "running", llmModel: null, llmProvider: null };

test("a recorded model is shown with its provider, whatever the run kind or status", () => {
  const recorded = { llmModel: "stub-model", llmProvider: "stub" };
  expect(runModelLabel({ ...base, ...recorded })).toBe("stub-model via stub");
  expect(runModelLabel({ ...base, ...recorded, status: "completed" })).toBe("stub-model via stub");
  expect(runModelLabel({ ...base, ...recorded, kind: "experiment_replay" })).toBe("stub-model via stub");
});

test("an experiment replay never calls a model, in any status", () => {
  for (const status of ["queued", "running", "completed", "failed", "cancelled"]) {
    expect(runModelLabel({ ...base, kind: "experiment_replay", status })).toBe("No model calls · Sandbox replay");
  }
});

test("a finished run without a recorded model used none", () => {
  for (const status of ["completed", "failed", "cancelled"]) {
    for (const kind of ["initial", "reinvestigation"]) {
      expect(runModelLabel({ ...base, kind, status })).toBe("No model used");
    }
  }
});

test("an unfinished run without a recorded model has not been assigned one yet", () => {
  for (const status of ["queued", "running", "awaiting_approval", "cancelling"]) {
    expect(runModelLabel({ ...base, status })).toBe("Model not assigned yet");
  }
});
