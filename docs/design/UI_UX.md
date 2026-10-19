# UI / UX Specification

Status: Planned. Tokens and components: [DESIGN_SYSTEM.md](DESIGN_SYSTEM.md). API: [API_DESIGN.md](../architecture/API_DESIGN.md).

## 1. Information architecture

```
/                         Landing (public)
/demo                     Demo gallery (prerecorded + replayable investigations)
/app                      Dashboard
/app/connections          Database connections
/app/investigations/new   New investigation (workspace in "draft" state)
/app/investigations/[id]  Investigation workspace (primary interface)
   ?tab=plan|findings|tournament|report     tabs inside workspace
/app/investigations/[id]/plan-explorer      Full-screen plan explorer
/app/history              Investigation history
/app/replay/[runId]       Reproducibility & replay
/app/reports/[runId]      Report (printable reading view)
/app/settings             Settings (profile, BYOK, theme, budgets)
```

Navigation: left nav = Dashboard, New investigation, History, Connections, Settings. Reports and replay are reached from an investigation. Breadcrumb in the top bar: `Investigations / Slow customer orders page / Run 2`.

URL is the source of truth for tab and selected entity (`?tab=plan&node=7`), so links are shareable and back/forward work. Zustand holds only ephemeral UI state (panel sizes, selected plan node hover, editor draft).

## 2. Global states

Every data-driven region implements these states — designed, not defaulted:

| State | Treatment |
|---|---|
| Loading | Skeleton matching final layout (table rows, graph placeholder). No full-page spinners. |
| Empty | One sentence + primary action + "Try a demo workload" link |
| Error | What failed (from `error.message`), what the user can do, retry button; `request_id` copyable |
| Partial success | Content shown with a top banner: "Run ended early (budget exhausted). 2 of 4 candidates measured." |
| Cancelled | Grey banner with cancel time; results so far remain visible; "Re-run" action |
| Awaiting approval | Persistent banner + ApprovalCard focused; browser tab title prefixed `● Approval needed` |
| Stale connection | SSE disconnected > 10 s: subtle "Reconnecting…" pill; auto-resume with `Last-Event-ID` |

## 3. Screens

### 3.1 Landing page (`/`)
- **Purpose:** explain the product in 10 seconds and route to the demo.
- **Layout:** headline + one-line subhead; a static, real screenshot of the workspace (not an illustration); "How it works" as a 5-step horizontal strip (Inspect → Hypothesize → Propose → Benchmark → Verify) with the Verify step emphasized; honesty section ("What 'verified' means"); CTA buttons: *Open demo* (primary), *Run locally* (secondary, links to README).
- **Mobile:** single column; steps stack vertically.

### 3.2 Dashboard (`/app`)
- **Purpose:** resume work, see outcomes at a glance.
- **Layout:** top row of three summary panels with varied widths (Active runs · Awaiting approval · Recent outcomes distribution); below, a table of recent investigations (title, mode icons, outcome ClaimBadge, duration, updated).
- **Interactions:** row click → workspace; approval panel items jump straight to the ApprovalCard.
- **Empty:** "No investigations yet" + New investigation + demo link.

### 3.3 Database connections (`/app/connections`)
- **Purpose:** register restricted connections and see capabilities.
- **Layout:** table (name, host, environment badge, purpose, last test, capability icons); "Add connection" sheet with form + collapsible "Create a restricted role" SQL snippet (copyable) explaining required grants.
- **Test result:** capability checklist (✓ read-only role, ✓ pg_stat_statements, ✗ superuser refused…) with warnings in `--inconclusive`, refusals in `--rejected`.
- **Validation:** host blocked by SSRF guard → inline error "Private network addresses aren't allowed on this deployment."
- **Public demo:** page shows feature-disabled explanation and offline alternative.

### 3.4 Investigation workspace (`/app/investigations/[id]`) — primary interface
Three resizable panels:

| Left (context) | Center (results) | Right (agents) |
|---|---|---|
| SQL editor (CodeMirror, PG dialect), param sets editor, mode selector (A/B/C toggles with availability), connection or workload picker, schema browser (tables → columns, indexes, stats) | Tabs: **Plan** (graph/tree + node details) · **Findings** (hypotheses with evidence) · **Tournament** · **Report** | Live timeline (agent/tool events), budget meter (LLM calls, tokens, time), approval card when pending, run controls (Start, Cancel, Re-run) |

