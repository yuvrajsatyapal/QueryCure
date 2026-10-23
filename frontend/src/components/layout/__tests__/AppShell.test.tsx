import { afterEach, expect, test, vi } from "vitest";
import { cleanup, screen } from "@testing-library/react";
import { CommandProvider } from "@/components/command/CommandProvider";
import { renderWithQuery } from "@/test/render";
import { SideNav } from "../SideNav";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }), usePathname: () => "/app" }));

afterEach(cleanup);

test("every section is a real link (no dead or placeholder entries)", () => {
  const { container } = renderWithQuery(
    <CommandProvider>
      <SideNav />
    </CommandProvider>,
  );

  expect(screen.getByRole("link", { name: "Dashboard" }).getAttribute("href")).toBe("/app");
  expect(screen.getByRole("link", { name: "History" }).getAttribute("href")).toBe("/app/history");
  expect(screen.getByRole("link", { name: "Settings" }).getAttribute("href")).toBe("/app/settings");
  expect(screen.getByRole("link", { name: "Demo gallery" }).getAttribute("href")).toBe("/demo");
  expect(container.querySelector("[aria-disabled]")).toBeNull();
});
