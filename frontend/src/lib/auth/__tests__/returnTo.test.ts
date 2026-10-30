import { afterEach, expect, test, vi } from "vitest";
import { DEFAULT_RETURN_TO, PENDING_RETURN_KEY, rememberReturnTo, rememberedReturnTo, safeReturnTo, signInHref } from "../returnTo";

afterEach(() => {
  vi.restoreAllMocks();
  sessionStorage.clear();
});

test("same-site paths are kept, with their query and fragment", () => {
  expect(safeReturnTo("/app/history")).toBe("/app/history");
  expect(safeReturnTo("/app/investigations/abc?tab=report#finding-2")).toBe("/app/investigations/abc?tab=report#finding-2");
  expect(safeReturnTo("/demo")).toBe("/demo");
});

test("anything that could leave the site falls back to the dashboard", () => {
  for (const value of [
    "https://evil.example/app",
    "//evil.example",
    "/\\evil.example",
    "\\\\evil.example",
    "/\t/evil.example",
    "/\n/evil.example",
    " /app",
    "javascript:alert(1)",
    "app/history",
    "",
    null,
    undefined,
  ]) {
    expect(safeReturnTo(value), String(value)).toBe(DEFAULT_RETURN_TO);
  }
});

test("the sign-in page is never a destination, so it cannot loop", () => {
  expect(safeReturnTo("/sign-in")).toBe(DEFAULT_RETURN_TO);
  expect(safeReturnTo("/sign-in?next=/app")).toBe(DEFAULT_RETURN_TO);
  expect(safeReturnTo("/sign-in/")).toBe(DEFAULT_RETURN_TO);
});

test("overlong values fall back instead of being truncated into another path", () => {
  // The API's login route accepts at most 300 characters of return_to.
  expect(safeReturnTo(`/app/${"a".repeat(300)}`)).toBe(DEFAULT_RETURN_TO);
  expect(safeReturnTo(`/app/${"a".repeat(295)}`)).toBe(`/app/${"a".repeat(295)}`);
});

test("signInHref carries the current page as an encoded next parameter", () => {
  expect(signInHref("/app/history")).toBe("/sign-in?next=%2Fapp%2Fhistory");
  expect(signInHref("/app?q=1")).toBe("/sign-in?next=%2Fapp%3Fq%3D1");
  // The dashboard is the default anyway, and nothing unsafe is ever put in the link.
  expect(signInHref("/app")).toBe("/sign-in");
  expect(signInHref("//evil.example")).toBe("/sign-in");
  expect(signInHref("/sign-in")).toBe("/sign-in");
});

test("signInHref can carry a failed sign-in's reason back to the page", () => {
  expect(signInHref("/app/connections", "access_denied")).toBe("/sign-in?next=%2Fapp%2Fconnections&auth_error=access_denied");
  expect(signInHref("/app", "not_allowed")).toBe("/sign-in?auth_error=not_allowed");
  expect(signInHref("/app", "a&b")).toBe("/sign-in?auth_error=a%26b");
});

test("the destination of the latest sign-in attempt is remembered for when it fails", () => {
  expect(rememberedReturnTo()).toBe(DEFAULT_RETURN_TO);
  rememberReturnTo("/app/connections");
  expect(rememberedReturnTo()).toBe("/app/connections");
  // A newer attempt replaces it, so a stale destination is never used.
  rememberReturnTo("/app/history");
  expect(rememberedReturnTo()).toBe("/app/history");
});

test("a tampered remembered destination, or unavailable storage, falls back to the dashboard", () => {
  sessionStorage.setItem(PENDING_RETURN_KEY, "//evil.example");
  expect(rememberedReturnTo()).toBe(DEFAULT_RETURN_TO);
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
    throw new Error("blocked");
  });
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("blocked");
  });
  expect(() => rememberReturnTo("/app/connections")).not.toThrow();
  expect(rememberedReturnTo()).toBe(DEFAULT_RETURN_TO);
});
