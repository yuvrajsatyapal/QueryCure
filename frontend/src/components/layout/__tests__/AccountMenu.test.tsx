import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderWithQuery } from "@/test/render";
import { API_BASE_URL } from "@/lib/api/client";
import { getMe, logout } from "@/lib/api/session";
import { AccountMenu } from "../AccountMenu";
import { SignInDialog } from "../SignInDialog";

vi.mock("@/lib/api/session", () => ({
  getMe: vi.fn(),
  createSession: vi.fn(),
  getAuthOptions: vi.fn(),
  logout: vi.fn(),
}));

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

test("a local session shows one Sign in button and no provider links until the dialog opens", async () => {
  vi.mocked(getMe).mockResolvedValue(local as never);
  const onSignIn = vi.fn();
  renderWithQuery(<AccountMenu onSignIn={onSignIn} />);
  expect(await screen.findByText("Local session")).toBeDefined();
  const signIn = screen.getByRole("button", { name: "Sign in" });
  expect(screen.queryByRole("link", { name: /Google|GitHub/ })).toBeNull();
  fireEvent.click(signIn);
  expect(onSignIn).toHaveBeenCalledOnce();
});

test("no Sign in button when the deployment offers no provider", async () => {
  vi.mocked(getMe).mockResolvedValue({ ...local, features: { ...features, googleLogin: false, githubLogin: false } } as never);
  renderWithQuery(<AccountMenu onSignIn={vi.fn()} />);
  expect(await screen.findByText("Local session")).toBeDefined();
  expect(screen.queryByRole("button", { name: "Sign in" })).toBeNull();
});

test("while the session loads, neither the Sign in button nor an account is shown", () => {
  vi.mocked(getMe).mockReturnValue(new Promise(() => {}));
  renderWithQuery(<AccountMenu onSignIn={vi.fn()} />);
  expect(screen.getByRole("status", { name: "Loading account" })).toBeDefined();
  expect(screen.queryByRole("button", { name: "Sign in" })).toBeNull();
  expect(screen.queryByRole("button", { name: /^Account/ })).toBeNull();
});

test("the sign-in dialog offers each configured provider through the existing login routes", async () => {
  vi.mocked(getMe).mockResolvedValue(local as never);
  renderWithQuery(<SignInDialog onClose={vi.fn()} />);
  const dialog = await screen.findByRole("dialog", { name: "Sign in to QueryCure" });
  expect(within(dialog).getByText("Choose how you'd like to continue.")).toBeDefined();
  const google = await within(dialog).findByRole("link", { name: "Continue with Google" });
  expect(document.activeElement).toBe(google);
  const github = within(dialog).getByRole("link", { name: "Continue with GitHub" });
  expect(google.getAttribute("href")).toBe(`${API_BASE_URL}/api/v1/auth/google/login?return_to=%2Fapp%2Fhistory`);
  expect(github.getAttribute("href")).toBe(`${API_BASE_URL}/api/v1/auth/github/login?return_to=%2Fapp%2Fhistory`);
});

test("only configured providers appear in the dialog", async () => {
  vi.mocked(getMe).mockResolvedValue({ ...local, features: { ...features, googleLogin: false } } as never);
  renderWithQuery(<SignInDialog onClose={vi.fn()} />);
  expect(await screen.findByRole("link", { name: "Continue with GitHub" })).toBeDefined();
  expect(screen.queryByRole("link", { name: "Continue with Google" })).toBeNull();
});

test("starting one sign-in blocks a second, duplicate start", async () => {
  vi.mocked(getMe).mockResolvedValue(local as never);
  renderWithQuery(<SignInDialog onClose={vi.fn()} />);
  const google = await screen.findByRole("link", { name: "Continue with Google" });
  // jsdom cannot navigate; stop the first click from trying while the handler still runs.
  google.addEventListener("click", (e) => e.preventDefault(), { once: true });
  fireEvent.click(google);
  expect(await screen.findByText("Redirecting to Google…")).toBeDefined();
  const github = screen.getByRole("link", { name: "Continue with GitHub" });
  expect(github.getAttribute("aria-disabled")).toBe("true");
  const second = new MouseEvent("click", { bubbles: true, cancelable: true });
  github.dispatchEvent(second);
  expect(second.defaultPrevented).toBe(true);
});

test("the dialog closes from its close button and Escape", async () => {
  vi.mocked(getMe).mockResolvedValue(local as never);
  const onClose = vi.fn();
  renderWithQuery(<SignInDialog onClose={onClose} />);
  await screen.findByRole("dialog", { name: "Sign in to QueryCure" });
  fireEvent.click(screen.getByRole("button", { name: "Close sign-in" }));
  fireEvent.keyDown(document, { key: "Escape" });
  expect(onClose).toHaveBeenCalledTimes(2);
});

