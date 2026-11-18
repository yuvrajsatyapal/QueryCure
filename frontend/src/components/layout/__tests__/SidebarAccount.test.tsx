import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithQuery } from "@/test/render";
import { ApiError } from "@/lib/api/client";
import { getMe, logout } from "@/lib/api/session";
import { goHome } from "@/lib/auth/navigate";
import { SidebarAccount } from "../SidebarAccount";

vi.mock("@/lib/api/session", () => ({
  getMe: vi.fn(),
  createSession: vi.fn(),
  getAuthOptions: vi.fn(),
  logout: vi.fn(),
}));
vi.mock("@/lib/auth/navigate", () => ({ goHome: vi.fn() }));
vi.mock("next/navigation", () => ({ usePathname: () => "/app/history" }));

const features = { liveInspection: true, sandbox: true, googleLogin: true, githubLogin: true };
const local = { user: { id: "u0", kind: "local", displayName: null }, profile: "local", features };
const oauth = (displayName: string | null) => ({ user: { id: "u1", kind: "oauth", displayName }, profile: "local", features });

beforeEach(() => {
  window.history.replaceState(null, "", "/app/history");
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

test("a local session shows one Sign in link to the sign-in page, carrying the current page", async () => {
  vi.mocked(getMe).mockResolvedValue(local as never);
  const onNavigate = vi.fn();
  renderWithQuery(<SidebarAccount onNavigate={onNavigate} />);
  expect(await screen.findByText("Local session")).toBeDefined();
  const signIn = screen.getByRole("link", { name: "Sign in" });
  expect(signIn.getAttribute("href")).toBe("/sign-in?next=%2Fapp%2Fhistory");
  expect(screen.getAllByRole("link")).toHaveLength(1);
  expect(screen.queryByRole("button", { name: /sign in/i })).toBeNull();
  expect(screen.queryByRole("link", { name: /Google|GitHub/ })).toBeNull();
  // A navigation link, not a popup: nothing opens in place, and the mobile drawer is told to close.
  fireEvent.click(signIn);
  expect(onNavigate).toHaveBeenCalledOnce();
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(screen.queryByRole("menu")).toBeNull();
});

test("the collapsed rail shows the same link as a named icon", async () => {
  vi.mocked(getMe).mockResolvedValue(local as never);
  renderWithQuery(<SidebarAccount collapsed />);
  const signIn = await screen.findByRole("link", { name: "Sign in" });
  expect(signIn.getAttribute("href")).toBe("/sign-in?next=%2Fapp%2Fhistory");
});

test("no Sign in link when the deployment offers no provider", async () => {
  vi.mocked(getMe).mockResolvedValue({
    ...local,
    features: { ...features, googleLogin: false, githubLogin: false },
  } as never);
  renderWithQuery(<SidebarAccount />);
  expect(await screen.findByText("Local session")).toBeDefined();
  expect(screen.queryByRole("link", { name: "Sign in" })).toBeNull();
});

test("while the session loads or is being replaced, neither Sign in nor an account is shown", async () => {
  vi.mocked(getMe).mockReturnValue(new Promise(() => {}));
  renderWithQuery(<SidebarAccount />);
  expect(screen.getByRole("status", { name: "Loading account" })).toBeDefined();
  expect(screen.queryByRole("link", { name: "Sign in" })).toBeNull();
  cleanup();

  // A 401 means SessionGate is creating a session: still not "signed out".
  vi.mocked(getMe).mockRejectedValue(new ApiError("UNAUTHENTICATED", "no", 401, [], null));
  renderWithQuery(<SidebarAccount />);
  await waitFor(() => expect(getMe).toHaveBeenCalled());
  expect(await screen.findByRole("status", { name: "Loading account" })).toBeDefined();
  expect(screen.queryByRole("link", { name: "Sign in" })).toBeNull();
  expect(screen.queryByText("Local session")).toBeNull();
});

test("a signed-in account shows its initials and name with Settings and Sign out beside them", async () => {
  vi.mocked(getMe).mockResolvedValue(oauth("Ada Lovelace") as never);
  const onNavigate = vi.fn();
  renderWithQuery(<SidebarAccount onNavigate={onNavigate} />);
  expect(await screen.findByText("Ada Lovelace")).toBeDefined();
  expect(screen.getByText("AL")).toBeDefined();
  expect(screen.getByText("Signed in")).toBeDefined();
  const name = screen.getByText("Ada Lovelace");
  const settings = screen.getByRole("link", { name: "Settings" });
  const signOut = screen.getByRole("button", { name: "Sign out" });
  expect(settings.getAttribute("href")).toBe("/app/settings");
  expect(settings.hasAttribute("aria-current")).toBe(false);
  // Order: name, Settings, Sign out. No disclosure, chevron, menu or dialog.
  expect(name.compareDocumentPosition(settings) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(settings.compareDocumentPosition(signOut) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(screen.queryByRole("button", { name: /Account actions/ })).toBeNull();
  expect(document.querySelector("[aria-expanded]")).toBeNull();
  expect(screen.queryByRole("link", { name: "Sign in" })).toBeNull();
  fireEvent.click(settings);
  expect(onNavigate).toHaveBeenCalledOnce();
});

test("Settings is marked current on the settings page", async () => {
  vi.resetModules();
  vi.doMock("next/navigation", () => ({ usePathname: () => "/app/settings" }));
  const { SidebarAccount: Account } = await import("../SidebarAccount");
  vi.mocked(getMe).mockResolvedValue(oauth("Ada Lovelace") as never);
  renderWithQuery(<Account />);
  expect((await screen.findByRole("link", { name: "Settings" })).getAttribute("aria-current")).toBe("page");
  vi.doUnmock("next/navigation");
});

test("the tab order is Settings then Sign out", async () => {
  vi.mocked(getMe).mockResolvedValue(oauth("Ada Lovelace") as never);
  const user = userEvent.setup();
  renderWithQuery(<SidebarAccount />);
  await screen.findByText("Ada Lovelace");
  await user.tab();
  expect(document.activeElement).toBe(screen.getByRole("link", { name: "Settings" }));
  await user.tab();
  expect(document.activeElement).toBe(screen.getByRole("button", { name: "Sign out" }));
});

test("a missing name falls back to a neutral label and icon; a long one keeps its full text available", async () => {
  vi.mocked(getMe).mockResolvedValue(oauth(null) as never);
  renderWithQuery(<SidebarAccount />);
  expect(await screen.findByText("Your account")).toBeDefined();
  expect(document.querySelector('[data-avatar="icon"]')).not.toBeNull();
  cleanup();

  const long = "Augusta Ada King, Countess of Lovelace and Analytical Engine Enthusiast";
  vi.mocked(getMe).mockResolvedValue(oauth(long) as never);
  renderWithQuery(<SidebarAccount />);
  const text = await screen.findByText(long);
  expect(text.closest("[title]")?.getAttribute("title")).toBe(long);
  expect(text.className).toContain("truncate");
  // First and last word, as in "Ada Lovelace" → AL.
  expect(screen.getByText("AE")).toBeDefined();
});

test("Sign out uses the existing logout, shows progress, and reports a failure", async () => {
  vi.mocked(getMe).mockResolvedValue(oauth("Ada Lovelace") as never);
  let fail: (e: Error) => void = () => {};
  vi.mocked(logout).mockReturnValueOnce(new Promise((_, reject) => (fail = reject)));
  renderWithQuery(<SidebarAccount />);
  fireEvent.click(await screen.findByRole("button", { name: "Sign out" }));
  const pending = await screen.findByRole("button", { name: "Signing out…" });
  expect(pending.hasAttribute("disabled")).toBe(true);
  expect(logout).toHaveBeenCalledOnce();
  fail(new Error("offline"));
  expect(await screen.findByRole("alert")).toHaveProperty("textContent", "Sign-out failed. Check your connection and try again.");
  expect(screen.getByRole("button", { name: "Sign out" }).hasAttribute("disabled")).toBe(false);
});

test("a successful sign-out shows the signing-out screen and loads the home page", async () => {
  vi.mocked(getMe).mockResolvedValue(oauth("Ada Lovelace") as never);
  vi.mocked(logout).mockResolvedValue(undefined);
  renderWithQuery(<SidebarAccount />);
  fireEvent.click(await screen.findByRole("button", { name: "Sign out" }));
  expect(await screen.findByRole("heading", { name: "Signing you out" })).toBeDefined();
  await waitFor(() => expect(goHome).toHaveBeenCalledOnce());
  // It stays up through the page load: no flash of the local session or the old account.
  expect(screen.getByRole("heading", { name: "Signing you out" })).toBeDefined();
  expect(screen.queryByText("Local session")).toBeNull();
  expect(getMe).toHaveBeenCalledTimes(1);
});

test("a failed sign-out takes the screen away and reports the failure", async () => {
  vi.mocked(getMe).mockResolvedValue(oauth("Ada Lovelace") as never);
  vi.mocked(logout).mockRejectedValue(new Error("offline"));
  renderWithQuery(<SidebarAccount />);
  fireEvent.click(await screen.findByRole("button", { name: "Sign out" }));
  expect(await screen.findByRole("alert")).toHaveProperty("textContent", "Sign-out failed. Check your connection and try again.");
  expect(screen.queryByRole("heading", { name: "Signing you out" })).toBeNull();
  expect(goHome).not.toHaveBeenCalled();
});

test("the collapsed rail shows the avatar, a Settings link and a Sign out button", async () => {
  vi.mocked(getMe).mockResolvedValue(oauth("Ada Lovelace") as never);
  renderWithQuery(<SidebarAccount collapsed />);
  const avatar = await screen.findByRole("img", { name: "Account: Ada Lovelace" });
  const settings = screen.getByRole("link", { name: "Settings" });
  const signOut = screen.getByRole("button", { name: "Sign out" });
  expect(settings.getAttribute("href")).toBe("/app/settings");
  expect(avatar.compareDocumentPosition(settings) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(settings.compareDocumentPosition(signOut) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
});
