import { describe, expect, it } from "vitest";
import { apiRewrites, DEFAULT_PROXY_TIMEOUT_MS, resolveBackendProxy } from "../backendProxy";

const WEB = "https://qc-web.onrender.com";
const API = "https://qc-api.onrender.com";

describe("resolveBackendProxy", () => {
  it("is off when BACKEND_ORIGIN is unset or blank", () => {
    expect(resolveBackendProxy(undefined, WEB, undefined)).toBeNull();
    expect(resolveBackendProxy("  ", WEB, undefined)).toBeNull();
  });

  it("accepts a bare https origin and uses the default timeout", () => {
    expect(resolveBackendProxy(API, WEB, undefined)).toEqual({
      origin: API,
      timeoutMs: DEFAULT_PROXY_TIMEOUT_MS,
    });
    expect(resolveBackendProxy(`${API}/`, WEB, undefined)?.origin).toBe(API);
  });

  it("allows plain http on loopback only", () => {
    expect(resolveBackendProxy("http://127.0.0.1:8000", WEB, undefined)?.origin).toBe("http://127.0.0.1:8000");
    expect(() => resolveBackendProxy("http://qc-api.onrender.com", WEB, undefined)).toThrow(/https/);
  });

  it.each([`${API}/api`, "https://user:pw@qc-api.onrender.com", `${API}?x=1`, "not a url", "ftp://qc-api.onrender.com"])(
    "rejects %s",
    (bad) => {
      expect(() => resolveBackendProxy(bad, WEB, undefined)).toThrow(/BACKEND_ORIGIN/);
    },
  );

  it("refuses the web app's own origin, which would loop", () => {
    expect(() => resolveBackendProxy(WEB, WEB, undefined)).toThrow(/loop/);
  });

  it("reads and validates the timeout", () => {
    expect(resolveBackendProxy(API, WEB, "90000")?.timeoutMs).toBe(90000);
    for (const bad of ["abc", "999", "1.5"]) {
      expect(() => resolveBackendProxy(API, WEB, bad)).toThrow(/TIMEOUT/);
    }
  });
});

describe("apiRewrites", () => {
  it("proxies only /api/v1 and keeps the rest of the path", () => {
    expect(apiRewrites({ origin: API, timeoutMs: 1000 })).toEqual([
      { source: "/api/v1/:path*", destination: `${API}/api/v1/:path*` },
    ]);
  });
});
