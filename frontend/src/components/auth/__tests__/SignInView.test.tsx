import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { renderWithQuery } from "@/test/render";
import { API_BASE_URL, ApiError } from "@/lib/api/client";
import { getAuthOptions, getMe, logout } from "@/lib/api/session";
import { rememberedReturnTo } from "@/lib/auth/returnTo";
import { SignInView } from "../SignInView";

vi.mock("@/lib/api/session", () => ({
  getMe: vi.fn(),
  createSession: vi.fn(),
  getAuthOptions: vi.fn(),
  logout: vi.fn(),
}));
const replace = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));

const both = { restrictedAccess: false, googleLogin: true, githubLogin: true };
const features = { liveInspection: true, sandbox: true, googleLogin: true, githubLogin: true };
const unauthenticated = new ApiError("UNAUTHENTICATED", "no", 401, [], null);
const login = (provider: string, returnTo: string) => `${API_BASE_URL}/api/v1/auth/${provider}/login?return_to=${encodeURIComponent(returnTo)}`;

beforeEach(() => {
  vi.mocked(getAuthOptions).mockResolvedValue(both);
  vi.mocked(getMe).mockRejectedValue(unauthenticated);
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  sessionStorage.clear();
});

test("the page explains itself and offers each configured provider through the existing login routes", async () => {
  renderWithQuery(<SignInView next="/app/history" authError={null} />);
  expect(screen.getByRole("heading", { level: 1, name: "Welcome to QueryCure" })).toBeDefined();
  expect(screen.getByText("Sign in to manage your investigations and database connections.")).toBeDefined();
  const google = await screen.findByRole("link", { name: "Continue with Google" });
  const github = screen.getByRole("link", { name: "Continue with GitHub" });
  expect(google.getAttribute("href")).toBe(login("google", "/app/history"));
  expect(github.getAttribute("href")).toBe(login("github", "/app/history"));
  expect(screen.getByText(/never sees your password/)).toBeDefined();
  expect(screen.getByRole("link", { name: "Back to QueryCure" }).getAttribute("href")).toBe("/app/history");
  expect(screen.queryByRole("dialog")).toBeNull();
});

test("only configured providers are offered, and none configured is said plainly", async () => {
  vi.mocked(getAuthOptions).mockResolvedValue({ ...both, googleLogin: false });
  renderWithQuery(<SignInView next={null} authError={null} />);
  expect(await screen.findByRole("link", { name: "Continue with GitHub" })).toBeDefined();
  expect(screen.queryByRole("link", { name: "Continue with Google" })).toBeNull();
  cleanup();

  vi.mocked(getAuthOptions).mockResolvedValue({
    ...both,
    googleLogin: false,
    githubLogin: false,
  });
  renderWithQuery(<SignInView next={null} authError={null} />);
  expect(await screen.findByText("Sign-in is not configured for this deployment.")).toBeDefined();
  expect(screen.queryByRole("link", { name: /Continue with/ })).toBeNull();
});

test("an unsafe or missing destination returns to the dashboard", async () => {
  renderWithQuery(<SignInView next="https://evil.example/" authError={null} />);
  expect((await screen.findByRole("link", { name: "Continue with Google" })).getAttribute("href")).toBe(login("google", "/app"));
  expect(screen.getByRole("link", { name: "Back to QueryCure" }).getAttribute("href")).toBe("/app");
  cleanup();

  renderWithQuery(<SignInView next={null} authError={null} />);
  expect((await screen.findByRole("link", { name: "Continue with GitHub" })).getAttribute("href")).toBe(login("github", "/app"));
});

test("one click starts one sign-in: both options are disabled while redirecting", async () => {
  renderWithQuery(<SignInView next="/app" authError={null} />);
  const google = await screen.findByRole("link", { name: "Continue with Google" });
  // Navigation is jsdom-unimplemented; stop it after our handler has run.
  window.addEventListener("click", (e) => e.preventDefault(), { once: true });
  fireEvent.click(google);
  const redirecting = screen.getByRole("link", { name: "Redirecting to Google…" });
  expect(redirecting.getAttribute("aria-disabled")).toBe("true");
  const github = screen.getByRole("link", { name: "Continue with GitHub" });
  expect(github.getAttribute("aria-disabled")).toBe("true");
  // fireEvent.click returns false when our handler prevented the navigation.
  expect(fireEvent.click(github)).toBe(false);
  expect(fireEvent.click(redirecting)).toBe(false);

  // Coming back with Back restores the page from the bfcache: the options work again.
  const restored = new Event("pageshow") as PageTransitionEvent;
  Object.defineProperty(restored, "persisted", { value: true });
  fireEvent(window, restored);
  expect((await screen.findByRole("link", { name: "Continue with GitHub" })).hasAttribute("aria-disabled")).toBe(false);
});

