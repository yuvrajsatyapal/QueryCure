import { afterEach, beforeAll, describe, expect, test, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { existsSync } from "node:fs";
import { resolve } from "node:path";
import { ProductScreens } from "../ProductScreens";

beforeAll(() => {
  globalThis.IntersectionObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
    takeRecords() {
      return [];
    }
  } as unknown as typeof IntersectionObserver;
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
  vi.stubGlobal("matchMedia", vi.fn().mockImplementation(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
});
afterEach(cleanup);

describe("ProductScreens", () => {
  test("opens on Approval & audit and shows the Verified → provenance fails → Inconclusive transition", () => {
    render(<ProductScreens />);
    const tabs = screen.getAllByRole("tab");
    expect(tabs).toHaveLength(4);
    expect(screen.getByRole("tab", { name: /Approval & audit/ }).getAttribute("aria-selected")).toBe("true");
    const panel = screen.getByRole("tabpanel");
    expect(panel.textContent).toContain("Verified · tested scope");
    expect(panel.textContent).toContain("provenance check fails");
    expect(panel.textContent).toContain("Inconclusive");
  });

  test("arrow keys, Home and End move between tabs and show the matching panel", () => {
    render(<ProductScreens />);
    const list = screen.getByRole("tablist");
    fireEvent.keyDown(list, { key: "ArrowRight" });
    expect(screen.getByRole("tab", { name: /Report/ }).getAttribute("aria-selected")).toBe("true");
    expect(screen.getByRole("tabpanel").textContent).toContain("17 of 17 match the manifest");
    fireEvent.keyDown(list, { key: "Home" });
    expect(screen.getByRole("tab", { name: /Investigation/ }).getAttribute("aria-selected")).toBe("true");
    fireEvent.keyDown(list, { key: "End" });
    expect(screen.getByRole("tab", { name: /Report/ }).getAttribute("aria-selected")).toBe("true");
  });

  test("one subtle note states the stored-record basis, and nothing claims authenticity or demo status", () => {
    const { container } = render(<ProductScreens />);
    const text = container.textContent ?? "";
    expect(text).toContain("representative investigation records and stored measurements");
    expect(text).not.toMatch(/demo|prerecorded/i);
    expect(text).toContain("not proof of authenticity");
    expect(text).not.toMatch(/tamper|certified/i);
  });

  test("every screenshot asset exists in both themes", () => {
    const { container } = render(<ProductScreens />);
    const srcs = [...container.querySelectorAll("img")].map((i) => i.getAttribute("src") ?? "");
    expect(srcs.length).toBeGreaterThanOrEqual(12);
    for (const src of srcs) expect(existsSync(resolve(__dirname, "../../../../public", src.slice(1)))).toBe(true);
  });
});
