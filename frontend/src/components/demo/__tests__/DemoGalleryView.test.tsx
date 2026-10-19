import { afterEach, expect, test, vi } from "vitest";
import { cleanup, screen, within } from "@testing-library/react";
import { renderWithQuery } from "@/test/render";
import { DemoGalleryView } from "../DemoGalleryView";

vi.mock("@/lib/api/demo", () => ({
  demoKeys: { gallery: ["demo"] },
  getDemoGallery: vi.fn().mockResolvedValue({
    items: [
      {
        slug: "orders",
        title: "Orders sandbox composite index",
        outcome: "verified_recommendation",
        headline: "A composite index removes the sort.",
        summary: "Tests a real index win.",
        model: "nvidia/nemotron:free",
        recordedAt: "2026-10-10",
        measurementsRecordedOn: "Apple M2, Docker",
      },
      {
        slug: "trap",
        title: "Rewrite trap",
        outcome: "inconclusive",
        headline: "Nothing could be shown.",
        summary: "s",
        model: "m:free",
        recordedAt: "2026-10-11",
        measurementsRecordedOn: null,
      },
    ],
    benchmarks: [
      {
        id: "b1",
        workloadId: "orders_ecommerce@v1",
        engineVersion: "bench@2",
        label: "Recorded on Apple M2, Docker. Not your database.",
        arms: [{ arm: "oc_1", kind: "create_index", verdict: "verified", reasons: [], ddl: ["CREATE INDEX ON orders (customer_id)"], query: null }],
        stats: [{ arm: "oc_1", paramSet: "hot", baselineMedianMs: "4.10", candidateMedianMs: "0.31", speedup: "13.2", ciLow: "11.9", ciHigh: "14.6", n: 30 }],
      },
    ],
  }),
}));

afterEach(cleanup);

test("every gallery card says it is prerecorded and keeps the API's words and numbers", async () => {
  renderWithQuery(<DemoGalleryView />);
  const investigations = await screen.findByRole("region", { name: "Investigations" });
  const cards = within(investigations).getAllByRole("listitem");
  expect(cards).toHaveLength(2);
  for (const card of cards) expect(within(card).getByText("Prerecorded")).toBeDefined();
  expect(within(cards[0]!).getByText("verified recommendation")).toBeDefined();
  expect(within(cards[0]!).getByText("A composite index removes the sort.")).toBeDefined();
  expect(within(cards[1]!).getByText("· no benchmark")).toBeDefined();

  const bench = screen.getByRole("region", { name: "Benchmark verdicts" });
  // The section banner says it too; the card itself must carry its own tag.
  expect(within(within(bench).getByRole("listitem")).getByText("Prerecorded")).toBeDefined();
  const row = within(bench).getByRole("row", { name: /hot/ });
  expect(row.textContent).toBe("hot4.10 ms0.31 ms13.2× (11.9–14.6×)30");
  expect(within(bench).getByText("Recorded on Apple M2, Docker. Not your database.")).toBeDefined();
});
