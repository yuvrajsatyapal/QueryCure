import { afterEach, expect, test, vi } from "vitest";
import { cleanup, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithQuery } from "@/test/render";
import { ApiError } from "@/lib/api/client";
import type { ExperimentSummary } from "@/lib/api/types";
import { ReplayConfirm } from "../ReplayView";

const replayExperiment = vi.fn();
vi.mock("@/lib/api/reports", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  replayExperiment: (...a: unknown[]) => replayExperiment(...a),
}));
vi.mock("@/lib/api/optimization", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  getExperiment: () =>
    Promise.resolve({ config: { candidates: [{ arm: "oc_1", ddl: ["CREATE INDEX ON orders (customer_id)"], query: null }] } }),
}));

afterEach(() => {
  cleanup();
  replayExperiment.mockReset();
});

const experiment = { id: "exp-1", status: "completed" } as unknown as ExperimentSummary;

test("a retried confirmation reuses one Idempotency-Key, so the server returns the original attempt", async () => {
  replayExperiment
    .mockRejectedValueOnce(new ApiError("TIMEOUT", "The request timed out.", 504, [], null))
    .mockResolvedValueOnce({ id: "attempt-1", status: "queued" });
  const onDone = vi.fn();
  renderWithQuery(<ReplayConfirm experiment={experiment} runId="run-1" onDone={onDone} />);
  const confirm = await screen.findByRole("button", { name: "Confirm and re-run" });
  await waitFor(() => expect((confirm as HTMLButtonElement).disabled).toBe(false));

  await userEvent.click(confirm);
  await screen.findByRole("alert");
  await userEvent.click(screen.getByRole("button", { name: "Confirm and re-run" }));

  await waitFor(() => expect(onDone).toHaveBeenCalled());
  expect(replayExperiment).toHaveBeenCalledTimes(2);
  const [first, second] = replayExperiment.mock.calls;
  expect(first?.[0]).toBe("exp-1");
  expect(first?.[1]).toMatch(/^[0-9a-f-]{36}$/);
  expect(second?.[1]).toBe(first?.[1]);
});
