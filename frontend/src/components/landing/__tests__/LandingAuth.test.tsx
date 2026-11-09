import { afterEach, expect, test, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { renderWithQuery } from "@/test/render";
import { ApiError } from "@/lib/api/client";
import { createSession, getAuthOptions, getMe, logout } from "@/lib/api/session";
import { FinalCtas, FooterAuthLink, HeroCta, NavAuth } from "../LandingAuth";

vi.mock("@/lib/api/session", () => ({
  getMe: vi.fn(),
  createSession: vi.fn(),
  getAuthOptions: vi.fn(),
  logout: vi.fn(),
}));

const features = { liveInspection: true, sandbox: true, googleLogin: true, githubLogin: true };
const oauth = { user: { id: "u1", kind: "oauth", displayName: "Ada Lovelace" }, profile: "demo", features };
const local = { user: { id: "u0", kind: "local", displayName: null }, profile: "local", features };
const open = { restrictedAccess: false, githubLogin: true, googleLogin: true };
const restricted = { restrictedAccess: true, githubLogin: true, googleLogin: false };
const noProviders = { restrictedAccess: false, githubLogin: false, googleLogin: false };
const error = (status: number, code: string) => new ApiError(code, "x", status, [], null);
const signedOut = () => vi.mocked(getMe).mockRejectedValue(error(401, "UNAUTHENTICATED"));
const hrefOf = (name: string | RegExp) => screen.getByRole("link", { name }).getAttribute("href");
const links = () => screen.queryAllByRole("link").map((l) => l.textContent?.trim());

afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

const everySlot = (
  <>
    <NavAuth />
    <HeroCta />
    <FinalCtas />
    <FooterAuthLink />
  </>
);

test("while the session is unknown no slot claims anything: no link, only a reserved space", () => {
  vi.mocked(getMe).mockReturnValue(new Promise(() => {}));
  vi.mocked(getAuthOptions).mockReturnValue(new Promise(() => {}));
  const { container } = renderWithQuery(everySlot);
  expect(links()).toEqual([]);
  expect(screen.queryByRole("button")).toBeNull();
  expect(container.querySelectorAll("[data-auth-slot='pending']").length).toBeGreaterThan(0);
  expect(createSession).not.toHaveBeenCalled();
});

test("signed out in an open deployment: Sign in / Get started lead to the sign-in page, Open QueryCure stays secondary", async () => {
  signedOut();
  vi.mocked(getAuthOptions).mockResolvedValue(open);
  renderWithQuery(
    <>
      <NavAuth />
      <HeroCta />
      <FinalCtas />
      <FooterAuthLink />
    </>,
  );
  await waitFor(() => expect(screen.getAllByRole("link", { name: "Get started" })).toHaveLength(2));
  // Nav, hero, final CTA and footer: every sign-in entry is the bare page, so the API's own default (/app) applies.
  for (const link of screen.getAllByRole("link", { name: /^(Get started|Sign in)$/ })) expect(link.getAttribute("href")).toBe("/sign-in");
  expect(screen.getAllByRole("link", { name: "Sign in" })).toHaveLength(2);
  const openApp = screen.getAllByRole("link", { name: "Open QueryCure" });
  expect(openApp.length).toBeGreaterThan(0);
  for (const link of openApp) expect(link.getAttribute("href")).toBe("/app");
  expect(screen.queryByRole("link", { name: "Open dashboard" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Sign out" })).toBeNull();
  expect(createSession).not.toHaveBeenCalled();
});

test("a local session is not a signed-in account", async () => {
  vi.mocked(getMe).mockResolvedValue(local as never);
  vi.mocked(getAuthOptions).mockResolvedValue(open);
  renderWithQuery(<HeroCta />);
  expect(await screen.findByRole("link", { name: "Get started" })).toBeDefined();
  expect(screen.queryByRole("link", { name: "Open dashboard" })).toBeNull();
});

test("a signed-in account gets the dashboard, its name, and Sign out instead of Sign in / Get started", async () => {
  vi.mocked(getMe).mockResolvedValue(oauth as never);
  vi.mocked(getAuthOptions).mockResolvedValue(open);
  renderWithQuery(everySlot);
  await waitFor(() => expect(screen.getAllByRole("link", { name: "Open dashboard" }).length).toBe(3));
  // Header, hero and closing call to action, plus the footer's shorter "Dashboard".
  for (const link of screen.getAllByRole("link", { name: /^(Open dashboard|Dashboard)$/ })) expect(link.getAttribute("href")).toBe("/app");
  expect(screen.getByRole("link", { name: "Dashboard" })).toBeDefined();
  expect(screen.queryByRole("link", { name: /Sign in|Get started|Open QueryCure/ })).toBeNull();
  expect(screen.getByRole("button", { name: "Sign out" })).toBeDefined();
  const account = screen.getByLabelText("Signed in as Ada Lovelace");
  expect(account.textContent).toBe("AL");
  expect(createSession).not.toHaveBeenCalled();
});

test("a signed-in account with no name still shows a neutral label", async () => {
  vi.mocked(getMe).mockResolvedValue({ ...oauth, user: { ...oauth.user, displayName: null } } as never);
  vi.mocked(getAuthOptions).mockResolvedValue(open);
  renderWithQuery(<NavAuth />);
  expect(await screen.findByLabelText("Signed in")).toBeDefined();
});

test("restricted trial: Sign in is the only way in, straight to the sign-in page, with no Open QueryCure", async () => {
  signedOut();
  vi.mocked(getAuthOptions).mockResolvedValue(restricted);
  renderWithQuery(everySlot);
  await waitFor(() => expect(screen.getAllByRole("link", { name: "Sign in" }).length).toBeGreaterThan(0));
  expect(screen.queryByRole("link", { name: /Open QueryCure|Get started/ })).toBeNull();
  for (const link of screen.getAllByRole("link", { name: "Sign in" })) expect(link.getAttribute("href")).toBe("/sign-in");
});

test("an unapproved account (403) is offered Sign in, where the reason and Sign out are shown", async () => {
  vi.mocked(getMe).mockRejectedValue(error(403, "ACCESS_DENIED"));
  vi.mocked(getAuthOptions).mockResolvedValue(restricted);
  renderWithQuery(<NavAuth />);
  await screen.findByRole("link", { name: "Sign in" });
  expect(hrefOf("Sign in")).toBe("/sign-in");
  expect(screen.queryByRole("button", { name: "Sign out" })).toBeNull();
});

test("no provider configured: no Sign in or Get started; an open deployment still offers Open QueryCure", async () => {
  signedOut();
  vi.mocked(getAuthOptions).mockResolvedValue(noProviders);
  renderWithQuery(everySlot);
  await waitFor(() => expect(screen.getAllByRole("link", { name: "Open QueryCure" }).length).toBeGreaterThan(0));
  expect(screen.queryByRole("link", { name: /Sign in|Get started/ })).toBeNull();
});

test("no provider and a restricted trial: nothing to offer, and nothing misleading", async () => {
  signedOut();
  vi.mocked(getAuthOptions).mockResolvedValue({ restrictedAccess: true, githubLogin: false, googleLogin: false });
  renderWithQuery(everySlot);
  await waitFor(() => expect(getAuthOptions).toHaveBeenCalled());
  await waitFor(() => expect(document.querySelector("[data-auth-slot='pending']")).toBeNull());
  expect(links()).toEqual([]);
});

test("API unavailable: a neutral way to sign in, never Open QueryCure or an account", async () => {
  vi.mocked(getMe).mockRejectedValue(error(0, "NETWORK"));
  vi.mocked(getAuthOptions).mockRejectedValue(error(0, "NETWORK"));
  renderWithQuery(everySlot);
  await waitFor(() => expect(screen.getAllByRole("link", { name: /Get started|Sign in/ }).length).toBeGreaterThan(0));
  expect(screen.queryByRole("link", { name: /Open QueryCure|Open dashboard/ })).toBeNull();
  expect(screen.queryByRole("alert")).toBeNull();
  for (const link of screen.getAllByRole("link")) expect(link.getAttribute("href")).toBe("/sign-in");
});

test("Sign out uses the existing logout, then the page falls back to signed out without starting a session", async () => {
  vi.mocked(getMe).mockResolvedValueOnce(oauth as never).mockRejectedValue(error(401, "UNAUTHENTICATED"));
  vi.mocked(getAuthOptions).mockResolvedValue(open);
  vi.mocked(logout).mockResolvedValue(undefined);
  renderWithQuery(
    <>
      <NavAuth />
      <HeroCta />
    </>,
  );
  fireEvent.click(await screen.findByRole("button", { name: "Sign out" }));
  await waitFor(() => expect(logout).toHaveBeenCalledOnce());
  expect(await screen.findAllByRole("link", { name: /Sign in|Get started/ })).not.toHaveLength(0);
  expect(screen.queryByRole("button", { name: "Sign out" })).toBeNull();
  expect(screen.queryByRole("link", { name: "Open dashboard" })).toBeNull();
  expect(createSession).not.toHaveBeenCalled();
});

test("Sign out shows progress and, on failure, says so and stays signed in", async () => {
  vi.mocked(getMe).mockResolvedValue(oauth as never);
  vi.mocked(getAuthOptions).mockResolvedValue(open);
  let fail: (e: Error) => void = () => {};
  vi.mocked(logout).mockReturnValueOnce(new Promise((_, reject) => (fail = reject)));
  renderWithQuery(<NavAuth />);
  fireEvent.click(await screen.findByRole("button", { name: "Sign out" }));
  expect((await screen.findByRole("button", { name: "Signing out…" })).hasAttribute("disabled")).toBe(true);
  fail(new Error("offline"));
  expect((await screen.findByRole("alert")).textContent).toBe("Sign-out failed. Check your connection and try again.");
  expect(screen.getByRole("link", { name: "Open dashboard" })).toBeDefined();
  expect(screen.getByRole("button", { name: /Sign out/ }).hasAttribute("disabled")).toBe(false);
});
