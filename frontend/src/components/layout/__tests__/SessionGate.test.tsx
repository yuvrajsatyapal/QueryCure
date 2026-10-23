import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { cleanup, screen } from "@testing-library/react";
import { renderWithQuery } from "@/test/render";
import { ApiError } from "@/lib/api/client";
import { createSession, getAuthOptions, getMe } from "@/lib/api/session";
import { SessionGate } from "../SessionGate";

vi.mock("@/lib/api/session", () => ({
  getMe: vi.fn(),
  createSession: vi.fn(),
  getAuthOptions: vi.fn(),
  logout: vi.fn(),
}));

const denied = (status: number, code: string) => new ApiError(code, "denied", status, [], null);
const me = { user: { id: "u1", kind: "oauth", displayName: "Ada" }, profile: "demo", features: {} };

beforeEach(() => {
  vi.mocked(getAuthOptions).mockResolvedValue({ restrictedAccess: true, githubLogin: true, googleLogin: false });
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  window.history.replaceState(null, "", "/");
});

test("an open deployment starts an anonymous session and renders the app", async () => {
  vi.mocked(getMe).mockRejectedValueOnce(denied(401, "UNAUTHENTICATED")).mockResolvedValue(me as never);
  vi.mocked(createSession).mockResolvedValue({});
  renderWithQuery(<SessionGate>app content</SessionGate>);
  expect(await screen.findByText("app content")).toBeDefined();
  expect(createSession).toHaveBeenCalledOnce();
});

test("a restricted trial without a session shows only the configured sign-in options", async () => {
  vi.mocked(getMe).mockRejectedValue(denied(401, "UNAUTHENTICATED"));
  vi.mocked(createSession).mockRejectedValue(denied(403, "ACCESS_DENIED"));
  renderWithQuery(<SessionGate>app content</SessionGate>);
  expect(await screen.findByRole("heading", { name: "Sign in to QueryCure" })).toBeDefined();
  expect(await screen.findByRole("link", { name: "Sign in with GitHub" })).toBeDefined();
  expect(screen.queryByRole("link", { name: "Sign in with Google" })).toBeNull();
  expect(screen.queryByText("app content")).toBeNull();
});

test("a signed-in account that is not approved is told so and can sign out", async () => {
  vi.mocked(getMe).mockRejectedValue(denied(403, "ACCESS_DENIED"));
  renderWithQuery(<SessionGate>app content</SessionGate>);
  expect(await screen.findByText(/not approved for this trial/)).toBeDefined();
  expect(screen.getByRole("button", { name: "Sign out" })).toBeDefined();
  expect(createSession).not.toHaveBeenCalled();
  expect(screen.queryByText("app content")).toBeNull();
});

test("a refused sign-in explains why on the sign-in screen", async () => {
  window.history.replaceState(null, "", "/app?auth_error=not_allowed");
  vi.mocked(getMe).mockRejectedValue(denied(401, "UNAUTHENTICATED"));
  vi.mocked(createSession).mockRejectedValue(denied(403, "ACCESS_DENIED"));
  renderWithQuery(<SessionGate>app content</SessionGate>);
  expect(await screen.findByRole("alert")).toBeDefined();
  expect(screen.getByRole("alert").textContent).toMatch(/not approved for this trial/);
});