- **Draft state:** editor active, "Start investigation" primary; plan tab shows uploaded/EXPLAIN plan if available.
- **Running:** editor read-only (shows the exact query being investigated); timeline streams; findings appear incrementally with ClaimBadges.
- **Findings tab:** hypotheses list sorted by confidence; each shows statement, ClaimBadge, supporting/contradicting EvidenceChips, verification method, linked candidates. Clicking an EvidenceChip highlights the plan node in the Plan tab.
- **Keyboard:** `⌘/Ctrl+Enter` start, `Esc` close drawers, `[`/`]` switch tabs, `g p` plan, `g f` findings.
- **Mobile:** tabs Query · Plan · Agents · Results; approval card full-screen modal.

### 3.5 Execution-plan explorer (`/plan-explorer`, also embedded)
- **Graph view (React Flow):** top-down tree laid out with dagre; node = PlanNode component; edge thickness ∝ actual (or estimated) rows on a log scale; hottest node by self time gets the accent border.
- **Tree-table view:** indented rows with columns: node, relation, est rows, actual rows, error ratio, self time %, buffers hit/read, loops. Default on mobile and for screen readers.
- **Node detail drawer:** all raw fields, derived metrics, linked evidence/findings.
- **Diff mode:** two plans side by side; nodes matched structurally; changed node types highlighted, metric deltas shown; summary "Seq Scan → Index Scan on orders; Sort removed".
- **Empty:** "No plan yet — paste EXPLAIN (FORMAT JSON) output or run an investigation."

### 3.6 Investigation page: split trace, evidence navigation, header

Implemented as a LangSmith-style **split trace** ([ADR-0030](../engineering/adr/ADR-0030-linear-langsmith-ui-direction.md); DESIGN_SYSTEM §5 "Trace"). Frontend only: everything shown comes from run events and existing endpoints; nothing is inferred or filled in.

**Header (sticky).** Breadcrumb, title, run status pill, run selector dropdown (all runs of the investigation, newest first, kind, relation, status, report link), compact usage meters (LLM calls, tokens, tool calls against the run budget, from `GET /runs/{id}`), model, Replay / Cancel. Sticks to the top of the viewport with an opaque background and a bottom hairline; content scrolls beneath it and never under it (the trace column offsets by the header height). The objective and notices sit below the sticky part.

**Split layout.** Left: the step tree (region "Agent timeline"). Right: details of the selection (region "Selection details").
- The tree's first row is the **run**. Selecting it (the default) shows the run results tabs: Findings · Plan · Tournament · Report.
- Selecting any other row shows **step details** with tabs:
  - **Input:** what started the step as recorded in its start event (node, agent, attempt; tool name and calling agent). Prompts are not recorded (only a prompt version, server-side). Tool arguments are stored redacted on the server and not exposed to the browser. Each gap is stated, never filled in.
  - **Output:** what the step recorded: status, latency, evidence produced, and the log events nested under it (findings, hypotheses, summaries, candidates, verdicts, errors). Raw model output is stored server-side as an artifact and not exposed here. For a log event, its recorded payload fields.
  - **Metadata:** span kind, id, agent, status, start/end, latency, attempt, event sequence numbers, raw events (collapsed).
  - **Evidence:** every evidence ID the step recorded, each resolved on demand to kind, summary and provenance; plan-node evidence offers "Show in plan". Unresolvable IDs say so.
  - "Back to run results" returns to the run row.
- Below 1280px the tree stacks above the details.
- Parallel analysts are sibling steps under the run, as emitted; no lanes are drawn.

**Tree keyboard model** (WAI-ARIA tree, roving focus, selection follows focus): ↑/↓ previous/next visible row; → expands, or moves to the first child; ← collapses, or moves to the parent; Home/End first/last row. Clicking a chevron toggles; clicking a row selects. Log rows can be hidden; Collapse/Expand all. Selecting a row inside a collapsed node (from elsewhere) reveals it.

**Evidence navigation** (pure logic in `lib/investigation/links.ts`, unit-tested):
- A finding or hypothesis offers **"Show step"**, which selects the trace row of its `finding.created` / `hypothesis.created` event (matched by key). If no event carries the key (older run, events still loading), the control says "Step not recorded". If several match, it selects the first and says how many.
- Opening evidence that cites a plan node selects that node in the Plan tab (tree view). If the cited plan is not among this run's plans, or the node ID is absent from it, a notice says so and stays on the current view. Evidence that fails to load shows an error with its ID.
- Plan nodes show **"Cited by"**: findings and hypotheses whose evidence resolves to that node, and the tree table shows a citation count per node. Evidence is resolved per ID through `GET /runs/{id}/evidence/{evidence_id}` (immutable, cached); while resolving, the count reads as pending; failures are counted and reported, not hidden.

