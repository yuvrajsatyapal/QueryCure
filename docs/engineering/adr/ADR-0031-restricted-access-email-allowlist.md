# ADR-0031: Restricted access by a server-side email allowlist

- Status: Accepted (2026-10-23)
- Area: Security / Platform
- Amends: [ADR-0013](ADR-0013-auth-strategy.md)

## Context
In the demo profile, anyone who has the URL gets an anonymous session (production hardening report N6). A restricted hosted trial must admit only accounts the owner approved, and enforce that on the backend.

### Audit of the existing architecture (2026-10-23)
- Sessions are opaque tokens, stored hashed in `sessions`, sent in an HttpOnly cookie. Every protected endpoint resolves the user through `api/deps.py`: `current_user` for normal requests and `stream_user` for SSE. Mutations also need the double-submit CSRF token.
- `POST /session` creates the session: the single local user in the local profile, and a new anonymous `users` row in the demo profile.
- The OAuth callback (`api/routers/auth.py`) turns an anonymous user into an account, or merges it into an existing one, and then rotates the session.
- Neither provider requests an email today. Google asks for `openid profile` and GitHub for `read:user`.
- `users.email TEXT` has existed since the baseline migration and has never been written, and `qc_app` already has `UPDATE` on `users`. **No migration is needed.**
- The demo gallery, the workload catalog, health checks and the OAuth login and callback routes are public. They take no user and touch no user data.

## Options
1. **Allowlist in configuration** (`ACCESS_ALLOWLIST`). Changing it needs a restart. No migration and no admin UI.
2. Allowlist table in the metadata DB. Changes apply without a restart, but it needs a migration and either an admin path or manual SQL against the hosted DB.
3. Allowlist by `(provider, subject)` pairs, as DEPLOYMENT §3a first suggested. Nobody's email is involved, but the owner must find opaque numeric IDs before inviting anyone.

## Decision
Option 1, keyed by **provider-verified email**, which the owner asked for. It is off by default and turned on with `RESTRICTED_ACCESS=true`.

### Behaviour while `RESTRICTED_ACCESS=true`
| Request | Result |
|---|---|
| `POST /session` with no valid session | `403 ACCESS_DENIED`. No anonymous user is created |
| A protected endpoint with no session, or with an anonymous or local session left over from before | `401 UNAUTHENTICATED` |
| A protected endpoint with an OAuth session whose stored email is not on the list (revoked, or signed in before restriction) | `403 ACCESS_DENIED` |
| A protected endpoint with an OAuth session whose stored email is on the list | Normal |
| OAuth callback where none of the account's verified emails are on the list | Redirect with `?auth_error=not_allowed`. No user row and no session are created |
| OAuth callback where a verified email is on the list | Sign in, store the matched email in `users.email`, rotate the session |
| `GET /auth/options` (new, public) | `{restricted_access, github_login, google_login}`, so the web app can show sign-in buttons before a session exists |

- The check runs on **every request** (`current_user` and `stream_user`), against the email stored at sign-in. Removing an address and restarting the API therefore revokes access on the next request, including SSE reconnects, without deleting sessions.
- **Provider verification.**
  - Google: the `email` scope is added, and the email counts only when userinfo returns `email_verified: true`.
  - GitHub: the `user:email` scope is added. `GET /user/emails` is read, and only entries with `verified: true` count. Any verified address may match.
  - Comparison is exact after trimming and lowercasing. No other normalisation is done (for example, Gmail dots are not folded).
- **The email scopes are requested only while restricted.** With restriction off, sign-in behaves exactly as before, ADR-0013's "no email" still holds, and nothing is written to `users.email`.
- **No details are exposed.** Error messages are generic, and logs record the provider and the outcome, never the email or the list.
- **Settings validation:**
  - `RESTRICTED_ACCESS` is refused in the local profile, so local development and the stub-model e2e tests are unchanged.
  - It needs at least one configured OAuth provider.
  - Setting `ACCESS_ALLOWLIST` while `RESTRICTED_ACCESS` is off is refused, so an operator never thinks they restricted access when they did not.
  - An empty list is allowed and means nobody gets in, which works as a kill switch.

## Trade-offs
- \+ Small: a setting, a dependency check and a callback check. No migration and no new table.
- \+ Fails closed: a missing or stale email is denied.
- − Every list change needs a restart, so revocation takes effect at restart, not instantly.
- − Revocation is checked per request. An SSE stream that is already open keeps streaming until it disconnects, and a job the user already queued runs to the end. Both are refused from the next request onwards.
- − An approved user's email is stored (`users.email`) while restriction is on. It is retained until the account is deleted, like the display name.
- − A GitHub "verified" email proves the user once confirmed that inbox, not that they own it today.
- − The demo gallery stays public. It is static, prerecorded content with no LLM, no database work and no user data.

## Consequences
- The SessionGate in the web app shows a sign-in screen when `POST /session` returns 403 or `/me` returns 403.
- DEPLOYMENT §3a documents how to add and remove accounts.
- Tests cover approved, unapproved, unverified, anonymous and revoked access, plus the settings rules.
