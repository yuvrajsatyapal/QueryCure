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
- **Purpose:** resume work, see what needs attention.
- **Counts** (UI Pass 2): Running (`queued` + `running` + `cancelling`), Needs approval (`awaiting_approval`), Completed, Failed, Cancelled. Each comes from `GET /investigations?status=…&limit=100`, which filters on the latest run's status. A count is exact only when the endpoint returns no `next_cursor`; otherwise it reads **"100+"** (or "N+" for a sum that includes a capped status) with a tooltip saying the list endpoint has no total. While anything runs or awaits approval, counts refresh every 10 s.
- **Layout** (UI rebuild Phase 1, prototype Layout 3): page header, then a `1.75fr / 1fr` row of *Active investigations* and *Run outcomes*, then *Recent investigations* (8 newest, a table: outcome pill, title, mode, run, updated), then the status counts above as a strip.
- **Active investigations:** investigations whose latest run is in flight, from the shared recent list (`GET /investigations?limit=25`), ordered awaiting approval → running → cancelling → queued, newest first within a status. An approval row shows the pending approval's round, candidate count and expiry (`GET /runs/{id}/approvals`) and the one primary action, *Review candidates*. A running row shows LLM and tool calls against the run budget (`GET /runs/{id}`, `usage` / `budget`, polled every 10 s); no current-step or progress estimate (the list carries no events). A footer counts runs concluded in the 24 h before the list was fetched. With nothing in flight, the panel holds the Get started links.
- **Run outcomes:** the latest run of each of the 25 recent investigations, counted by `RunOutcome` (plus failed and cancelled; in-flight runs excluded) as a stacked bar and a legend with icons and words, and the median wall-clock time (`started_at` → `finished_at`) of the completed ones with its n. Candidate verdicts and speedups are not on the dashboard: they need per-run verification records.
- **Empty:** "Nothing in flight" with Get started links; "Nothing investigated yet" + Start an investigation in the recent table.
- **Error:** the API error notice, and each panel says it is unavailable rather than showing an empty state.

### 3.3 Database connections (`/app/connections`)
- **Purpose:** register restricted read-only connections and see what each one can do.
- **Layout** (UI Pass 2, settings-section pattern, DESIGN_SYSTEM §5 "SettingsSection"): page header with "Add connection". Connections list as rows: name, `user@host:port/db` (mono), environment tag, TLS mode, last-test status pill (Never tested / Test passed / Test failed / Role refused, words + icon, with the test time), actions Test and Delete (two-step confirm). The test result's capability checklist expands under its row.
- **Add connection:** sections, each with a label and one-line description on the left and controls on the right: *Read-only role* first (the SQL snippet, open by default, since the role must exist before credentials can be entered), then *Identity* (name, environment), *Server* (host, port, database, TLS), *Credentials* (username, password; stored encrypted, never shown again). Field labels and validation messages are unchanged. Capability refusals (superuser, CREATEROLE) read ✕ in `--rejected`; limitations ! in `--inconclusive`.
- **Validation:** host blocked by SSRF guard → the API's message inline. **Public demo:** feature-disabled explanation.

### 3.4 Investigation workspace (`/app/investigations/[id]`) — primary interface
Three resizable panels:

| Left (context) | Center (results) | Right (agents) |
|---|---|---|
| SQL editor (CodeMirror, PG dialect), param sets editor, mode selector (A/B/C toggles with availability), connection or workload picker, schema browser (tables → columns, indexes, stats) | Tabs: **Plan** (graph/tree + node details) · **Findings** (hypotheses with evidence) · **Tournament** · **Report** | Live timeline (agent/tool events), budget meter (LLM calls, tokens, time), approval card when pending, run controls (Start, Cancel, Re-run) |

- **Draft state:** editor active, "Start investigation" primary; plan tab shows uploaded/EXPLAIN plan if available.
- **Running:** editor read-only (shows the exact query being investigated); timeline streams; findings appear incrementally with ClaimBadges.
- **Findings tab:** hypotheses list sorted by confidence; each shows statement, ClaimBadge, supporting/contradicting EvidenceChips, verification method, linked candidates. Clicking an EvidenceChip highlights the plan node in the Plan tab.
- **Keyboard:** see §3.15 (palette and shortcuts, UI Pass 3).
- **Mobile:** tabs Query · Plan · Agents · Results; approval card full-screen modal.

### 3.5 Execution-plan explorer (`/plan-explorer`, also embedded)
Implemented embedded (Plan tab, New investigation preview); controls, flags and full-width view in §3.16.
- **Graph view (React Flow):** top-down tree laid out with dagre; node = PlanNode component; edge thickness ∝ actual (or estimated) rows on a log scale; hottest node by self time gets the accent border.
- **Tree-table view:** indented rows with columns: node, relation, est rows, actual rows, error ratio, self time %, buffers hit/read, loops. Default on mobile and for screen readers.
- **Node detail drawer:** all raw fields, derived metrics, linked evidence/findings.
- **Diff mode:** two plans side by side; nodes matched structurally; changed node types highlighted, metric deltas shown; summary "Seq Scan → Index Scan on orders; Sort removed".
- **Empty:** "No plan yet — paste EXPLAIN (FORMAT JSON) output or run an investigation."

### 3.6 Investigation page: split trace, evidence navigation, header

Implemented as a LangSmith-style **split trace** ([ADR-0030](../engineering/adr/ADR-0030-linear-langsmith-ui-direction.md); DESIGN_SYSTEM §5 "Trace"). Frontend only: everything shown comes from run events and existing endpoints; nothing is inferred or filled in.

**Header (sticky).** Breadcrumb, title, run status pill, run selector menu (§3.6c) with the selected sealed run's report link beside it, compact usage meters (LLM calls, tokens, tool calls against the run budget, from `GET /runs/{id}`), model, Replay / Cancel. The **model line** (`lib/investigation/model.ts`, replay-header correction 2026-10-27) says only what the run records: a recorded model as `<model> via <provider>`; an experiment replay without one *No model calls · Sandbox replay* (it re-measures in the sandbox and never calls a model, REPLAY_ENGINE §8.2); a finished run (completed, failed, cancelled) without one *No model used*; an unfinished run without one *Model not assigned yet*. Sticks to the top of the viewport with an opaque background and a bottom hairline; content scrolls beneath it and never under it (the trace column offsets by the header height). The objective and notices sit below the sticky part.

**Split layout.** Left: the step tree (region "Agent timeline"). Right: details of the selection (region "Selection details").
- The tree's first row is the **run**. Selecting it (the default) shows the run results tabs: Findings · Plan · Tournament · Report.
- Selecting any other row shows **step details** with tabs:
  - **Input:** what started the step as recorded in its start event (node, agent, attempt; tool name and calling agent). Prompts are not recorded (only a prompt version, server-side). Tool arguments are stored redacted on the server and not exposed to the browser. Each gap is stated, never filled in.
  - **Output:** what the step recorded: status, latency, evidence produced, and the log events nested under it (findings, hypotheses, summaries, candidates, verdicts, errors). Raw model output is stored server-side as an artifact and not exposed here. For a log event, its recorded payload fields.
  - **Metadata:** span kind, id, agent, status, start/end, latency, attempt, event sequence numbers, raw events (collapsed).
  - **Evidence:** every evidence ID the step recorded, each resolved on demand to kind, summary and provenance; plan-node evidence offers "Show in plan". Unresolvable IDs say so.
  - "Back to run results" returns to the run row.
