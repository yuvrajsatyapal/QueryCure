import { afterEach, expect, test } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { SideNav } from "../SideNav";

afterEach(cleanup);

test("every section is a real link (no dead or placeholder entries)", () => {
  const { container } = render(<SideNav />);

  expect(screen.getByRole("link", { name: "Dashboard" }).getAttribute("href")).toBe("/app");
  expect(screen.getByRole("link", { name: "History" }).getAttribute("href")).toBe("/app/history");
  expect(screen.getByRole("link", { name: "Settings" }).getAttribute("href")).toBe("/app/settings");
  expect(screen.getByRole("link", { name: "Demo gallery" }).getAttribute("href")).toBe("/demo");
  expect(container.querySelector("[aria-disabled]")).toBeNull();
});
