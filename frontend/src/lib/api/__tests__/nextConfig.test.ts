import { PHASE_PRODUCTION_BUILD } from "next/constants";
import { afterEach, describe, expect, it, vi } from "vitest";
import config from "../../../../next.config";
import { DEFAULT_PROXY_TIMEOUT_MS } from "../backendProxy";

const WEB = "https://qc-web.onrender.com";
const API = "https://qc-api.onrender.com";

function load(env: Record<string, string | undefined>) {
  vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", WEB);
  vi.stubEnv("BACKEND_ORIGIN", undefined);
  vi.stubEnv("BACKEND_PROXY_TIMEOUT_MS", undefined);
  for (const [name, value] of Object.entries(env)) vi.stubEnv(name, value);
  return config(PHASE_PRODUCTION_BUILD);
}

afterEach(() => vi.unstubAllEnvs());

describe("next.config with BACKEND_ORIGIN", () => {
  it("rewrites /api/v1 to the backend, turns compression off and sets the default timeout", async () => {
    const result = load({ BACKEND_ORIGIN: API });
    expect(result.compress).toBe(false);
    expect(result.experimental?.proxyTimeout).toBe(DEFAULT_PROXY_TIMEOUT_MS);
    expect(await result.rewrites?.()).toEqual([
      { source: "/api/v1/:path*", destination: `${API}/api/v1/:path*` },
    ]);
  });

  it("uses BACKEND_PROXY_TIMEOUT_MS when set", () => {
    expect(load({ BACKEND_ORIGIN: API, BACKEND_PROXY_TIMEOUT_MS: "90000" }).experimental?.proxyTimeout).toBe(90000);
  });

  it("keeps the existing CSP and the web origin in connect-src", async () => {
    vi.stubEnv("NODE_ENV", "production"); // headers() is empty outside production
    const [rule] = (await load({ BACKEND_ORIGIN: API }).headers?.()) ?? [];
    const csp = rule?.headers.find((h) => h.key === "Content-Security-Policy")?.value ?? "";
    expect(csp).toContain(`connect-src 'self' ${WEB}`);
    expect(csp).not.toContain(API);
  });

  it("still refuses its own origin, a path and an unsafe scheme", () => {
    expect(() => load({ BACKEND_ORIGIN: WEB })).toThrow(/loop/);
    expect(() => load({ BACKEND_ORIGIN: `${API}/api` })).toThrow(/BACKEND_ORIGIN/);
    expect(() => load({ BACKEND_ORIGIN: "http://qc-api.onrender.com" })).toThrow(/https/);
  });
});

describe("next.config without BACKEND_ORIGIN", () => {
  it("generates no rewrite and leaves compression and the proxy timeout alone", () => {
    for (const origin of [undefined, "", "  "]) {
      const result = load({ BACKEND_ORIGIN: origin });
      expect(result.rewrites).toBeUndefined();
      expect(result.compress).toBeUndefined();
      expect(result.experimental).toBeUndefined();
    }
  });

  it("ignores BACKEND_PROXY_TIMEOUT_MS when there is no proxy", () => {
    expect(load({ BACKEND_PROXY_TIMEOUT_MS: "90000" }).experimental).toBeUndefined();
  });
});
