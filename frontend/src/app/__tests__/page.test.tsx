import { afterEach, expect, test } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import Page from "../page";

afterEach(cleanup);

test("home page explains the product and links to the labelled demo and the app", () => {
  render(<Page />);

  expect(screen.getByRole("heading", { level: 1, name: "QueryCure" })).toBeDefined();
  expect(screen.getByRole("link", { name: "Explore prerecorded investigations" }).getAttribute("href")).toBe("/demo");
  expect(screen.getByRole("link", { name: "Open the app" }).getAttribute("href")).toBe("/app");
  // The public-demo limits are stated, not implied.
  expect(screen.getByText(/benchmarks are prerecorded and labelled/)).toBeDefined();
});
