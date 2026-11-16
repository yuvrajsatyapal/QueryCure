/** Same-origin API proxy (ADR-0034). Imported by `next.config.ts` (so no `@/` alias here).
 *
 * The browser calls the web app's own origin; Next rewrites `/api/v1/*` to the backend. The
 * session and CSRF cookies are then first-party to the web origin, which is what the cookie
 * model (SameSite=Lax, a CSRF cookie read by script, no Domain) needs when the two services live
 * on hosts that share no registrable domain (`*.onrender.com`).
 *
 * `BACKEND_ORIGIN` is read when the config loads. Rewrites are compiled into the build's routes
 * manifest, so it must be set for `next build`; a later change needs a rebuild. It is never
 * exposed to the browser (no `NEXT_PUBLIC_` prefix). */
const LOOPBACK = new Set(["localhost", "127.0.0.1", "[::1]"]);

/** Idle time before the proxy gives up on the backend. Next's own default is 30 s, shorter than a
 * sleeping free-tier backend needs to wake. The SSE heartbeat (15 s) keeps a live stream under it. */
export const DEFAULT_PROXY_TIMEOUT_MS = 120_000;

export interface BackendProxy {
  origin: string;
  timeoutMs: number;
}

export function resolveBackendProxy(
  backendOrigin: string | undefined,
  webOrigin: string,
  timeoutMs: string | undefined,
): BackendProxy | null {
  const raw = backendOrigin?.trim() ?? "";
  if (!raw) return null;
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    throw new Error(`BACKEND_ORIGIN must be an absolute origin, got ${JSON.stringify(raw)}.`);
  }
  const bare = url.pathname === "/" && !url.search && !url.hash && !url.username && !url.password;
  if ((url.protocol !== "https:" && url.protocol !== "http:") || !bare) {
    throw new Error(`BACKEND_ORIGIN must be a bare http(s) origin, got ${JSON.stringify(raw)}.`);
  }
  if (url.protocol !== "https:" && !LOOPBACK.has(url.hostname)) {
    throw new Error("BACKEND_ORIGIN must use https outside loopback.");
  }
  if (url.origin === new URL(webOrigin).origin) {
    // Proxying to itself would loop forever.
    throw new Error("BACKEND_ORIGIN must not be the web app's own origin (rewrite loop).");
  }
  let timeout = DEFAULT_PROXY_TIMEOUT_MS;
  if (timeoutMs?.trim()) {
    timeout = Number(timeoutMs);
    if (!Number.isInteger(timeout) || timeout < 1000) {
      throw new Error("BACKEND_PROXY_TIMEOUT_MS must be an integer of at least 1000.");
    }
  }
  return { origin: url.origin, timeoutMs: timeout };
}

export function apiRewrites(proxy: BackendProxy) {
  return [{ source: "/api/v1/:path*", destination: `${proxy.origin}/api/v1/:path*` }];
}
