import { afterEach, expect, test, vi } from "vitest";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { testQueryClient } from "@/test/render";
import { ApiError } from "@/lib/api/client";
import { createSession, getAuthOptions, getMe } from "@/lib/api/session";
import { useLandingAuth } from "../useLandingAuth";

vi.mock("@/lib/api/session", () => ({
  getMe: vi.fn(),
  createSession: vi.fn(),
  getAuthOptions: vi.fn(),
  logout: vi.fn(),
}));

const features = { liveInspection: true, sandbox: true, googleLogin: true, githubLogin: true };
const oauth = { user: { id: "u1", kind: "oauth", displayName: "Ada Lovelace" }, profile: "demo", features };
const local = { user: { id: "u0", kind: "local", displayName: null }, profile: "local", features };
const anonymous = { user: { id: "u2", kind: "anonymous", displayName: null }, profile: "demo", features: { ...features, googleLogin: false, githubLogin: false } };
const options = { restrictedAccess: false, githubLogin: true, googleLogin: true };
const error = (status: number, code: string) => new ApiError(code, "x", status, [], null);

function setup() {
  const client = testQueryClient();
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  return { client, ...renderHook(() => useLandingAuth(), { wrapper }) };
}

afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

test("pending until the session is known; the landing page never starts a session", async () => {
  vi.mocked(getAuthOptions).mockResolvedValue(options);
  vi.mocked(getMe).mockReturnValue(new Promise(() => {}));
  const { result } = setup();
  expect(result.current).toEqual({ status: "pending" });

  cleanup();
  vi.mocked(getMe).mockRejectedValue(error(401, "UNAUTHENTICATED"));
  const second = setup();
  await waitFor(() => expect(second.result.current.status).toBe("signedOut"));
  expect(createSession).not.toHaveBeenCalled();
});

test("an oauth account is signed in, with its display name, without waiting for the sign-in options", async () => {
  vi.mocked(getAuthOptions).mockReturnValue(new Promise(() => {}));
  vi.mocked(getMe).mockResolvedValue(oauth as never);
  const { result } = setup();
  await waitFor(() => expect(result.current).toEqual({ status: "signedIn", name: "Ada Lovelace" }));
});

test("a local or anonymous session is signed out, and the providers come from /me", async () => {
  vi.mocked(getAuthOptions).mockResolvedValue(options);
  vi.mocked(getMe).mockResolvedValue(local as never);
  const { result } = setup();
  await waitFor(() => expect(result.current).toEqual({ status: "signedOut", restricted: false, canSignIn: true }));
  cleanup();

  vi.mocked(getMe).mockResolvedValue(anonymous as never);
  const second = setup();
  await waitFor(() => expect(second.result.current).toEqual({ status: "signedOut", restricted: false, canSignIn: false }));
});

test("without a session (401) the sign-in options decide: open, restricted, or no provider", async () => {
  vi.mocked(getMe).mockRejectedValue(error(401, "UNAUTHENTICATED"));
  vi.mocked(getAuthOptions).mockResolvedValue({ restrictedAccess: true, githubLogin: false, googleLogin: true });
  const { result } = setup();
  await waitFor(() => expect(result.current).toEqual({ status: "signedOut", restricted: true, canSignIn: true }));
  cleanup();

  vi.mocked(getAuthOptions).mockResolvedValue({ restrictedAccess: false, githubLogin: false, googleLogin: false });
  const none = setup();
  await waitFor(() => expect(none.result.current).toEqual({ status: "signedOut", restricted: false, canSignIn: false }));
});

test("an account that is not approved (403 ACCESS_DENIED) is signed out of a restricted trial", async () => {
  vi.mocked(getMe).mockRejectedValue(error(403, "ACCESS_DENIED"));
  vi.mocked(getAuthOptions).mockReturnValue(new Promise(() => {}));
  const { result } = setup();
  await waitFor(() => expect(result.current).toEqual({ status: "signedOut", restricted: true, canSignIn: true }));
  expect(createSession).not.toHaveBeenCalled();
});

test("an unreachable API or a server error is unavailable, never a guess about the account", async () => {
  vi.mocked(getAuthOptions).mockResolvedValue(options);
  vi.mocked(getMe).mockRejectedValue(error(0, "NETWORK"));
  const { result } = setup();
  await waitFor(() => expect(result.current.status).toBe("unavailable"));
  cleanup();

  vi.mocked(getMe).mockRejectedValue(error(503, "UNAVAILABLE"));
  const down = setup();
  await waitFor(() => expect(down.result.current.status).toBe("unavailable"));

  cleanup();
  vi.mocked(getMe).mockRejectedValue(error(401, "UNAUTHENTICATED"));
  vi.mocked(getAuthOptions).mockRejectedValue(error(0, "NETWORK"));
  const noOptions = setup();
  await waitFor(() => expect(noOptions.result.current.status).toBe("unavailable"));
});

test("window focus re-reads the session, so a sign-out in another tab shows here", async () => {
  vi.mocked(getAuthOptions).mockResolvedValue(options);
  vi.mocked(getMe).mockResolvedValueOnce(oauth as never).mockRejectedValue(error(401, "UNAUTHENTICATED"));
  const { result } = setup();
  await waitFor(() => expect(result.current.status).toBe("signedIn"));
  expect(getMe).toHaveBeenCalledTimes(1);

  act(() => {
    window.dispatchEvent(new Event("focus"));
  });
  await waitFor(() => expect(result.current).toEqual({ status: "signedOut", restricted: false, canSignIn: true }));
  expect(getMe).toHaveBeenCalledTimes(2);
});

test("a page restored from the back/forward cache re-reads the session; a normal load does not", async () => {
  vi.mocked(getAuthOptions).mockResolvedValue(options);
  vi.mocked(getMe).mockResolvedValueOnce(oauth as never).mockRejectedValue(error(401, "UNAUTHENTICATED"));
  const { result } = setup();
  await waitFor(() => expect(result.current.status).toBe("signedIn"));

  act(() => {
    window.dispatchEvent(new PageTransitionEvent("pageshow", { persisted: false }));
  });
  expect(getMe).toHaveBeenCalledTimes(1);

  act(() => {
    window.dispatchEvent(new PageTransitionEvent("pageshow", { persisted: true }));
  });
  await waitFor(() => expect(result.current.status).toBe("signedOut"));
  expect(getMe).toHaveBeenCalledTimes(2);
});

test("a failed re-read keeps the last known account instead of demoting it, but a 401 does not", async () => {
  vi.mocked(getAuthOptions).mockResolvedValue(options);
  vi.mocked(getMe).mockResolvedValueOnce(oauth as never).mockRejectedValueOnce(error(0, "NETWORK"));
  const { result } = setup();
  await waitFor(() => expect(result.current.status).toBe("signedIn"));
  act(() => {
    window.dispatchEvent(new Event("focus"));
  });
  await waitFor(() => expect(getMe).toHaveBeenCalledTimes(2));
  expect(result.current).toEqual({ status: "signedIn", name: "Ada Lovelace" });
});

test("listeners are removed on unmount", async () => {
  vi.mocked(getAuthOptions).mockResolvedValue(options);
  vi.mocked(getMe).mockResolvedValue(oauth as never);
  const { result, unmount } = setup();
  await waitFor(() => expect(result.current.status).toBe("signedIn"));
  unmount();
  window.dispatchEvent(new Event("focus"));
  expect(getMe).toHaveBeenCalledTimes(1);
});
