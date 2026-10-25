import { expect, test } from "vitest";
import { disambiguateTitles } from "../titles";

const inv = (id: string, title: string, createdAt: string) => ({ id, title, createdAt });

test("unique titles need no detail", () => {
  const out = disambiguateTitles([inv("a", "Slow orders", "2026-10-20T10:00:00Z"), inv("b", "Slow invoices", "2026-10-20T10:00:00Z")], "UTC");
  expect(out.size).toBe(0);
});

test("repeated titles (ignoring case and spaces) get their recorded creation time", () => {
  const out = disambiguateTitles(
    [inv("a", "Slow orders", "2026-10-20T10:05:00Z"), inv("b", " slow ORDERS ", "2026-10-21T14:30:00Z"), inv("c", "Other", "2026-10-21T14:30:00Z")],
    "UTC",
  );
  expect(out.get("a")).toMatch(/Oct 20.*10:05/);
  expect(out.get("b")).toMatch(/Oct 21.*2:30/);
  expect(out.has("c")).toBe(false);
});

test("repeats created in the same minute also show a short investigation ID", () => {
  const out = disambiguateTitles(
    [
      inv("1b2c3d4e-0000-4000-8000-000000000001", "Slow orders", "2026-10-20T10:05:10Z"),
      inv("9f8e7d6c-0000-4000-8000-000000000002", "Slow orders", "2026-10-20T10:05:40Z"),
    ],
    "UTC",
  );
  expect(out.get("1b2c3d4e-0000-4000-8000-000000000001")).toMatch(/10:05.* · 1b2c3d4e$/);
  expect(out.get("9f8e7d6c-0000-4000-8000-000000000002")).toMatch(/10:05.* · 9f8e7d6c$/);
});
