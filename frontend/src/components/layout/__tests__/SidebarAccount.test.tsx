import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithQuery } from "@/test/render";
import { ApiError } from "@/lib/api/client";
import { getMe, logout } from "@/lib/api/session";
import { SidebarAccount } from "../SidebarAccount";

vi.mock("@/lib/api/session", () => ({
  getMe: vi.fn(),
  createSession: vi.fn(),
  getAuthOptions: vi.fn(),
  logout: vi.fn(),
}));
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

test("a signed-in account shows its initials, name and a collapsed disclosure", async () => {
  vi.mocked(getMe).mockResolvedValue(oauth("Ada Lovelace") as never);
  renderWithQuery(<SidebarAccount />);
  const profile = await screen.findByRole("button", { name: /Ada Lovelace/ });
  expect(profile.getAttribute("aria-expanded")).toBe("false");
  expect(profile.hasAttribute("aria-haspopup")).toBe(false);
  expect(within(profile).getByText("AL")).toBeDefined();
  expect(within(profile).getByText("Signed in")).toBeDefined();
  expect(screen.queryByRole("button", { name: "Sign out" })).toBeNull();
  expect(screen.queryByRole("link", { name: "Sign in" })).toBeNull();
});

test("the profile expands account actions inline, below it, and collapses again", async () => {
  vi.mocked(getMe).mockResolvedValue(oauth("Ada Lovelace") as never);
  const { container } = renderWithQuery(<SidebarAccount />);
  const profile = await screen.findByRole("button", { name: /Ada Lovelace/ });
  fireEvent.click(profile);
  expect(profile.getAttribute("aria-expanded")).toBe("true");
  const signOut = screen.getByRole("button", { name: "Sign out" });
  // In the sidebar's own flow: inside this component, after the profile, labelled as its region.
  expect(container.contains(signOut)).toBe(true);
  expect(profile.compareDocumentPosition(signOut) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  const region = document.getElementById(profile.getAttribute("aria-controls") ?? "");
  expect(region?.contains(signOut)).toBe(true);
  expect(screen.queryByRole("menu")).toBeNull();
  expect(screen.queryByRole("dialog")).toBeNull();
  // No account route exists, so no dead Account entry is offered.
  expect(within(region as HTMLElement).getAllByRole("button")).toHaveLength(1);

  fireEvent.click(profile);
  expect(profile.getAttribute("aria-expanded")).toBe("false");
  expect(screen.queryByRole("button", { name: "Sign out" })).toBeNull();
});

test("the disclosure works from the keyboard", async () => {
  vi.mocked(getMe).mockResolvedValue(oauth("Ada Lovelace") as never);
  const user = userEvent.setup();
  renderWithQuery(<SidebarAccount />);
  const profile = await screen.findByRole("button", { name: /Ada Lovelace/ });
  await user.tab();
  expect(document.activeElement).toBe(profile);
  await user.keyboard("{Enter}");
  expect(profile.getAttribute("aria-expanded")).toBe("true");
  await user.tab();
  expect(document.activeElement).toBe(screen.getByRole("button", { name: "Sign out" }));
  await user.keyboard("{Shift>}{Tab}{/Shift}");
  await user.keyboard(" ");
  expect(profile.getAttribute("aria-expanded")).toBe("false");
});

test("a missing name falls back to a neutral label and icon; a long one keeps its full text available", async () => {
  vi.mocked(getMe).mockResolvedValue(oauth(null) as never);
  renderWithQuery(<SidebarAccount />);
  const profile = await screen.findByRole("button", { name: /Your account/ });
  expect(profile.querySelector('[data-avatar="icon"]')).not.toBeNull();
  cleanup();

  const long = "Augusta Ada King, Countess of Lovelace and Analytical Engine Enthusiast";
  vi.mocked(getMe).mockResolvedValue(oauth(long) as never);
  renderWithQuery(<SidebarAccount />);
  const named = await screen.findByRole("button", { name: new RegExp(long) });
  expect(named.getAttribute("title")).toBe(long);
  expect(within(named).getByText(long).className).toContain("truncate");
  // First and last word, as in "Ada Lovelace" → AL.
  expect(within(named).getByText("AE")).toBeDefined();
});

test("Sign out uses the existing logout, shows progress, and reports a failure", async () => {
  vi.mocked(getMe).mockResolvedValue(oauth("Ada Lovelace") as never);
  let fail: (e: Error) => void = () => {};
  vi.mocked(logout).mockReturnValueOnce(new Promise((_, reject) => (fail = reject)));
  renderWithQuery(<SidebarAccount />);
  fireEvent.click(await screen.findByRole("button", { name: /Ada Lovelace/ }));
  fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
  const pending = await screen.findByRole("button", { name: "Signing out…" });
  expect(pending.hasAttribute("disabled")).toBe(true);
  expect(logout).toHaveBeenCalledOnce();
  fail(new Error("offline"));
  expect(await screen.findByRole("alert")).toHaveProperty("textContent", "Sign-out failed. Check your connection and try again.");
  expect(screen.getByRole("button", { name: "Sign out" }).hasAttribute("disabled")).toBe(false);
});

test("a successful sign-out drops the cached account so the session is re-read", async () => {
  vi.mocked(getMe)
    .mockResolvedValueOnce(oauth("Ada Lovelace") as never)
    .mockResolvedValue(local as never);
  vi.mocked(logout).mockResolvedValue(undefined);
  renderWithQuery(<SidebarAccount />);
  fireEvent.click(await screen.findByRole("button", { name: /Ada Lovelace/ }));
  fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
  expect(await screen.findByText("Local session")).toBeDefined();
  expect(screen.queryByText("Ada Lovelace")).toBeNull();
  expect(getMe).toHaveBeenCalledTimes(2);
});

test("the collapsed rail expands to an icon Sign out below the avatar", async () => {
  vi.mocked(getMe).mockResolvedValue(oauth("Ada Lovelace") as never);
  renderWithQuery(<SidebarAccount collapsed />);
  const profile = await screen.findByRole("button", { name: "Account: Ada Lovelace" });
  expect(profile.getAttribute("aria-expanded")).toBe("false");
  fireEvent.click(profile);
  const signOut = screen.getByRole("button", { name: "Sign out" });
  expect(profile.compareDocumentPosition(signOut) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(screen.queryByRole("menu")).toBeNull();
});
