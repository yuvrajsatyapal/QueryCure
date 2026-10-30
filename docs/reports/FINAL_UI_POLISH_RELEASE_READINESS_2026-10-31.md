# Final UI polish and release-readiness checkpoint (2026-10-31)

Local only: no push, no deploy, no Neon access, no live model calls. Baseline: `main` at `dafbb9b` (ADR-0032 activation), 11 commits ahead of `origin/main`, clean tree.

## 1. Issues found

| # | Reported / suspected | Reproduced? | Cause | Fix |
|---|---|---|---|---|
| 1 | Black badge over the sidebar's Google/GitHub sign-in links | Yes, dev server only, every width and both themes (36×36 badge at bottom-left over both links) | Next.js development indicator (`nextjs-portal`, fixed bottom-left). Absent from the production build (no `nextjs-portal` element at any size) | `devIndicators: false` in `next.config.ts` (dev-only setting, no production CSS). A first attempt, `position: "bottom-right"`, made the badge cover the approval drawer's Close button and failed `sandbox-approval` and `trace-layout` e2e; every corner covers a control. Build and runtime errors still open the dev overlay |
| 2 | (found while checking short heights) Nav painted over the account footer | Yes, dev **and production**, e.g. 1024×360 and 320×360; Settings unreachable (37% in view). Would also hit taller laptops when the *Active runs* list is full | The nav was `min-h-0 flex-1` with no overflow, so it shrank below its content; the desktop sidebar had no scroll | Nav keeps its content height (`min-h-0` removed); desktop sidebar `overflow-y-auto`, as the mobile drawer already was |
| 3 | Mobile report dominated by identifiers and digests | Yes: two *Source details* blocks of full UUIDs and SHA-256 values in every replay report; reproduced report 4,634 px tall at 320 px | Presentation | Collapsed, labelled disclosure (below) |
| 4 | (found) Truncated evidence in the report | Yes: toolbar showed `manifest sha256:` plus 16 characters; each round showed an 8-character experiment ID with no way to see or copy the rest | Presentation | Full values in disclosures, each copyable |
| 5 | Empty Graph on an experiment replay reads as failure | Yes: "0 of 13 graph steps reached", "0 nodes · 0 tool calls", "No findings yet." on a completed, reproduced replay | Expected (replays run no agents), but unexplained | Replay-specific copy in the view strip, Graph note and Findings empty state |

Not reproduced: overlapping text or controls in reports at any tested width; horizontal page overflow (0 px at every width and theme, before and after).

## 2. Changes (frontend only)

- `frontend/src/components/layout/SideNav.tsx`, `AppShell.tsx`: issue 2.
- `frontend/next.config.ts`: issue 1.
- `frontend/src/components/report/TechnicalDetails.tsx` (new): native `<details>`, collapsed, summary "{label} · N IDs and digests"; values complete (wrapped, never truncated) and in the DOM when collapsed; per-value *Copy {label}* button copying the full value with a polite "Copied {label}" status; opens on `beforeprint`.
- `ReportView.tsx`: *Source details* (replay result, original recommendation) and a new per-round *Experiment details* (full experiment ID, result, environment, sandbox image and workload digests) use it. Outcome, comparison verdict, recommendation provenance, candidate and verification scope stay outside.
- `ReportPanel.tsx`: *Report integrity* disclosure (full manifest, report JSON and Markdown digests, sealing versions) replaces the 16-character prefix.
- `InvestigationView.tsx`, `TraceGraph.tsx` (`note` prop), `FindingsPanel.tsx` (`emptyText` prop): issue 5, `experiment_replay` runs only. No nodes, findings, events or engine changes.

Sealed content: no change to report JSON, Markdown, digests, manifests, builders, renderers, replay classification or exports. No backend, infra or fixture file changed (`git diff` empty for `backend/`, `infra/`, `frontend/src/test/fixtures/`).

## 3. Tests (written first, seen failing)

- `e2e/sidebar-footer.spec.ts` (new, 3 tests): 8 sizes (320×360 … 1440×900) × dark/light; every footer control (Settings, theme toggle, sign-in links) must be topmost at its own centre after scrolling into view, no nav link may intersect the footer, no sideways overflow; keyboard Tab reaches Settings at 1024×360, fully in view with a solid focus outline. Failed before the fix (nav/footer clash at 320×360; Settings 37% in view), then the dev badge failed it on the sign-in links.
- `report.test.tsx` (+5): collapsed labelled disclosure with complete values; copy writes the full value and announces it; a round keeps its full experiment ID; toolbar exposes the full manifest digest; disclosures open on `beforeprint`.
- `InvestigationView.test.tsx` (+2): replay copy in strip, Graph note and Findings; ordinary runs keep the step count.
- `e2e/replay-rehearsal.spec.ts`: opens the *Source details* disclosure before asserting the source run ID (the list is not in the accessibility tree while collapsed).

