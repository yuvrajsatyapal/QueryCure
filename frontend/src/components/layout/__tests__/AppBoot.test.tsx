import { afterEach, expect, test, vi } from "vitest";
import { act, cleanup, screen, waitFor } from "@testing-library/react";
import { renderWithQuery } from "@/test/render";
import { ApiError } from "@/lib/api/client";
import { listInvestigations } from "@/lib/api/investigations";
import { getMe } from "@/lib/api/session";
import { AppBoot } from "../AppBoot";

vi.mock("@/lib/api/session", () => ({ getMe: vi.fn(), createSession: vi.fn(), logout: vi.fn(), getAuthOptions: vi.fn() }));
vi.mock("@/lib/api/investigations", async (orig) => ({ ...(await orig<typeof import("@/lib/api/investigations")>()), listInvestigations: vi.fn() }));
vi.mock("next/navigation", () => ({ usePathname: () => "/app", useRouter: () => ({ push: vi.fn() }) }));

const me = { user: { id: "u1", kind: "oauth", displayName: "Ada" }, profile: "local", features: {} };
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.useRealTimers();
});

test("covers the app until the account and the first investigations are in, then leaves for good", async () => {
  let release: (v: unknown) => void = () => {};
  vi.mocked(getMe).mockResolvedValue(me as never);
  vi.mocked(listInvestigations).mockReturnValue(new Promise((r) => (release = r)) as never);
  renderWithQuery(<AppBoot />);
  expect(screen.getByRole("heading", { name: "Getting QueryCure ready" })).toBeDefined();
  expect(await screen.findByText("Loading your workspace…")).toBeDefined();
  expect(screen.getByRole("heading", { name: "Getting QueryCure ready" })).toBeDefined();
  await act(async () => release({ items: [], nextCursor: null }));
  await waitFor(() => expect(screen.queryByRole("heading", { name: "Getting QueryCure ready" })).toBeNull());
});

test("a 401 while the session starts keeps the screen up, without an error", async () => {
  vi.mocked(getMe).mockRejectedValue(new ApiError("UNAUTHENTICATED", "no", 401, [], null));
  renderWithQuery(<AppBoot />);
  await waitFor(() => expect(getMe).toHaveBeenCalled());
  expect(screen.getByText("Confirming your account…")).toBeDefined();
  expect(screen.queryByRole("alert")).toBeNull();
  expect(listInvestigations).not.toHaveBeenCalled();
});

test("an unreachable API offers Try again and Back to home at once", async () => {
  vi.mocked(getMe).mockRejectedValue(new ApiError("INTERNAL", "boom", 500, [], null));
  renderWithQuery(<AppBoot />);
  expect(await screen.findByRole("alert")).toBeDefined();
  expect(screen.getByText("Can't reach QueryCure")).toBeDefined();
  expect(screen.getByRole("button", { name: "Try again" })).toBeDefined();
  expect(screen.getByRole("link", { name: "Back to home" }).getAttribute("href")).toBe("/");
});

test("a slow load shows the recovery panel after a few seconds", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  vi.mocked(getMe).mockReturnValue(new Promise(() => {}));
  renderWithQuery(<AppBoot />);
  expect(screen.queryByRole("alert")).toBeNull();
  await act(async () => void vi.advanceTimersByTime(4100));
  expect(screen.getByText("Still connecting to QueryCure")).toBeDefined();
  expect(screen.getByText("Taking a little longer…")).toBeDefined();
});

test("a denied account does not wait: SessionGate hands it to the sign-in page", async () => {
  vi.mocked(getMe).mockRejectedValue(new ApiError("ACCESS_DENIED", "no", 403, [], null));
  renderWithQuery(<AppBoot />);
  await waitFor(() => expect(screen.queryByRole("heading", { name: "Getting QueryCure ready" })).toBeNull());
});