- Below 1280px the tree stacks above the details.
- **Tree list containment (sidebar-height fix, 2026-10-27; implemented and visually approved).** The tree's scrolling list is `position: relative`. Rows whose step is not *done* carry an `sr-only` status word (`(running)`, `(failed)`, …), which is absolutely positioned; with an unpositioned list its containing block was the page, so the word escaped the list's scroll clip at its in-list position and stretched the document. With a live run at 1440×900 the document was 1358 px against a 1088 px app shell, so the sticky sidebar scrolled up and left a 270 px blank band. The waterfall marks were not the cause (they are contained by their own `relative` bar cell). The same applies to any completed run with a failed, warning or unfinished step low in the list. Regression: `e2e/trace-layout.spec.ts`.
- Parallel analysts are sibling steps under the run, as emitted; no lanes are drawn.
- **Experiment replay empty state (final UI polish, 2026-10-31).** An experiment replay re-measures one experiment without rerunning the agents, so its graph has no reached step and it has no findings; its trace holds only run, replay and benchmark lifecycle events. For `experiment_replay` runs the view strip says "No agent steps: an experiment replay re-measures the benchmark without rerunning the agents" instead of "0 of 13 graph steps reached"; the Graph view carries a note under its header pointing to the Waterfall for the recorded benchmark events; Findings says the replay has no findings of its own and the original run keeps its findings. No nodes, findings or events are added, and the replay engine and event schema are unchanged.
- **Sidebar footer (final UI polish, 2026-10-31).** The nav keeps its content height (no `min-h-0`) and the desktop sidebar scrolls (`overflow-y-auto`, as the mobile drawer already did). Before, on short viewports (e.g. 1024×360, 320×360) the nav shrank below its content and Connections, Demo gallery and Settings painted over the account footer, and Settings could not be reached. Separately, Next's development indicator (fixed bottom-left, dev only, absent from production builds) covered the sign-in links. `devIndicators: false` in `next.config.ts` hides the badge (every corner covers a control: bottom-right covers the approval drawer's Close); errors still open the dev overlay; no production CSS. Regression: `e2e/sidebar-footer.spec.ts` (8 sizes × both themes, hit-testing every footer control, plus keyboard focus).

**Tree keyboard model** (WAI-ARIA tree, roving focus, selection follows focus): ↑/↓ previous/next visible row; → expands, or moves to the first child; ← collapses, or moves to the parent; Home/End first/last row. Clicking a chevron toggles; clicking a row selects. Log rows can be hidden; Collapse/Expand all. Selecting a row inside a collapsed node (from elsewhere) reveals it.

**Evidence navigation** (pure logic in `lib/investigation/links.ts`, unit-tested):
- A finding or hypothesis offers **"Show step"**, which selects the trace row of its `finding.created` / `hypothesis.created` event (matched by key). If no event carries the key (older run, events still loading), the control says "Step not recorded". If several match, it selects the first and says how many.
- Opening evidence that cites a plan node selects that node in the Plan tab (tree view). If the cited plan is not among this run's plans, or the node ID is absent from it, a notice says so and stays on the current view. Evidence that fails to load shows an error with its ID.
- Plan nodes show **"Cited by"**: findings and hypotheses whose evidence resolves to that node, and the tree table shows a citation count per node. Evidence is resolved per ID through `GET /runs/{id}/evidence/{evidence_id}` (immutable, cached); while resolving, the count reads as pending; failures are counted and reported, not hidden.

#### 3.6a Investigation workspace (UI rebuild Phase 2, 2026-10-24)

Supersedes the layout above where they differ; evidence navigation and the results tabs are unchanged.

- **Header:** breadcrumb, title, run status, and an **activity line** in words (`lib/trace/activity.ts`) taken only from the run status and recorded events (open node, latest `benchmark.progress`, pending approval). The orb moves only while the run is running, the stream is live and a step is open; reconnecting and a dropped stream are said in words (rules in §3.6b). Below it a figures strip: duration from the run's own timestamps, LLM calls / tokens / tool calls against budget, evidence and error counts from events. On an **experiment replay** that recorded no model usage, *LLM calls* and *Tokens* read *Not used* (title *Experiment replays make no model calls*) instead of meters against the model budget, since a replay never calls a model (REPLAY_ENGINE §8.2); recorded usage on any run is always shown as a meter, and tool calls stay metered (`RunStats`, replay usage meters 2026-10-27, visually approved). Known inconsistency, not fixed: a replay whose own re-measurement verifies its candidate is sealed with outcome `verified_recommendation` but an empty `recommendation`, so the result card reads *Verified recommendation* above *No recommendation was verified.* (backend `report-builder@1`; see CURRENT_PHASE).
- **View switch:** Waterfall · Graph · Results. Results shows the results tabs full width.
- **Result summary** (`ResultSummary`): outcome, headline, verdict, candidate and primary interval, and every provenance note (sandbox only, prerecorded, stub model, partial), always shown and compact; the limitations and the verdict explanation sit behind a labelled disclosure ("Limitations (n)"), remembered per browser. The full text stays in the Report tab.
- **Waterfall** (`TraceTree`, `lib/trace/waterfall.ts`): the WAI-ARIA tree with a shared time axis, round-step ticks and zoom (1–16×, centred on the selection). Axis labels are laid out by their width and never overlap.
- **Compressed time** (opt-in): offered only when an approval wait (`approval.requested` → `approval.decided`, or to now while pending) takes at least a quarter of the run. **Linear** is the default. Compressed, each such wait is drawn at 6% of the axis as a dashed break labelled with its real length (`≈ 9h 13m`); no tick falls inside a break, a note says distances across a break are not elapsed time (in one line on narrow panes: *Not to scale across ≈ breaks*), and the legend names the break. The Time column always shows real durations. Zoom works on the drawn axis. Bars come from recorded timestamps only: node spans, tool calls laid over their agent node, and the approval wait (`approval.requested` → `approval.decided`) hatched. LLM calls emit no event, so **no model-call segments are drawn**; an agent node is one bar. A step a finished run left open is drawn as "no end recorded". An approval interrupt closes the gate's first execution at the decision; the resumed gate is its own row ("resumed").
- **Graph** (`TraceGraph`, `lib/trace/graph.ts`): three columns (about 640 px) so it draws near 1:1 beside the inspector; `write_report` sits on the bottom row and exits reach it down a right-hand bus, never behind another node (tested). Fit scales to the pane's width and height between 85% and 115%; below 85% the canvas scrolls. The panel is no taller than the drawn graph. Pan by scrolling or dragging the background; zoom keeps the view centred. Node names are 12px mono and never clipped (tested); the full name and state are in each node's accessible name and tooltip. A **Selected node** strip under the canvas (a status region, not scaled with the canvas) shows the selected node's full name, state and recorded details at any zoom; on touch screens it also says *Drag to explore* while the canvas overflows, until it is first scrolled. The compiled LangGraph topology from `lib/trace/langgraph-topology.json`, kept identical to `compile_graph()` by `backend/tests/unit/agents/test_graph_topology_contract.py`. Node state and taken edges are derived from recorded node spans (fan-out steps grouped by overlap); a node without events is "not reached", never "skipped". Stop exits to `write_report` are hidden unless taken or asked for. Nodes are buttons in reading order with arrow-key movement.
- **Inspector:** the selected step's Input · Output · Metadata · Evidence (unchanged rules: prompts, tool arguments and raw output are named as unavailable), with an execution switcher for nodes that ran more than once and the recorded approval wait. The run row shows the results tabs. A separator between trace and inspector resizes it (pointer or arrow keys); its default is 38% of the workspace (340–640 px).
- **Context menu:** right-click, Shift+F10, the context-menu key or the inspector's Actions button: Inspect, Show in graph / waterfall, copy step name or event seqs, back to the run. "Show in graph" / "Show in waterfall" move focus to the node or row in the other view.
- **Width:** the split needs 900px of the workspace's own width (so it follows the collapsed or expanded sidebar). Narrower, the trace stacks above the results and a row's details open in a modal **bottom sheet** on click/Enter (arrow keys only move the selection). The sheet has one header row: step name, Actions, and a single Close (focused on open; Esc closes and focus returns to the row).

