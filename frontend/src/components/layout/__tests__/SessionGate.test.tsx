import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { cleanup, screen, waitFor } from "@testing-library/react";
import { renderWithQuery } from "@/test/render";
import { ApiError } from "@/lib/api/client";
import { createSession, getAuthOptions, getMe } from "@/lib/api/session";
import { rememberReturnTo } from "@/lib/auth/returnTo";
import { SessionGate } from "../SessionGate";

vi.mock("@/lib/api/session", () => ({
  getMe: vi.fn(),
  createSession: vi.fn(),
  getAuthOptions: vi.fn(),
  logout: vi.fn(),
}));
const replace = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));

const denied = (status: number, code: string) => new ApiError(code, "denied", status, [], null);
const me = { user: { id: "u1", kind: "oauth", displayName: "Ada" }, profile: "demo", features: {} };

beforeEach(() => {
  vi.mocked(getAuthOptions).mockResolvedValue({ restrictedAccess: true, githubLogin: true, googleLogin: false });
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  sessionStorage.clear();
  window.history.replaceState(null, "", "/");
});

test("an open deployment starts an anonymous session and renders the app", async () => {
  vi.mocked(getMe)
    .mockRejectedValueOnce(denied(401, "UNAUTHENTICATED"))
    .mockResolvedValue(me as never);
  vi.mocked(createSession).mockResolvedValue({});
  renderWithQuery(<SessionGate>app content</SessionGate>);
  expect(await screen.findByText("app content")).toBeDefined();
  expect(createSession).toHaveBeenCalledOnce();
});

test("a restricted trial without a session sends the user to the sign-in page, back here afterwards", async () => {
  window.history.replaceState(null, "", "/app/connections?tab=new");
  vi.mocked(getMe).mockRejectedValue(denied(401, "UNAUTHENTICATED"));
  vi.mocked(createSession).mockRejectedValue(denied(403, "ACCESS_DENIED"));
  renderWithQuery(<SessionGate>app content</SessionGate>);
  await waitFor(() => expect(replace).toHaveBeenCalledWith("/sign-in?next=%2Fapp%2Fconnections%3Ftab%3Dnew"));
  expect(screen.queryByText("app content")).toBeNull();
  // There is one sign-in experience: the gate draws no sign-in screen of its own.
  expect(screen.queryByRole("link", { name: /Sign in with|Continue with/ })).toBeNull();
});

test("a signed-in account that is not approved goes to the sign-in page without a new session", async () => {
  window.history.replaceState(null, "", "/app/history");
  vi.mocked(getMe).mockRejectedValue(denied(403, "ACCESS_DENIED"));
  renderWithQuery(<SessionGate>app content</SessionGate>);
  await waitFor(() => expect(replace).toHaveBeenCalledWith("/sign-in?next=%2Fapp%2Fhistory"));
  expect(createSession).not.toHaveBeenCalled();
  expect(screen.queryByText("app content")).toBeNull();
});

test("a refused sign-in in a restricted trial returns to sign-in with its reason and original destination", async () => {
  rememberReturnTo("/app/connections");
  window.history.replaceState(null, "", "/app?auth_error=not_allowed");
  vi.mocked(getMe).mockRejectedValue(denied(401, "UNAUTHENTICATED"));
  vi.mocked(createSession).mockRejectedValue(denied(403, "ACCESS_DENIED"));
  renderWithQuery(<SessionGate>app content</SessionGate>);
  await waitFor(() => expect(replace).toHaveBeenCalledWith("/sign-in?next=%2Fapp%2Fconnections&auth_error=not_allowed"));
});

test("in an open deployment a failed sign-in returns to the sign-in page with its reason", async () => {
  window.history.replaceState(null, "", "/app?auth_error=access_denied");
  vi.mocked(getMe).mockResolvedValue({
    ...me,
    user: { id: "u0", kind: "anonymous", displayName: null },
  } as never);
  renderWithQuery(<SessionGate>app content</SessionGate>);
  await waitFor(() => expect(replace).toHaveBeenCalledWith("/sign-in?auth_error=access_denied"));
  // The error is shown once, where the user can try again, not as a banner over the app first.
  expect(screen.queryByRole("alert")).toBeNull();
});

test("a failed sign-in keeps the page it started from, so a retry still returns there", async () => {
  rememberReturnTo("/app/connections");
  window.history.replaceState(null, "", "/app?auth_error=access_denied");
  vi.mocked(getMe).mockResolvedValue({
    ...me,
    user: { id: "u0", kind: "local", displayName: null },
  } as never);
  renderWithQuery(<SessionGate>app content</SessionGate>);
  await waitFor(() => expect(replace).toHaveBeenCalledWith("/sign-in?next=%2Fapp%2Fconnections&auth_error=access_denied"));
});

test("a signed-in account keeps a sign-in error on the page it came back to", async () => {
  window.history.replaceState(null, "", "/app?auth_error=access_denied");
  vi.mocked(getMe).mockResolvedValue(me as never);
  renderWithQuery(<SessionGate>app content</SessionGate>);
  expect(await screen.findByText("app content")).toBeDefined();
  expect(screen.getByRole("alert").textContent).toBe("Sign-in was cancelled.");
  expect(replace).not.toHaveBeenCalled();
});