test("a signed-in account shows its name and initials, never a hardcoded email", async () => {
  vi.mocked(getMe).mockResolvedValue(oauth("Ada Lovelace") as never);
  renderWithQuery(<AccountMenu onSignIn={vi.fn()} />);
  const button = await screen.findByRole("button", { name: "Account: Ada Lovelace" });
  expect(button.getAttribute("aria-haspopup")).toBe("menu");
  expect(button.getAttribute("aria-expanded")).toBe("false");
  expect(within(button).getByText("Ada Lovelace")).toBeDefined();
  expect(within(button).getByText("AL")).toBeDefined();
  expect(within(button).getByText("Signed in")).toBeDefined();
  expect(screen.queryByRole("button", { name: "Sign in" })).toBeNull();
  expect(button.querySelector("img")).toBeNull();
});

test("an account without a name falls back to a neutral label and a generic icon", async () => {
  vi.mocked(getMe).mockResolvedValue(oauth(null) as never);
  renderWithQuery(<AccountMenu onSignIn={vi.fn()} />);
  const button = await screen.findByRole("button", { name: "Account: Your account" });
  expect(within(button).getByText("Your account")).toBeDefined();
  expect(button.querySelector('[data-avatar="icon"]')).not.toBeNull();
});

test("the account menu toggles, closes on Escape and returns focus, and has no dead entries", async () => {
  vi.mocked(getMe).mockResolvedValue(oauth("Ada Lovelace") as never);
  renderWithQuery(<AccountMenu onSignIn={vi.fn()} />);
  const button = await screen.findByRole("button", { name: "Account: Ada Lovelace" });
  button.focus();
  fireEvent.click(button);
  const menu = screen.getByRole("menu", { name: "Account" });
  expect(button.getAttribute("aria-expanded")).toBe("true");
  expect(within(menu).getAllByRole("menuitem").map((i) => i.textContent)).toEqual(["Sign out"]);
  expect(document.activeElement).toBe(within(menu).getByRole("menuitem", { name: "Sign out" }));
  fireEvent.keyDown(menu, { key: "Escape" });
  expect(screen.queryByRole("menu")).toBeNull();
  expect(document.activeElement).toBe(button);
  fireEvent.click(button);
  fireEvent.pointerDown(button);
  fireEvent.click(button);
  expect(screen.queryByRole("menu")).toBeNull();
});

test("signing out uses the existing logout and the sidebar returns to the local session", async () => {
  vi.mocked(getMe).mockResolvedValueOnce(oauth("Ada Lovelace") as never).mockResolvedValue(local as never);
  vi.mocked(logout).mockResolvedValue(undefined);
  renderWithQuery(<AccountMenu onSignIn={vi.fn()} />);
  fireEvent.click(await screen.findByRole("button", { name: "Account: Ada Lovelace" }));
  await act(async () => fireEvent.click(screen.getByRole("menuitem", { name: "Sign out" })));
  expect(logout).toHaveBeenCalledOnce();
  expect(await screen.findByRole("button", { name: "Sign in" })).toBeDefined();
  expect(screen.queryByText("Ada Lovelace")).toBeNull();
});

test("a failed sign-out says so and keeps the account visible", async () => {
  vi.mocked(getMe).mockResolvedValue(oauth("Ada Lovelace") as never);
  vi.mocked(logout).mockRejectedValue(new Error("network"));
  renderWithQuery(<AccountMenu onSignIn={vi.fn()} />);
  fireEvent.click(await screen.findByRole("button", { name: "Account: Ada Lovelace" }));
  fireEvent.click(screen.getByRole("menuitem", { name: "Sign out" }));
  expect((await screen.findByRole("alert")).textContent).toMatch(/Sign-out failed/);
  expect(screen.getByRole("button", { name: "Account: Ada Lovelace" })).toBeDefined();
});

test("while signing out the account control is disabled", async () => {
  vi.mocked(getMe).mockResolvedValue(oauth("Ada Lovelace") as never);
  vi.mocked(logout).mockReturnValue(new Promise(() => {}));
  renderWithQuery(<AccountMenu onSignIn={vi.fn()} />);
  fireEvent.click(await screen.findByRole("button", { name: "Account: Ada Lovelace" }));
  fireEvent.click(screen.getByRole("menuitem", { name: "Sign out" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Account: Ada Lovelace" }).hasAttribute("disabled")).toBe(true));
  expect(screen.getByText("Signing out…")).toBeDefined();
});

test("the collapsed rail keeps sign-in and the account reachable by name", async () => {
  vi.mocked(getMe).mockResolvedValue(local as never);
  const { unmount } = renderWithQuery(<AccountMenu collapsed onSignIn={vi.fn()} />);
  expect(await screen.findByRole("button", { name: "Sign in" })).toBeDefined();
  unmount();
  vi.mocked(getMe).mockResolvedValue(oauth("Ada Lovelace") as never);
  renderWithQuery(<AccountMenu collapsed onSignIn={vi.fn()} />);
  expect(await screen.findByRole("button", { name: "Account: Ada Lovelace" })).toBeDefined();
});