#### 3.6b Status orb and activity indicators (UI rebuild Phase 4, Workstream 4 Stage 1, 2026-10-26)

One rule for every status indicator: **motion means confirmed live activity, nothing else.** A status that is merely *running* in some record is drawn still.

| What the page knows | Example | Indicator |
|---|---|---|
| **Recorded status** — stored on a finished or historical run | History rows, completed run header, demo gallery | Still, always |
| **Polled status** — a snapshot refreshed on an interval | Sidebar *Active runs*, dashboard count tiles and in-flight rows, History list | Still, always, including `running`. Polling proves the status was true at the last poll, not that work is happening now |
| **Confirmed live stream** — the run's SSE stream is open (`StreamState` `live`) | Investigation page while connected | Necessary but not enough: a live stream with no open step (between steps, waiting on approval) stays still |
| **Actively executing operation** — live stream **and** an open span (`node.started` / `tool.started` with no end) on a `running` run | The header activity orb; each open trace row (glyph, waterfall stripe); the graph's running node | The only state that moves |
| **Reduced motion** (`prefers-reduced-motion: reduce`) | Any of the above | Still. The words (*Measuring · block 3 of 12*, *Live*, *running*) carry the state |

- **`StatusOrb`** (`components/ui/StatusPill.tsx`): `tone`, `live`, `size`, `label`. Still by default; it moves only with `live` **and** tone `running` **and** a size of at least 12 px (below that the dot texture has too little ink, so a small orb is a plain dot). Terminal, approval, warning and neutral tones never move whatever `live` says. A `label` makes it `role="img"` with that name; otherwise it is decorative and the visible word names the state. The DOM says `data-motion="live"` or `"still"`.
- **`StatusIcon` / `StatusPill` / `RunStatusPill`**: `running` is drawn as the orb (no spinner anywhere); every other tone keeps its own icon shape, so color is never the only signal. Both take `live` (default `false`); `RunStatusPill` is always still — it names the recorded status beside the activity line, which is the header's one live indicator.
- **Investigation header:** the activity orb follows `activityOf().animate` (running status, `live` stream, an open step). Reconnecting shows a still neutral dot and *Reconnecting…*; a dropped stream shows *Live updates stopped* (warning). The status pill keeps the backend's status (*Running*), so a disconnected run never reads as completed.
- **Trace:** open spans move only while the stream is live; closed spans, recorded traces (open spans become *did not finish*) and the legend swatch are still. The toolbar's *Live* dot is still: it states the connection, not activity.
- **Sidebar, History, Dashboard:** still in every state.
- **Busy buttons** (e.g. the approval drawer's submit spinner) are request feedback for the user's own click, not run status; they keep `motion-reduce:animate-none`.

#### 3.6c Run selector (UI rebuild Phase 4, Workstream 4 Stage 2, 2026-10-27; implemented, visually approved)

The header's run switcher (`components/investigation/RunSelector.tsx`, menu content and run helpers in `RunPicker.tsx`). Reference: Component Kit artboard *Run selector menu* (its *This investigation / Replays* tabs replaced by labelled groups, owner decision).

- **Trigger:** a menu button (`aria-haspopup="menu"`, `aria-expanded`) reading `run 2 · Experiment replay of run #1 of 3`. A single run is a plain label; no runs, nothing.
- **Groups**, both visible together, each newest first, a group shown only when it has runs:
  - **Investigation runs** — the original run and AI re-investigations (and any kind that is not an experiment replay);
  - **Experiment replays** — runs of kind `experiment_replay`.
  Report replays are not runs and never appear. Grouping reads only the run's `kind`.
- **Row:** a still `StatusOrb` in the recorded status's tone; `#N`, kind and relation (`runRelation`: *of run #1*, or *of a run that is no longer available* when the parent is not listed); the status word (`runStatusMeta`), outcome and replay result in words; *followed by #2 (experiment replay), …* for runs with children; the age from `created_at` (`timeAgo`, full date in the `title`). Nothing is inferred: no parent, replay status or timestamp is invented.
- **Selected run:** `aria-checked="true"`, the accent tint and a check icon, so it never rests on color alone.
- **Motion:** the menu fades and lifts 4 px over 160 ms on open (the sheet rises 12 px over 200 ms), once, no overshoot; nothing under reduced motion. The orbs never move: the selector has only recorded statuses (§3.6b).
- **Layout:** fixed-position popover, portaled to `body` so the sticky header's backdrop filter cannot clip or re-anchor it; up to 416 px wide, clamped 8 px inside the viewport; opens below the trigger, or above when the space below is under 240 px and the space above is larger; the height is capped by the space available and the list scrolls inside (`overscroll-contain`). It follows the trigger on scroll and resize. Below 480 px it is a sheet pinned 8 px from the bottom and sides (up to 70 dvh) over a scrim, and the page behind does not scroll. Rows are compact on desktop and at least 44 px on coarse pointers; long relations wrap, and so does a long trigger label (the trigger overrides the button's `nowrap`).
- **Keyboard (WAI-ARIA menu button with `menuitemradio` rows in labelled `group`s):** Enter, Space or ArrowDown/ArrowUp on the trigger open the menu and focus the selected run (or the first); ArrowUp/ArrowDown move with wrapping across both groups; Home/End go to the first/last run; Enter or Space choose the focused run; Escape closes and returns focus to the trigger; Tab closes, returns focus to the trigger and lets the browser move on (no focus trap). A click or tap outside closes. Only the selected row is a tab stop (roving tabindex, which also keeps a scrolling list keyboard-reachable); the focus ring is drawn inside the row so the scroll box cannot clip it. Choosing a run calls the investigation page's existing `selectRun` (URL `?run=`), so the command palette's run scope follows it.
- **Report link:** *This run's report* (accessible name *Open this run's report*) sits beside the trigger, outside the menu, under the same rule as before: the selected run is sealed (`finalized`) and the investigation has more than one run.

### 3.7 Optimization tournament (tab)
Charts, verdict classes, warnings and replicate selection: §3.17.
- Table: candidate (kind icon, short SQL), addresses (hypothesis links), VerdictPill, speedup median + SpeedupBar (CI), regression check per param set, index size, build time, write overhead (or "unmeasured").
- Winner row has the accent left border (only one); rejected rows show reason codes.
- Round selector when multiple rounds occurred.
- **Empty:** "No candidates benchmarked" with reason (Mode C unavailable / approvals declined / not needed).

