# ADR-0013: Backend-owned cookie sessions; local/anonymous users first, GitHub OAuth in Phase 5

- Status: Accepted (2026-10-11)
- Area: Security / Platform

## Context
Auth must protect user data and secrets, work with SSE (`EventSource` can't set headers), and not dominate early phases.

## Alternatives
1. Auth.js in Next.js issuing JWTs the backend verifies — popular; splits auth across two runtimes; JWT revocation complexity.
2. Hosted auth (Clerk, Supabase Auth) — fast; vendor dependency, cost at scale, another trust boundary.
3. **FastAPI owns auth: opaque session tokens (hashed in DB) in HttpOnly cookies; Phase 1 local single user + anonymous demo sessions; Phase 5 GitHub OAuth (Authlib) linking to the same `users` table.**

## Decision
Option 3.

## Rationale & trade-offs
- + One authority; cookies work for SSE; instant revocation by deleting the session row.
- + Learning value: OAuth code flow, CSRF, cookie security.
- − Requires web and API on same-site subdomains in production (DEPLOYMENT §3).
- − We implement CSRF protection ourselves (double-submit token).

## Consequences
All endpoints depend on `current_user`; anonymous users are real `users` rows (`kind=anonymous`) with retention limits.
