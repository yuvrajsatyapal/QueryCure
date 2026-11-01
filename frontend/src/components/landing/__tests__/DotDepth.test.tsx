import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { act, cleanup, render } from "@testing-library/react";
import { DotDepth } from "../DotDepth";

function mockReducedMotion(reduce: boolean) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn().mockImplementation(() => ({ matches: reduce, addEventListener: vi.fn(), removeEventListener: vi.fn() })),
  );
}

async function scrollTo(y: number) {
  await act(async () => {
    Object.defineProperty(window, "scrollY", { value: y, configurable: true });
    window.dispatchEvent(new Event("scroll"));
    await new Promise((r) => requestAnimationFrame(() => r(null)));
  });
}

beforeEach(() => {
  Object.defineProperty(window, "devicePixelRatio", { value: 1, configurable: true });
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

test("far layer trails the scroll", async () => {
  mockReducedMotion(false);
  const { container } = render(<DotDepth />);
  await scrollTo(300);
  expect((container.querySelector(".dot-depth") as HTMLElement).style.transform).toBe("translate3d(0, -30px, 0)");
});

test("stays still under prefers-reduced-motion", async () => {
  mockReducedMotion(true);
  const { container } = render(<DotDepth />);
  await scrollTo(300);
  expect((container.querySelector(".dot-depth") as HTMLElement).style.transform).toBe("");
});

test("stops listening when unmounted", async () => {
  mockReducedMotion(false);
  const remove = vi.spyOn(window, "removeEventListener");
  render(<DotDepth />).unmount();
  expect(remove).toHaveBeenCalledWith("scroll", expect.any(Function));
});