### 3.8 Benchmark comparison (drill-down from a tournament row)
Distribution chart and stats table as implemented: §3.17. Correctness panel as implemented: §3.18.
- Latency distribution chart per arm (dot strip + box), per param set tabs.
- Stats table: n, median, p95 (or n/a), CV, min/max, bootstrap CI.
- Correctness panel: fingerprints, row counts, order mode (ordered/multiset), outcome.
- Environment panel: PG version, settings, workload id, hardware, provenance badge (`measured` / `prerecorded`).
- Plan diff link.

### 3.9 Investigation history (`/app/history`)
- **Filters, all server-side** (UI Pass 2): title search, latest-run **status**, latest-run **outcome** (`verified_recommendation`, `unverified_recommendations`, `no_action_needed`, `inconclusive`), with a "Clear filters" action and a result line ("12 shown · more available").
- **Grouping:** rows grouped by creation day in local time: Today · Yesterday · Earlier this week · Earlier (the last group shows month headings: "October 2026").
- **Sorting:** newest first, the endpoint's only order; the page says so instead of offering a sort control that would reorder only the loaded page.
- **Mode filter: not offered.** The list endpoint has no mode parameter, and filtering client-side would silently miss unloaded pages. Mode tags stay on each row.
- Row actions: open, delete (soft, with Undo). No bulk actions.

### 3.10 Reproducibility & replay (`/app/replay/[runId]`)
- Manifest viewer: inputs with hashes (copy), environment, models/prompt versions, event count/digest.
- Actions: **Verify & replay report** (per-check ✓/✗ with failure codes; success copy is exactly "Integrity check passed against stored digests", never "tamper-proof"), **Re-run experiment** (confirmation dialog shows the exact DDL; if not replayable, show the reason code in words), **Re-investigate** (Post-MVP).
- Replay attempt history with status badges (`verified`, `verified_stored_only`, `integrity_failed`, `reproduced`, `reproduced_with_drift`, `not_reproduced`, `inconclusive`, …).
- Comparison view for experiment replay: per pair original vs replay verdicts, speedup drift with CI against the equivalence band, absolute latencies side by side (labeled not used for classification), environment diff (all differing fields, including minor ones). Labels follow `comparison_mode`: same-environment results say "Reproduced / Not reproduced"; cross-environment results say "Consistent across environments / Conclusion differs across environments" under a banner, and never use the word "reproduced".
- Reports in an unsupported schema version display the stored Markdown with an "archived format" banner.

### 3.11 Reports (`/app/reports/[runId]`, Report tab, demo detail)
The sealed report JSON is rendered as stored: no section content is recomputed, reworded or dropped (exports and the frozen Markdown renderer are untouched). UI Pass 2 changes presentation only:
- **Page chrome (standalone page):** breadcrumb Investigations › investigation title (from the report) › Report; actions: Export Markdown, Export JSON, Verify report.
- **Replay navigation bar:** Open the run (`/app/investigations/{investigationId}?run={runId}`) · Reproducibility & replay (`/app/replay/{runId}`) · when the report has `replay.replayOf.runId`, "Original run's report" · when `run.parentRunId`, "Parent run".
- **Reading layout:** article ≤ 46rem; on ≥ 1024px a sticky **table of contents** lists the sections the report actually contains (numbered, same order as the article) and highlights the one in view. In the investigation's Report tab the contents list is omitted (the column is narrow).
- **Evidence hierarchy:** the header is a verdict block (outcome, headline, recommendation verdict badge, and the primary measurement when one exists, with its provenance). Notices (sandbox only, prerecorded, stub model, partial) are icon callouts, each in its meaning's color. AI-written text sits in a distinct block (left rule in `--hypothesis`, "AI-written" label); measured values keep their provenance chip and "Why?" link.
- Print: the contents list and action bars are hidden.
- **Technical details disclosure (final UI polish, 2026-10-31).** Identifiers and digests that support a claim sit in a native `<details>` disclosure, collapsed by default and labelled with its contents ("Source details · 8 IDs and digests"): a replay's source run, experiment, stored outcome, sealing builder, manifest, report JSON, replayed result and classification basis; a round's *Experiment details* (full experiment ID, result digest, environment, sandbox image and workload digests, previously only an 8-character prefix); and, above the article, *Report integrity* (full manifest, report JSON and Markdown digests and the sealing versions, previously a 16-character manifest prefix). Values are rendered complete (wrapped, never truncated) and stay in the DOM when collapsed; each has a *Copy {label}* button that copies the full value and announces "Copied {label}" in a polite status region. Outcome, comparison verdict, recommendation provenance, candidate and verification scope stay outside the disclosure. Every disclosure opens on `beforeprint`. Presentation only: sealed JSON/Markdown, digests, manifests, builders and exports are unchanged.

### 3.12 Settings (`/app/settings`)
- **Layout** (UI Pass 2, settings-section pattern): *Model key*: the saved key (provider, `…hint`, model, added / last used) with Delete key, or "No key saved" plus what runs will use instead; *Add a key* / *Replace the key*: OpenRouter API key (`type=password`, never echoed) and optional free model; *Appearance*: theme as native radios (Dark, Light, Match system), the same setting as the sidebar toggle, kept in this browser only.
- Copy, validation (free models only), and storage behavior are unchanged.

### 3.13 Demo gallery (`/demo`)
- **Investigation cards** (UI Pass 2): title link, outcome pill (words + icon), headline, the "What this case tests" disclosure, and a footer that always carries **Prerecorded** plus model, recorded date and "measured on …" or "no benchmark". The text of every label, headline and summary is the API's, unchanged.
- **Benchmark cards:** per arm a verdict badge, kind and first reason code, the exact SQL, then a small table per parameter set (baseline median, candidate median, speed-up with 95% interval, n) instead of a sentence list. Numbers are the API's strings, not recomputed. The card's provenance label stays visible.

### 3.14 New investigation (`/app/investigations/new`): guided flow (UI Pass 3)
Frontend only. Same endpoints (`POST /inspect/sql`, `POST /inspect/plan`, `POST /connections/{id}/explain`, `GET /workloads`, `GET /settings/models`, `POST /investigations`), same request body as before Pass 3, so every server-side check (`validate_select`, the mode rules, production-connection refusal, param-set arity, approvals) applies unchanged.

