# Phase Completion Report Template

Copy to `docs/planning/reports/PHASE_<N>_REPORT.md` when a phase meets its exit criteria. Fill every section with facts; write "None" rather than deleting a section. Never include results that weren't actually produced.

---

# Phase <N> Report — <Phase name>

- **Dates:** <start> → <end> (UTC)
- **Exit criteria met:** yes / partially (explain)
- **Tasks completed:** T<N>.x, … (link [TASKS.md](TASKS.md))
- **Tasks deferred:** T<N>.y — reason, new target phase

## 1. What was implemented
Short description per capability, from the user's point of view, then the technical summary.

## 2. Important architecture decisions
| Decision | ADR / doc updated | Why |
|---|---|---|

## 3. Files changed
| Area | Files / modules | Notes |
|---|---|---|

## 4. Tests executed
Paste the actual commands and summarized real output.

| Suite | Command | Result (pass/fail counts) | Notes |
|---|---|---|---|
| Unit | `uv run pytest tests/unit -q` | | |
| Integration | | | |
| Security | | | |
| Evals | | metrics: | |
| Frontend | | | |

## 5. Acceptance criteria
| Criterion (from ROADMAP) | Status | Evidence (test name, screenshot, artifact) |
|---|---|---|

## 6. Known limitations
What doesn't work yet, rough edges, measurement caveats.

## 7. Security considerations
Controls added/changed, tests covering them, residual risks, anything needing review.

## 8. What I should study
Ordered list of modules/files to read, with one line on what to notice in each. Link the matching section of [LEARNING.md](../engineering/LEARNING.md).

## 9. Interview-relevant implementation details
3–6 concrete stories: a problem, the options, the choice, the trade-off, how it's tested. Include one failure/bug and how it was diagnosed.

## 10. Remaining work
Carry-over into the next phase, new risks (update [RISKS.md](RISKS.md)), doc updates still needed.