test("a cancelled or failed sign-in is explained", async () => {
  renderWithQuery(<SignInView next={null} authError="access_denied" />);
  expect(screen.getByRole("alert").textContent).toBe("Sign-in was cancelled.");
  cleanup();
  renderWithQuery(<SignInView next={null} authError="provider_unreachable" />);
  expect(screen.getByRole("alert").textContent).toBe("The sign-in provider could not be reached. Please try again later.");
  cleanup();
  renderWithQuery(<SignInView next={null} authError="something_new" />);
  expect(screen.getByRole("alert").textContent).toBe("Sign-in failed. Please try again.");
});

test("while the options and session load, a placeholder stands in for the buttons", () => {
  vi.mocked(getAuthOptions).mockReturnValue(new Promise(() => {}));
  renderWithQuery(<SignInView next={null} authError={null} />);
  expect(screen.getByRole("status", { name: "Loading sign-in options" })).toBeDefined();
  expect(screen.queryByRole("link", { name: /Continue with/ })).toBeNull();
});

test("options that cannot be loaded show the error and can be retried", async () => {
  vi.mocked(getAuthOptions).mockRejectedValueOnce(new ApiError("HTTP_503", "The API is unavailable.", 503, [], null));
  renderWithQuery(<SignInView next={null} authError={null} />);
  expect(await screen.findByText("The API is unavailable.")).toBeDefined();
  fireEvent.click(screen.getByRole("button", { name: "Try again" }));
  expect(await screen.findByRole("link", { name: "Continue with Google" })).toBeDefined();
});

test("an account that is already signed in is sent on to its destination", async () => {
  vi.mocked(getMe).mockResolvedValue({ user: { id: "u1", kind: "oauth", displayName: "Ada" }, profile: "local", features } as never);
  renderWithQuery(<SignInView next="/app/history" authError={null} />);
  await waitFor(() => expect(replace).toHaveBeenCalledWith("/app/history"));
  expect(screen.getByRole("status", { name: "Already signed in. Redirecting…" })).toBeDefined();
  expect(screen.queryByRole("link", { name: /Continue with/ })).toBeNull();
});

test("a local or anonymous session still gets the sign-in options", async () => {
  vi.mocked(getMe).mockResolvedValue({ user: { id: "u0", kind: "local", displayName: null }, profile: "local", features } as never);
  renderWithQuery(<SignInView next={null} authError={null} />);
  expect(await screen.findByRole("link", { name: "Continue with Google" })).toBeDefined();
  expect(replace).not.toHaveBeenCalled();
});

test("starting a sign-in remembers where to return, for when the provider sends back a failure", async () => {
  renderWithQuery(<SignInView next="/app/connections" authError={null} />);
  const github = await screen.findByRole("link", { name: "Continue with GitHub" });
  window.addEventListener("click", (e) => e.preventDefault(), { once: true });
  fireEvent.click(github);
  expect(rememberedReturnTo()).toBe("/app/connections");
});

test("a restricted trial says so, and Back leaves for the public page instead of the gated app", async () => {
  vi.mocked(getAuthOptions).mockResolvedValue({ ...both, restrictedAccess: true });
  renderWithQuery(<SignInView next="/app/history" authError={null} />);
  expect(await screen.findByText("This trial is limited to approved accounts.")).toBeDefined();
  expect(screen.getByRole("link", { name: "Back to QueryCure" }).getAttribute("href")).toBe("/");
  expect(screen.getByRole("link", { name: "Continue with Google" }).getAttribute("href")).toBe(login("google", "/app/history"));
});

test("a signed-in account that is not approved is told so once, and can sign out or switch account", async () => {
  vi.mocked(getAuthOptions).mockResolvedValue({ ...both, restrictedAccess: true });
  vi.mocked(getMe).mockRejectedValue(new ApiError("ACCESS_DENIED", "denied", 403, [], null));
  vi.mocked(logout).mockResolvedValue(undefined as never);
  renderWithQuery(<SignInView next={null} authError="not_allowed" />);
  expect(await screen.findByRole("link", { name: "Continue with GitHub" })).toBeDefined();
  expect(screen.getAllByRole("alert")).toHaveLength(1);
  expect(screen.getByRole("alert").textContent).toMatch(/not approved for this trial/);
  expect(replace).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
  await waitFor(() => expect(logout).toHaveBeenCalledOnce());
});