- **Layout:** a four-step wizard on the left; the plan preview (tree / graph, node details) on the right from `xl` up, below it on smaller screens. A step list (`<ol>`, `aria-current="step"`) shows progress. Completed steps can be reopened. Later steps open only once the earlier ones are valid.
- **1 · SQL query:** the CodeMirror editor. **Continue** sends the text to `POST /inspect/sql`, which uses the same validator as creation. On success the step shows the statement type (the API sends it lower-case; it is displayed upper-case), the tables and the parameter count. On failure it shows the API's message and the step stays open. Editing the SQL afterwards marks the check stale, and Review checks again before Start is enabled.
- **2 · Plan source:** *Upload plan* (paste or file, then Analyze), *Live EXPLAIN* (connection, then Run EXPLAIN; plain EXPLAIN only), *Demo workload* (workload, scale and example query; picking one replaces the SQL with the example, and the step says so), or *No plan* (agents work from the SQL text). An upload or live source needs a plan before Continue. A workload needs a workload. Continue stays disabled until the source is ready, with the reason beside it; while the analysis or EXPLAIN is pending it reads *Analyzing plan…* / *Running EXPLAIN…*, and Ctrl/Cmd+Enter does nothing. A failed request shows the API's message and the source button becomes *Retry analysis* / *Retry EXPLAIN*. A plan only counts for the inputs it was made from: editing the plan text, or changing the connection or SQL after EXPLAIN, asks for a new analysis, and a response that arrives after such an edit never makes the step ready.
- **3 · Investigation mode:** three radio cards: Offline, Live inspection and Sandbox benchmark. Only the modes the chosen source supports are enabled. Each disabled card says why, for example "Choose a connection in Plan source". The default is the mode the source implies, which matches the pre-Pass-3 behaviour. The step also holds the objective and the param sets, plus the parameter count from step 1. For sandbox mode it adds the existing approval note and the pre-authorize checkbox, unchanged.
- **4 · Review & start:** a read-only summary of every choice, each with an Edit button. A demo workload shows its full workload id here (`orders_ecommerce@v1:sf=0.01:seed=42`), as the old form did. Then the title, the model line and **Start investigation**. Start keeps the per-form idempotency key.
- **Suggested title:** `suggestTitle(sql)` in `lib/investigations/title.ts` is pure, deterministic code with no LLM and no network call. It strips comments and literals, then builds the title from the tables (CTE names excluded, at most 3, then "+N"), the WHERE columns (at most 2), GROUP BY / aggregate, the first ORDER BY column and LIMIT. Example: `orders · where customer_id · order by created_at · limit 20`. The result is capped at 120 characters. The title field shows it as the placeholder plus a "Suggested:" hint. A blank title submits the suggestion, and anything typed overrides it. No suggestion (SQL that cannot be read) → a title is required, as before.
- **Keyboard:** `⌘/Ctrl+Enter` continues to the next step, or starts on Review. Inside the SQL editor CodeMirror keeps its own `Mod-Enter`, so press `Tab` to leave the editor first. Focus moves to the heading of each newly opened step.
- **States:** pending buttons read "Checking…", "Analyzing…", "Running EXPLAIN…" or "Starting…". The workload and connection selects show a skeleton line while they load. Errors appear through `ErrorNotice` with the API's message.

### 3.15 Command palette and keyboard shortcuts (UI Pass 3)
- **Palette:** `⌘K` (macOS) or `Ctrl+K` opens it from anywhere in `/app`, inputs included. It is a modal `dialog` with a combobox and a listbox (`aria-activedescendant`). Focus is trapped while it is open and returns to the previous element when it closes. `↑/↓` move, `Enter` runs, `Esc` closes.
- **Groups:**
  1. *Actions*: New investigation, Switch to light/dark theme, Keyboard shortcuts.
  2. *Navigate*: Dashboard, History, Connections, Settings, Demo gallery.
  3. *This investigation*, only on an investigation page: Show Findings / Plan / Tournament / Report.
  4. *Investigations*: title search through `GET /investigations?q=…&limit=8`, debounced 200 ms, with a skeleton while loading and a "No matching investigations" line when nothing is found.

  Commands are filtered with a case-insensitive match on the words of their label. Nothing is fabricated: every command is an existing route or action.
- **Shortcuts** (none fire while focus is in an input, textarea, select, contenteditable or CodeMirror, while a modifier other than Shift is held, or while a modal dialog is open):

  | Keys | Action |
  |---|---|
  | `⌘K` / `Ctrl+K` | Command palette (works in inputs) |
  | `?` | Keyboard shortcuts dialog |
  | `c` | New investigation |
  | `g d` · `g h` · `g c` · `g s` | Dashboard · History · Connections · Settings |
  | `[` / `]` | Previous / next result tab (investigation page) |
  | `g f` · `g p` · `g t` · `g r` | Findings · Plan · Tournament · Report tab (investigation page) |
  | `⌘/Ctrl+Enter` | Next step / Start (new investigation, outside the SQL editor) |

  A `g` sequence expires after 1 s. The sidebar shows the `⌘K` hint as a button, which also opens the palette by pointer or touch.
