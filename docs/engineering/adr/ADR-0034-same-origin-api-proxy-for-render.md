# ADR-0034: Same-origin API proxy for the Render free-tier deployment

- Status: Accepted (2026-11-16). Implemented and verified locally against a stand-in backend; **not deployed, not verified on Render**
- Area: Platform / Security
- Relates to: [ADR-0013](ADR-0013-auth-strategy.md), [ADR-0031](ADR-0031-restricted-access-email-allowlist.md), [ADR-0025](ADR-0025-pgbouncer-compatible-metadata-connections.md)

## Context
The trial is to run on free services without a custom domain: the Next.js web app and the FastAPI API as two Render web services, with Neon for metadata.

The authentication model assumes the web app and the API are **same-site**:
- The session cookie (`qc_session`, HttpOnly) and the CSRF cookie (`qc_csrf`) are set by the API with `SameSite=Lax`, `Secure`, and `Domain` taken from `COOKIE_DOMAIN`.
- The web app reads `qc_csrf` from `document.cookie` and sends it as `X-CSRF-Token` (`frontend/src/lib/api/client.ts`). The double-submit check needs the script to see that cookie.
- Every call is `fetch(..., { credentials: "include" })`, and the run stream is `EventSource(..., { withCredentials: true })`.

Two Render services get hosts like `qc-web.onrender.com` and `qc-api.onrender.com`. `onrender.com` is on the [Public Suffix List](https://publicsuffix.org/list/public_suffix_list.dat), so these are **cross-site**:
- `Lax` cookies are not sent on cross-site `fetch` or `EventSource` requests, so the API never sees the session.
- `Domain=.onrender.com` is refused by browsers.
- The web origin cannot read a cookie that belongs to the API origin, so the CSRF header cannot be built.
- `SameSite=None` would not repair the last point, and third-party cookie blocking (Safari, Chrome privacy modes) would break it again. It also weakens the cookie model.

## Options
1. **A domain we control** with `app.` and `api.` subdomains (the §3b design). Works with no code change, but needs a registrable domain, which this deployment does not have.
2. `SameSite=None` plus returning the CSRF token in a response body. Changes the authentication implementation, weakens CSRF defence, and still fails where third-party cookies are blocked.
3. **Serve the API from the web origin**: Next.js rewrites `/api/v1/*` to the backend. Cookies are first-party to the web host, so nothing in the authentication code changes.

## Decision
Option 3.

```
Browser ─▶ Render web service (Next.js) ──rewrite /api/v1/:path*──▶ Render API (uvicorn + embedded worker) ─▶ Neon
          one origin: https://<web>.onrender.com
```

- `frontend/next.config.ts` adds `rewrites()` only when `BACKEND_ORIGIN` is set (`frontend/src/lib/api/backendProxy.ts`). Without it the config is unchanged, so local builds and the Compose stacks behave as before.
- `BACKEND_ORIGIN` is a server-side variable (no `NEXT_PUBLIC_`), validated as a bare https origin (http only on loopback). It must not equal the web origin, which would loop.
- `NEXT_PUBLIC_API_BASE_URL` is the web app's **own** public origin, so the browser, the CSP (`connect-src`) and the OAuth links all use it.
- The backend's `PUBLIC_API_URL` is also the web origin, so OAuth callbacks are `https://<web>/api/v1/auth/{github,google}/callback`. `WEB_BASE_URL` is the same origin, `COOKIE_DOMAIN` stays **unset** (host-only cookies), and `CORS_ORIGINS` lists the web origin only because the settings validator requires it (same-origin requests do not use CORS).
- The proxy is path-, query- and method-preserving, and passes cookies, `X-CSRF-Token`, `Last-Event-ID`, `Set-Cookie` and `Location` through unchanged (measured, below).
- Cookie attributes, CSRF, sessions, the OAuth flow and the allowlist are **not modified**.

### Two settings that SSE needs (measured)
Run against a stand-in backend (uvicorn, same SSE headers and framing as `api/routers/runs.py`) behind `next start` 16.4.2:

1. **Compression must be off.** With Next's default `compress`, a browser-style `Accept-Encoding: gzip` made the stream arrive as `Content-Encoding: gzip` and **no event was delivered in 50 s**: the gzip middleware buffers a `text/event-stream` until it ends. With `compress: false` events arrived 2 s apart as sent and the 15 s heartbeats arrived on schedule. The config sets `compress: false` when the proxy is on.
2. **The proxy timeout is idle time, and its default is too short.** Next aborts a proxied request after 30 s by default (`experimental.proxyTimeout`). Measured with the timeout at 20 s: a request whose response headers took 25 s failed with 500 after 20 s, while an SSE stream whose gaps were 15–17 s lived past 50 s. Bytes, including heartbeats, reset it. A sleeping free-tier backend needs about a minute to wake, so the config raises it to 120 s (`BACKEND_PROXY_TIMEOUT_MS` overrides).

`compress` and `proxyTimeout` are read when `next start` runs, while the rewrite is compiled into the build's routes manifest. So **`BACKEND_ORIGIN` must be set both at build time and at run time**. If it is missing at run time the proxy still works, but compression is back on and SSE silently stops streaming. The deployment verification (DEPLOYMENT §3c) checks for this.

## Consequences
- \+ No change to authentication, CSRF, cookies or the allowlist. The cookie model keeps its meaning.
- \+ Small, off by default, covered by unit tests of the origin rules and the rewrite.
- \− **An extra hop and a double cold start.** The first visit after idle wakes the web service, then the API (about a minute each, [Render docs](https://render.com/docs/free)). A request that arrives during the API's wake is held up to the proxy timeout.
- \− **The web service carries all API traffic and SSE**, so its 512 MB, 750 shared instance hours and idle spin-down apply to every request. Keeping a stream open does not count as inbound traffic for Render's idle timer (unverified).
- \− **Client addresses.** Next's proxy does not add `X-Forwarded-For` (measured: the backend saw none), it passes a client-supplied value through unchanged, and it replaces `Host`. Rate limits key on `TRUSTED_PROXY_HOPS` entries from the right of that header, so the value depends on how many addresses Render's two edges add. The expected value is 2, **unverified on Render**. Too low means all users share one rate-limit bucket (stricter, not weaker); a client-supplied prefix cannot be chosen as the address as long as the value is not lower than the real number of proxies that append.
- \− Gzip is off for everything the web service serves, not only the stream. Render's edge may compress responses itself (unverified).
- \− `proxyTimeout` is an `experimental` Next option; a later Next version may rename it. The unit test and a build with the variable set would show that.

## Alternatives for later
- Keep compression on and have the API send `Cache-Control: no-cache, no-transform` on the stream (Next's compression middleware skips responses with `no-transform`; present in the bundled `compression`, not yet tested end to end). One backend line, needs approval because this change was limited to the frontend.
- Move the web app to a host with a native, streaming proxy or a platform rewrite, or put both behind one domain (option 1) once a domain exists. §3b is then the better route.
- If the proxy cannot carry SSE reliably on Render, fall back to polling the events endpoint; the stream is already resumable by sequence number.