## 4. Verification (actual output)

| Check | Result |
|---|---|
| Frontend lint, typecheck | clean |
| Vitest | 607 passed (600 baseline + 7) |
| Production build (`NEXT_PUBLIC_API_BASE_URL=http://localhost:8000`) | succeeded |
| Playwright, run 1 | 34 passed, 2 failed (`sandbox-approval`, `trace-layout`: dev badge at bottom-right intercepted the drawer's Close; see issue 1) |
| Playwright, after `devIndicators: false` | the 3 affected specs 5/5; full suite **36/36** (33 baseline + 3 new) |
| Rehearsal (`playwright.rehearsal.config.ts`) | first run failed on the collapsed *Source details* list (expected, §3); after the spec update **1/1** |
| Accessibility | axe (WCAG 2.1 A/AA) in `replay-report.spec.ts` and `accessibility.spec.ts` pass in both themes; disclosures are native `<details>`/`<summary>`; Tab from the summary reaches *Copy Manifest* with a solid outline (production build, 320 px) |
| Responsive (production build) | report outcomes reproduced, drifted, inconclusive at 320/375/768/1440, failed and historical v1 and a real v2 replay at 320/1440, both themes, reduced motion: 0 px sideways overflow everywhere. Reproduced report at 320 px: 4,634 → 4,193 px; drifted at 375 px: 3,614 → 3,374 px |
| Backend (no backend file changed) | `tests/unit/reports` 290 passed; `tests/integration/test_replay_cutover.py` 13 passed |
| Cutover gate, local DB | `replay-cutover-check`: exit 0, `legacy_in_flight: 0` |
| Integrity, local DB, read only | `verify-integrity`: exit 0; 782/782 sealed reports and 9,076 artifacts verified, 0 failures (718 report-builder@1, 64 report-builder@2; new reports since the activation checkpoint are this session's e2e runs) |

Screenshots (git-ignored): `test-results/ui-polish-2026-10-31/before/` and `after/`. Sidebar "before" shots are from the dev server (they show the badge); "after" shots are from the production build. No "before" Graph view was captured (the first harness did not switch views); the before Waterfall shows the old counter.

## 5. Release-readiness audit (read only)

| # | Item | Status |
|---|---|---|
| 1 | ADR-0032 activation in local production code | Verified locally: `registry.CURRENT_*` = report-builder@2 / report-md@2 / schema 2 (`reports/registry.py`); `_close` classifies snapshot replays (audit §19) |
| 2 | v2 default for new reports | Verified locally: all 64 v2 reports are post-activation; every report sealed by this session's e2e runs is v2 |
| 3 | v1 registered for historical reports | Verified locally: v1 builder and renderer in `BUILDERS`/`RENDERERS`, `LEGACY_REPORT_VERSIONS`, nothing retired |
| 4 | Legacy cutover handling | Verified locally: `replay/cutover.py`; 13 cutover integration tests pass |
| 5 | No sealed report changed | Verified locally: no backend change; 782/782 verify against stored digests (consistency, not authenticity) |
| 6 | Existing reports verifiable | Verified locally (same run) |
| 7 | Backend/frontend compatibility | Verified locally: frontend renders schemas 1 and 2 (fixtures from the real builders, e2e 36/36, rehearsal 1/1); this change touches no API contract |
| 8 | Production deployment order documented | Yes: DEPLOYMENT "Replay outcome activation (ADR-0032)": step 0 (up to `8f4c14e`), drain, gate, frontend first, then API and worker together from the activation commit |
| 9 | Cutover gate available and tested | Yes: `python -m querycure.ops replay-cutover-check`; tested (`test_cutover_check_blocks_while_a_legacy_replay_is_in_flight`); exit 0 locally |
| 10 | Rollback and monitoring documented | Yes: same section; `infra/ops/replay_activation_monitoring.sql` (10 checks), `verify-integrity`, worker-log scan; rollback reverts the activation commit only |

**Deployed and verified in production: nothing.** Production runs the pre-activation build. This frontend change is compatible with both the pre-activation and activated backends (it reads no new fields), so it can ship with step 0.

## 6. Remaining blockers and open items

Release blockers for *deployment review*: none found locally. Open before or during an actual deployment (owner decisions, unchanged by this session): host and domain (D1, D5); deploy step 0, drain, gate, then the activation commit; real OAuth on a deployed origin; alerting; Neon PITR validation; production worker-log scan after deploy; F1 (intermittent SSE pool-checkout 500, root cause unknown, not seen in this session's 2 full e2e runs). Known flake noted in tooling memory (`trace-layout` `-0`) did not occur.

## 7. Verdict

- **Ready for deployment review:** yes, locally verified. Not deployed.
- **Landing page next:** reasonable once the owner has reviewed this checkpoint; the remaining items above are deployment and operations work, not app UI work.
