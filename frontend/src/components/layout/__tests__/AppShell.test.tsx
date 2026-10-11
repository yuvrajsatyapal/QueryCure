import { afterEach, expect, test } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { SideNav } from "../SideNav";

afterEach(cleanup);

test("available sections are links; planned ones are visibly disabled, not dead links", () => {
  render(<SideNav />);

  expect(screen.getByRole("link", { name: "Dashboard" }).getAttribute("href")).toBe("/app");
  const planned = screen.getByText("History").closest("[aria-disabled]");
  expect(planned?.getAttribute("aria-disabled")).toBe("true");
  expect(screen.queryByRole("link", { name: /History/ })).toBeNull();
});