- **Feedback:** after a theme change from the palette, a polite live region announces it ("Dark theme on"). Navigation needs no toast.
- **Run scope (UI rebuild Phase 4, workstream 3, 2026-10-25):** opened on an investigation page, the palette searches the selected run first. A chip in the search row names it (*Run #N*); the chip's button, or Backspace in an empty field, widens the search to everything (the existing palette, unchanged), and *Search Run #N only* returns to the run. Each change is announced ("Searching everywhere"). Focus restore, the focus trap and every existing shortcut are unchanged; no new single-key shortcut.
  - **Groups**, before the commands (then *This investigation*, *Actions*, *Navigate*, so the run's own commands lead and the general ones never crowd the results): *Findings* (severity · agent), *Hypotheses* (rank · confidence · unverified), *Candidates* (the recorded candidate status in words; never a speed-up figure), *Plan diffs* (arms with a plan captured in the latest round), *Evidence* (every ID cited by a finding or hypothesis). Matching uses the label plus keys, evidence IDs, categories and statuses. Five per group until the user types, ten after; the rest is counted ("2 more · type to narrow").
  - **Data:** only what the page already loads, keyed by run (`lib/command/runScope.ts`). Evidence is not prefetched: cached details show their summary; otherwise the ID says *Details load when opened* or *Details unavailable* (a failed fetch). The latest round's experiment detail (for the plan-diff list) is fetched once, only while the palette is open, and shared with the Tournament tab's cache.
  - **Run changes:** the scope is replaced with the run. A run still loading shows *Loading Run #N*, never the previous run's results; items stamped with another run are dropped. A failed findings or candidates fetch is stated, not shown as "nothing". Empty: *Nothing in Run #N matches.*, with one option under *Outside this run*, *Search all investigations for “…”*: it is active, so Enter leaves the scope keeping the query (announced like the chip; Backspace and the chip are unchanged).
  - **Selecting:** a finding or hypothesis opens Findings and focuses it; evidence opens like an evidence chip (Plan tab for plan nodes, otherwise the Evidence tab with the record); a candidate opens Tournament on it and focuses the tab; a plan diff opens Tournament, selects the candidate, opens the *Execution-plan differences* section if it is folded (phones), and focuses the candidate picker, or the *Plan diff · baseline → …* heading when there is only one candidate (`focusSection`). The heading's focus ring is flush (`data-focus-flush`) with a gap below, so it never covers the description; chosen by pointer, the target is focused without a ring (`data-pointer-focus`, removed on blur), chosen by keyboard it keeps the ring.
  - **Phones:** an option's detail stacks under its label below 640 px, so neither is cut to a few characters.
  - **Same titles (global search):** investigations whose titles repeat show their recorded creation time after the status (*Completed · Oct 25, 7:30 PM*), plus the first 8 characters of the ID when the minute repeats too; from the list response only (`lib/command/titles.ts`). The status may truncate; the time and ID never do.
  - **Keyboard:** arrows wrap; the active option is kept in view (the first one also brings back its heading); a mousemove the browser replays at the same point after scrolling does not move the selection; Enter runs exactly the highlighted option; changing scope resets to the first option.

### 3.16 Execution-plan viewer (UI Pass 4)

Frontend only. Input is the existing `GET /runs/{id}/plans` (`PlanTree` + backend `NodeMetrics`, `plans/metrics.py`); no contract change. Derived display logic is pure and unit-tested in `lib/plan/analysis.ts`.

- **Structure:** the tree is the parsed plan's own parent → child structure (`PlanNode.children`, `parent_id`), including subplans and InitPlans with their `parent_relationship` / `subplan_name`. Nothing is re-ordered or merged.
- **Columns (tree-table):** node (type, relation/index, relationship), est. rows / loop, actual rows / loop, loops, estimate error, est. cost (startup..total), actual time / loop (ms), self time (ms · share), buffers read / hit. Every missing value is "—"; never zero.
- **Expensive nodes** (only when the plan has timing): *hottest* = the single node with the largest backend self time (unchanged); *expensive* = self time ≥ 20% of the root's inclusive time (`self_time_share` ≥ 0.20). Plain EXPLAIN plans flag no node: the planner's cumulative cost is shown as a bar labelled "est. cost, cumulative", because self cost cannot be derived reliably (Limit, Nested Loop inner rescans).
- **Row-estimation errors** use the backend ratio `max(actual, est) / max(min(actual, est), 1)` per loop, with its direction. Shown as *significant* at ≥ 10× and *severe* at ≥ 100×, except: a node that never executed (`actual_loops = 0`) reads "never executed" and is not flagged; an error whose larger side, summed over all loops, is under 100 rows is shown but not flagged ("small rows"); fewer actual rows than estimated on a node that a `Limit` above can stop early is shown with "LIMIT above" and not flagged (the walk up to the `Limit` stops at a node that reads its whole input: Sort, Hash, or a non-sorted Aggregate). Under-estimates (more rows than expected) are still flagged there; early stops from semi/anti joins and `EXISTS` subplans are not detected. These are display thresholds only; no verdict reads them.
- **Interaction:** expand/collapse per row, Expand all / Collapse all, Jump to hottest, a summary line (nodes, planning and execution time, analyzed/buffers, flagged counts), and a legend that states the thresholds. Treegrid keys as before (↑/↓, ←/→, Home/End, Enter/Space selects). No single-letter keys inside the tree, because `c` and `g …` are global shortcuts (§3.15).
- **Full width:** a "Full width" button opens the same viewer (tree or graph plus node details) in a modal dialog over the page; Esc or Close returns focus to the button.
- **Selection:** selecting a node from evidence, the report or the URL reveals it (its collapsed ancestors expand) and scrolls it into view. Pass 1 navigation (trace ↔ evidence ↔ plan node, Cited by) is unchanged.
- **Node details:** adds startup/total cost, actual startup/total time per loop, workers planned/launched, shared/temp buffers, and the estimate explanation in words ("planner expected 120 rows per loop, 4,812 returned: 40× under").

### 3.17 Benchmark analytics (UI Pass 4)

Frontend only. Input is `GET /experiments/{id}` (`ExperimentResult` measurements, stats, verdicts, replication, transport floor, noise screens) plus `GET /runs/{id}/verifications`; no contract or algorithm change. Pure logic in `lib/benchmark/analysis.ts`, unit-tested.

- **Attribution (claims@2):** every chart, row and figure names its experiment (short ID, round, replicate), candidate arm and param set. Samples are never pooled across param sets, arms or experiments. Replicates are separate experiments, chosen with an experiment selector inside a round; the replication range is shown as the backend reports it, labelled "range across N experiments", never as one pooled CI.
- **Timing distributions:** per param set, one row per arm (baseline first) on a shared log-scale axis: every recorded sample as a dot (`ArmMeasurement.latencies_ns`) and a box (Q1–Q3, recomputed from the same samples with the engine's inclusive quartile method) with the backend median. Failed samples are counted in words, never plotted. When the transport floor was recorded, a dashed line marks its median ("SELECT 1 round trip").
- **Speedup and CI:** a forest plot, one row per candidate × param set, point = `speedup`, whiskers = `ci_low`..`ci_high`, log axis, with a solid **1× no-improvement** line and, when the config records them, dashed `min_effect` and `max_regression` lines. A row is drawn only when a `SpeedupStats` entry exists, its numbers are finite and positive with `ci_low ≤ speedup ≤ ci_high`, and the arm did not fail correctness (`result_mismatch`, `nondeterministic_order`, `result_too_large`): otherwise the row says why it is not shown ("not comparable: results differ from the baseline").
- **Verdicts** (from the backend, never inferred): *Verified*; *Verified · noise warning* (replication); *Disputed* = the Benchmark Auditor downgraded the engine verdict (`auditor_downgraded`; the backend has no separate "disputed" verdict); *Rejected*; *Inconclusive*; *Unverified* = no measured verdict (declined, expired, proposed, approved, or absent from the experiment). Precedence: an auditor downgrade, then the replication verdict, then the audited verdict, then the engine verdict, then the candidate status. A summary strip counts each class; badges keep icon + words.
- **Warnings** (only when recorded): transport floor share of the fastest arm (≥ 50% = transport-dominated, ADR-0029); robust CV above `max_cv`; noise screens; failed samples and sample errors; p95 unavailable (n < 20); prerecorded provenance. Host contention is **not recorded** by `bench@2`; the panel says so instead of guessing. Older results without a transport floor say "not recorded".
- **Data table:** the stats table (n, median, p95, IQR, robust CV, min–max, failures, speedup with CI or the reason it is absent) is always shown; each distribution has a collapsed "Recorded samples" table with every sample value.
- **Unavailable data:** an experiment without a result, or a param set without measurements, says so in place of the chart.

### 3.18 Final polish: result summary, candidate descriptions, statistics glossary, correctness panel

Frontend only; spec and audit in [FINAL_UI_POLISH](../reports/FINAL_UI_POLISH_2026-10-23.md). No contract change.

- **Result summary** (investigation page, above the trace): shown only for a finished run with a sealed report in a supported schema (`GET /runs/{id}/report`, same query as the Report tab). Order: outcome and deterministic headline → recommendation verdict badge, candidate description and key, primary speedup with 95% CI, n and provenance → `VERDICT_EXPLANATION` (verified only) → callouts (sandbox only, prerecorded, stub model, partial) → **every** recorded limitation → "Full report" / "Benchmark details". Without a verified recommendation it says "No recommendation was verified" and points to the per-candidate verdicts. The AI-written summary stays in the Report tab.
- **Candidate descriptions:** `describeCandidate` (`lib/benchmark/candidate.ts`) parses only the three allowlisted DDL forms ("Composite index on orders (customer_id, created_at)", "… · hash", "· includes x", "· partial", "Extended statistics on t (a, b) · dependencies", "Refresh planner statistics on t", "Query rewrite"); anything else gets the generic kind label. No model. The key stays beside it in mono. Used in the approval card, tournament ranking, comparison heading, verdict list, report rounds and the result summary.
- **Statistics glossary:** "How to read these numbers" (`<details>`, closed) in the Tournament tab: speedup, 95% CI, IQR, robust CV, transport floor, p95, and "Faster is not the same as verified" with the full list of conditions.
- **Correctness panel** (benchmark comparison of the selected candidate, `lib/benchmark/correctness.ts`): the outcome comes from the rule verdict's gate (gate 3 is correctness): *same rows on every param set* (gate `null` or ≥ 4), *results differ* / *could not be decided* (gate 3, with reason words and the recorded detail; only the first failing param set is recorded), *not checked* (gate 1–2 or no verdict). Then the order rule from `order_is_total`, and per param set: rows (baseline / candidate), same rows (row count + multiset hash, the backend's `correctness_check` definition), same order (ordered hash), repeatability (`consistent`) per arm, hash-cap truncation, short row hashes (full hash in the accessible name). A missing fingerprint reads "unknown · no successful execution". The panel states that same rows on the tested data is not SQL equivalence.

### 3.19 Evidence relationships and benchmark studio (UI rebuild Phase 3, 2026-10-24)

**Evidence tab** (`EvidenceExplorer`, `lib/evidence/graph.ts`, TDD). A results tab between Findings and Plan (`g e`).
- Five columns, read left to right: Evidence → Finding → Hypothesis → Candidate → Verdict. It is not a force graph.
- **Recorded links** come only from stored references, and each names its field: `finding.evidence_ids`, `hypothesis.supporting_evidence`, `hypothesis.contradicting_evidence` (drawn in the rejected colour), `candidate.addresses_hypotheses`, `verification.candidate_key`, and the Benchmark Auditor's check and concern `evidence_ids`.
- **Inferred links:** only finding → hypothesis, because the backend stores none. It is drawn when both cite the same *supporting* evidence. It is dotted, in the hypothesis colour, labelled "inferred" and lists the shared IDs. A shared contradicting citation is not a link.
- Every cited evidence ID is a card. Each is resolved through `GET /runs/{id}/evidence/{eid}`, and its state is shown as resolved, loading or "could not be loaded". References to records the run does not return are listed in a note, never dropped.
- Links that skip a column run down the gutter, along a lane under the cards (one lane per target) and up into the target. They never pass behind an intermediate card.
- **Selected path** (the default) highlights the selection's upstream and downstream chain. Every other record and link stays listed and selectable, drawn quieter (cards at 55% opacity, links faint) and named "not on the selected path"; highlighting never changes a link's class or style, so it is not stronger evidence. **Everything** draws all records alike.
- The first selection explains the recommendation (`explainingSelection`): the verdict that verified a candidate (latest round), else any verdict, else the top-ranked hypothesis.
- Records are ordered within each column to reduce crossings between neighbouring columns (`orderNodes`, barycentre sweeps, keeping the least-crossing order). Only positions change; no record or link is added, removed or merged. Each link ends in a dot at the target's edge.
- **Link inspection:** pointing at a line (a 10 px hit area) shows a tooltip; hovering or focusing a link in the record panel highlights its line and shows the same readout as a status line. Both give source → target, the relationship, the recorded field or the inference basis (shared evidence IDs), and the class: recorded, inferred, or recorded · contradicting. Escape dismisses it.
- **Cards:** a readable type line (e.g. "plan node", "rank 1 · high confidence") with the provenance or status tag, then the description (three lines on the wide graph), then a short ID with a copy button (full ID in its name and tooltip). The accessible name still starts with the full ID. Stacked cards show the full ID and the whole description; descriptions over 110 characters get a separate **Show more** control, so expanding never selects.
- **Selected record** panel:
  - evidence: kind, provenance with its meaning, locator, artifact, data, and the backend's recorded "cited by";
  - candidates: the agent's expected benefit and cost estimates, labelled *predicted · not measured*;
  - verdicts: engine and final verdict, the auditor's status and checks.
- Actions on the panel: Show in plan (plan_node), Show step (the trace rows whose events recorded the ID), Show in Findings, Open in benchmark (selects that arm in the Tournament tab).
- **Keyboard:** roving focus; up and down within a column, left and right to a linked record in the next column.
- Below 880 px of panel width (the split inspector, phones) the columns stack. Each card then lists its incoming links (≈ marks inferred ones, ✕ contradicting ones) and no lines are drawn.

**Benchmark studio** (Tournament tab, prototype "Bench Studio"; supersedes the layout of §3.17, not its rules).
- Header: "Candidate comparison", the experiment attribution, and **Show data tables**. The ranking table, the per-arm statistics table, the result-fingerprint table and the full auditor summaries sit behind it.
- **Arms rail** ("Recommendation verdicts"): the baseline as reference, then the candidates in tournament order. Each shows its backend verdict class, the recorded primary-param-set speedup and CI, and Winner. Selecting a candidate drives the cards.
- **Verdict card:** headline from the verdict class. Under *Measured*: per param set speedup, 95% CI and n, the recorded index build, the correctness outcome and the tested scope (param sets, never pooled). Under *Predicted · not measured*: the agent's expected benefit, estimated index size and write overhead.
- **Measurement notes:** §3.17 warnings (transport floor, CV, failed samples, noise screens, prerecorded, host contention not recorded).
- **Speedup forest:** the selected arm is marked. Log scale over the recorded intervals, 1× and the thresholds, never narrower than 0.12 decades (a 1.32× range): a near-1× cluster is widened around its centre, and the caption says so and prints the axis range. Ticks adapt to the plot width (`lib/benchmark/scale.ts`: the richest of several 1-2-5-style tick sets whose labels stay ≥ 44 px apart; 1× always kept), labels never overlap and edge labels are anchored inside. A header row names "1× no change" (bold) and the thresholds (in their colours) where they fit; the legend always names them. Each interval strip is focusable and shows the exact estimate, interval, n and its side of 1× on hover or focus. Below 42 rem of studio width each row is a header line (candidate and param set left, estimate with interval and n right) over a 24 px strip, with a rule between rows; wider, the same parts are name, strip and value columns. The 1× line is solid ink with a halo so it reads apart from the gridline and the dashed thresholds.
- **Timing distributions:** per param set, every sample at its recorded latency (log scale, minimum 0.1 decades), dodged vertically onto up to five lanes so dots do not overlap (deterministic). Outliers beyond 1.5×IQR are rings, counted and kept. Box Q1–Q3 tinted in the series colour, a bold median with a halo, min–max line, a labelled dashed transport floor. Each arm row is a focusable slider: arrow keys, Home and End step through the samples from fastest to slowest and announce sample number, latency and outlier status; hover shows the same. Below 32 rem the arm row's figures (median · n · outliers) sit on one line beside the name, moving to the next line whole. Under the chart a compact key (median, outliers kept, transport floor with its value) stays visible; the full reading guide (quartiles, whiskers, dodging, outliers, transport floor, log scale, keys) is in a *How to read this chart* disclosure above the *Recorded samples · n …* disclosure, which keeps the table.
- **Correctness and audit gates:**
  - the correctness outcome from fingerprints;
  - the rule verdict and its gate;
  - the transport floor as a note-only gate when it dominates;
  - the Benchmark Auditor's recorded checks and concerns ("it can only downgrade").
- Layout follows container width (`@container/bench`, `/studio`): the rail moves beside the cards at 56 rem, and the distribution sits beside the gates at 56 rem of the main column.
- **Phones (≤ 767 px viewport):** the verdict card, measurement notes and speedup forest stay open. Timing distributions, Correctness and auditor checks, and Execution-plan differences become disclosures with a title and a one-line summary; several can be open. The checks section opens by default, and its summary is flagged, when correctness did not pass or the auditor recorded a warning, failure, concern or downgrade. Wider screens are unchanged.

### 3.20 Plan diff (UI rebuild Phase 4, workstream 1, 2026-10-25)

The studio's *Execution-plan differences* section, from `GET /runs/{id}/plans/diff` on the experiment's post-timing EXPLAIN ANALYZE captures. Frontend only; the diff, its alignment and its metrics are the backend's (`plans/diff.py`).

- **Selection:** *Candidate* (arms with a captured plan; it drives the studio's selection, so the whole studio shows the same arm) and *Parameter set*. A set chosen for another candidate falls back to the new candidate's first set. A missing baseline or candidate capture is stated, never a blank section.
- **Summary cards:** what changed (structural summary and counts); *Benchmark median* from the experiment's own statistics for that candidate and set (the measurement that decides, left out when no statistic was recorded); execution and planning time from the single capture; root cost (planner estimate); shared buffers (hit + read, summed over plan nodes). Every card names its source and carries a *measured* or *estimate* tag.
- **Layouts:** *Side by side* (baseline | change | candidate; one-sided nodes say "not in baseline / candidate") and *Unified* (one list, every figure `baseline → candidate`). Default: side by side, unified on phones; the choice is kept while the section is open. Status is a glyph and a word (`= same`, `~ changed`/`type changed`, `− removed`, `+ added`), never colour alone. Row counts are actual rows when recorded, else the planner estimate marked `~`.
- **Node metrics:** each change marker is a button that opens every metric recorded for that node (baseline, candidate, ratio worded as "lower/higher", source tag) with the changed property names. The diff records which properties differ, not their values, and says so. Close returns focus to the marker.
- **Estimate-only plans:** if either plan lacks EXPLAIN ANALYZE actuals (a plain EXPLAIN, as in Mode B), a note says its rows are planner estimates and no node times were recorded. Mode B runs have no experiment, so they show no plan diff.
- **Layout follows the diff's container** (`@container/diff`): at ≥ 42 rem rows and self time get their own columns; narrower (every current studio layout, 324–606 px) they sit under the node name. Tables scroll inside focusable regions; the page never scrolls sideways.
- Plan digests (sha256, shortened) of both captures are listed under the diff.
- **Refinements (owner review, 2026-10-25):** summary figures are superseded by the metric-card layout below; shared buffers carry "blocks". Node labels clamp to two lines and relation · index truncate to one; the full text stays in the DOM (screen readers), in a tooltip, and in the node metrics panel, which lists the relation and index (baseline → candidate) in full. The node metrics panel shows stacked metric cards (name, provenance tag, baseline, candidate, change) below 28 rem and the table above.
- **Metric cards (owner review, 2026-10-25):** each summary figure (benchmark median, execution time, planning time, root cost, shared buffers) is one card: title with its *measured* / *estimate* tag beside it (wrapping to a second line when narrow), then *Baseline* and *Candidate* as two labelled columns (label above value, monospace tabular numerals, no wrap inside a value), then its source in smaller muted text. When both values cannot sit side by side, the candidate column wraps under the baseline instead of being clipped. Cards grow with their content (no fixed heights or clamps). The card grid is chosen by the diff's own width (`@container/diff`), not the viewport: one full-width card per row below 33 rem, two columns from 33 rem; *What changed* spans the full width, and its index names may break after an underscore. No speed-up or percentage is derived on the cards. Cause of the earlier cramping: a fixed two-column grid gave 123–212 px cards inside the 254–464 px studio panel, clipping values at 320 px.

### 3.21 Approval review drawer (UI rebuild Phase 4, workstream 2, 2026-10-25)

Frontend only; the existing `GET /runs/{id}/approvals`, `GET /runs/{id}/candidates`, findings, and `POST /approvals/{id}/decision`. The inline approval card stays; its *Review details* button opens the drawer.

- **Shell:** right-side drawer (600 px) from 768 px up, accessible bottom sheet (≤ 92 dvh, grab handle) below. Modal: focus moves to the title, Tab stays inside, Esc / scrim / close button dismiss it, focus returns to *Review details* (or to the page heading when the card has gone after a decision). Body scroll is locked.
- **Shared state:** the card and the drawer share one selection and one decision request (`useApprovalDecision`), so a selection made in either shows in both. Semantics unchanged: all selected → `approve`, a subset → `partial` with those ids, *Decline all* → `decline`.
- **Content:** status and countdown; request context (investigation, run, workload, sandbox, parameter sets, requested/expires/decided); the baseline query; per candidate: each statement verbatim from the approval payload with copy, the server's full SQL SHA-256 with copy, *Expected (proposed, not measured)* (expected benefit, write overhead as the proposer's estimate, index size only when recorded), risks as listed by the proposer ("none listed" is not a safety claim), rollback SQL if recorded, *Measured* (nothing before an approved experiment; then a pointer to the Tournament tab), supporting hypotheses with evidence links (closing the drawer and opening the evidence). If the run's candidate record has a different digest from the approval, a warning says so; the approval's SQL and digest are what is shown.
- **Header and request context:** status pill, countdown (never wraps), title, and one truncated line *Round N · investigation* (full text in Request and the title attribute; the sandbox stays in the accessible description). Request metadata is a compact 13 px list.
- **Footer:** the selection count on its own line, then *Decline all* (sized to its label) and *Approve selected* (the rest of the row) on one row below 640 px; one row with the count between them above. Labels never wrap; the footer is outside the scrolling body, so it never covers the last candidate; the sheet pads for the bottom safe-area inset. Checked at 320, 375 and 390 px.
- **States:** pending; recording (both actions disabled, "Recording decision…"); recorded (the drawer stays open with the result); already decided (the server returned an earlier decision); expired (by status, or by the clock while still pending on the server: no decision is offered, in the card too; the clock is re-read at the expiry instant, not only every 15 s); **not recorded** (the server refused the decision with 409, e.g. "This approval request has expired.", while the list still said pending: the decision footer is replaced by *Close* at once, in the card too, the server's message and request id stay in the alert, the expiry time is restated, and the request's status is refetched; once the server's status arrives it is shown as expired or already decided); any other API error (validation, server, network: the envelope message, retry allowed, never shown as a decision).
- **One request at a time:** a decision is sent only while the phase is pending and no request is in flight (checked synchronously, so a double click, Enter then click, or card and drawer together send one request); nothing is sent after an outcome or a refusal.
- **Supporting hypotheses:** linked hypotheses with evidence links when the run's candidate record is loaded; "not loaded" when the record is missing; "No hypothesis is linked to this candidate." when it lists none.
- Nothing is computed client-side: no SQL is generated, reformatted or re-hashed, and no improvement is shown before measurement.

## 4. Key interaction flows

1. **Demo flow (public):** Landing → Open demo → pick `orders_ecommerce` → workspace pre-filled → Start (needs BYOK; prompt to add key or view prerecorded replay) → watch timeline → tournament shows prerecorded benchmark (◆ labeled) → report.
2. **Local verify flow:** New investigation → paste query + param sets → choose workload → Start → approve candidates → tournament → report → export.
3. **Live diagnose flow:** Connections → add + test → New investigation with connection → findings (unverified recommendations if no sandbox) → optionally attach a workload for verification.

## 5. Copy guidelines

(Numbers below are illustrative phrasing examples, not results.)

- Say what we know and how: "Observed: Seq Scan on `orders` reads ~4.9M rows (plan node 3)."
- Never "This will make your query 10× faster." Instead: "In the sandbox (`orders_ecommerce`, sf=1), median latency improved 11.2–14.0× (95% CI)."
- Use "Inconclusive" plainly and give the reason.
