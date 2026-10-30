# OAuth production verification checklist (Google and GitHub)

**Status (2026-10-18): not performed.** The automated suites pass (`test_github_oauth.py`, `test_google_oauth.py`, with providers faked over HTTP). No real sign-in has run against Google or GitHub, because there is no deployed origin with registered callbacks. Record each run in the table at the end. Never paste client secrets, codes or cookie values into chat, tickets or this file.

## What the code does (reviewed 2026-10-18)

| Control | Implementation |
|---|---|
| Flow | Authorization code + PKCE `S256` (`auth/github.py`, `auth/google.py`) |
| Scopes | GitHub `read:user`; Google `openid profile`. No email is requested or stored, and provider tokens are discarded after one profile call |
| State | 32-byte random value in the HttpOnly `qc_oauth` cookie (10 min, `SameSite=Lax`, path scoped to `/api/v1/auth/<provider>`, `Secure` outside local). Compared in constant time on callback; the cookie is deleted on success and failure |
| Callback | `<PUBLIC_API_URL>/api/v1/auth/{github,google}/callback` |
| Return target | Same-site relative path only (`/…`, not `//`, no backslash); otherwise `/app` |
| Identity | The provider's stable subject (GitHub numeric id, Google `sub`), never the display name |
| Session | On sign-in the previous `qc_session` is revoked server-side and a new one is issued (fixation defence). `qc_session` is HttpOnly; `qc_csrf` is readable for the double-submit `X-CSRF-Token` header. Both are `Secure` and `SameSite=Lax` outside local, with `Domain=COOKIE_DOMAIN` |
| Anonymous work | A new account converts the anonymous user in place. Signing in to an existing account moves the anonymous user's credentials and merges its data |
| Logout | `POST /api/v1/auth/logout`, CSRF-protected, revokes the session row and clears the cookies |
| Failures | Redirect to `<WEB_BASE_URL>/app?auth_error=<code>`. The code is stable; the provider's body is never echoed. Login is rate-limited (`session_create`) |

## Prerequisites (owner actions)

1. **A deployed origin pair** on one registrable domain, e.g. `https://app.<domain>` (web) and `https://api.<domain>` (API), both with valid TLS (DEPLOYMENT §3).
2. **GitHub OAuth app.** In GitHub → Settings → Developer settings → OAuth Apps → New:
   - Homepage URL `https://app.<domain>`;
   - Authorization callback URL `https://api.<domain>/api/v1/auth/github/callback` (exact match);
   - generate a client secret.
3. **Google OAuth client.** In Google Cloud console → APIs & Services → Credentials → Create OAuth client ID → Web application:
   - Authorized redirect URI `https://api.<domain>/api/v1/auth/google/callback`;
   - consent screen scopes `openid` and `profile` only;
   - while the consent screen is in **Testing**, add each test account under Test users.
4. **Host secret store**, never `.env` in an image:
   - `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`;
   - `PUBLIC_API_URL=https://api.<domain>` and `WEB_BASE_URL=https://app.<domain>` (settings refuse non-`https` outside local when OAuth is on);
   - `COOKIE_DOMAIN=.<domain>` and `CORS_ORIGINS=["https://app.<domain>"]`.
5. **Two test accounts per provider** that you control. Use no personal production accounts.

## Checks (run per provider, in a private browser window)

| # | Step | Expected |
|---|---|---|
| 1 | Open the web app; start one investigation anonymously; note its URL | Investigation visible |
| 2 | DevTools → Application → Cookies: note that `qc_session` exists (do not copy the value anywhere) | `HttpOnly`, `Secure`, `SameSite=Lax`, domain `.<domain>` |
| 3 | Click **Sign in** in the sidebar, then "Continue with <provider>" on the `/sign-in` page (a restricted trial redirects gated pages to the same page) | Redirect to the provider; the URL has `code_challenge_method=S256`, a `state`, and the exact registered `redirect_uri`. `qc_oauth` is set on the API path |
| 4 | Approve on the provider | Redirect back to `https://app.<domain>/app` (or the `return_to` path) |
| 5 | Inspect cookies | `qc_session` **value changed**; `qc_oauth` gone |
| 6 | `GET https://api.<domain>/api/v1/me` from the app | The account kind is the provider and the display name is shown; no email |
| 7 | Open the investigation from step 1 | Still visible and owned by the signed-in account |
| 8 | Sign out | 204. `/me` no longer shows the account, and the step-1 investigation is **not** visible from this browser |
| 9 | Sign in from a second private window as the same account, then sign out in the first window | The second window stays signed in (sessions are per device). That revoked sessions cannot be reused is covered by the automated tests; do not copy cookie values to test it by hand |
| 10 | Sign in again as the same account | The step-1 investigation is visible again (subject-based identity) |
| 11 | Second test account | Sees none of the first account's investigations (404 on its URL) |
| 12 | Tamper: start login, then edit the `state` query value on the callback URL | Redirect with `?auth_error=…`; no session issued |
| 13 | Deny consent at the provider | Redirect with `?auth_error=…`; no 500 |
| 14 | `return_to=//evil.example` on `/auth/<provider>/login` | After sign-in, lands on `/app`, not off-site |
| 15 | API logs for the run | `oauth_signed_in` / `oauth_failed` events only; no codes, tokens, secrets or emails |

## Results log

| Date | Origin | Provider | Checks passed | Failures / notes | Operator |
|---|---|---|---|---|---|
| — | — | — | not run | No deployed origin yet | — |