### 3.7 Optimization tournament (tab)
- Table: candidate (kind icon, short SQL), addresses (hypothesis links), VerdictPill, speedup median + SpeedupBar (CI), regression check per param set, index size, build time, write overhead (or "unmeasured").
- Winner row has the accent left border (only one); rejected rows show reason codes.
- Round selector when multiple rounds occurred.
- **Empty:** "No candidates benchmarked" with reason (Mode C unavailable / approvals declined / not needed).

### 3.8 Benchmark comparison (drill-down from a tournament row)
- Latency distribution chart per arm (dot strip + box), per param set tabs.
- Stats table: n, median, p95 (or n/a), CV, min/max, bootstrap CI.
- Correctness panel: fingerprints, row counts, order mode (ordered/multiset), outcome.
- Environment panel: PG version, settings, workload id, hardware, provenance badge (`measured` / `prerecorded`).
- Plan diff link.

### 3.9 Investigation history (`/app/history`)
- Filterable table (outcome, mode, date range, text search on title), cursor pagination ("Load more").
- Row actions: open, replay, delete (soft, with undo toast for 10 s).

### 3.10 Reproducibility & replay (`/app/replay/[runId]`)
- Manifest viewer: inputs with hashes (copy), environment, models/prompt versions, event count/digest.
- Actions: **Verify & replay report** (per-check ✓/✗ with failure codes; success copy is exactly "Integrity check passed against stored digests", never "tamper-proof"), **Re-run experiment** (confirmation dialog shows the exact DDL; if not replayable, show the reason code in words), **Re-investigate** (Post-MVP).
- Replay attempt history with status badges (`verified`, `verified_stored_only`, `integrity_failed`, `reproduced`, `reproduced_with_drift`, `not_reproduced`, `inconclusive`, …).
- Comparison view for experiment replay: per pair original vs replay verdicts, speedup drift with CI against the equivalence band, absolute latencies side by side (labeled not used for classification), environment diff (all differing fields, including minor ones). Labels follow `comparison_mode`: same-environment results say "Reproduced / Not reproduced"; cross-environment results say "Consistent across environments / Conclusion differs across environments" under a banner, and never use the word "reproduced".
- Reports in an unsupported schema version display the stored Markdown with an "archived format" banner.

### 3.11 Reports (`/app/reports/[runId]`)
- Reading layout (max 880px text width + wide figures): summary box (outcome, confidence, recommendation), root cause, evidence table, recommendation with DDL and rollback, plan diff figure, benchmark table/chart, trade-offs, limitations, reproducibility block.
- Export: Markdown, JSON. Print stylesheet.
- Every number carries provenance; LLM-written paragraphs carry a subtle "AI-written summary" label.

### 3.12 Settings (`/app/settings`)
- Sections: Profile · LLM keys (BYOK: provider, masked hint, default model, test button, delete) · Defaults (budget profile, theme) · Data (delete all my data).
- Key entry field is `type=password`, never echoed back; after saving shows `••••abcd`.

## 4. Key interaction flows

1. **Demo flow (public):** Landing → Open demo → pick `orders_ecommerce` → workspace pre-filled → Start (needs BYOK; prompt to add key or view prerecorded replay) → watch timeline → tournament shows prerecorded benchmark (◆ labeled) → report.
2. **Local verify flow:** New investigation → paste query + param sets → choose workload → Start → approve candidates → tournament → report → export.
3. **Live diagnose flow:** Connections → add + test → New investigation with connection → findings (unverified recommendations if no sandbox) → optionally attach a workload for verification.

## 5. Copy guidelines

(Numbers below are illustrative phrasing examples, not results.)

- Say what we know and how: "Observed: Seq Scan on `orders` reads ~4.9M rows (plan node 3)."
- Never "This will make your query 10× faster." Instead: "In the sandbox (`orders_ecommerce`, sf=1), median latency improved 11.2–14.0× (95% CI)."
- Use "Inconclusive" plainly and give the reason.
