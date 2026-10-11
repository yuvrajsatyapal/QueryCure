import { afterEach, expect, test } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import Page from "../page";

afterEach(cleanup);

test("home page names the product and states the project phase", () => {
  render(<Page />);

  expect(screen.getByRole("heading", { level: 1, name: "QueryDoctor AI" })).toBeDefined();
  expect(screen.getByText(/Phase 1/)).toBeDefined();
});
