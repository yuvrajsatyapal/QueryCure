import type { RunEvent } from "@/lib/api/types";
import { describe } from "./describe";

/* Folds a run's flat event log into a span tree for the trace view: run → graph nodes →
 * tool calls and log events. Analysts run in parallel, so a tool call joins the open node of
 * its agent rather than simply the latest node. Pure and deterministic: same events, same tree. */

export type SpanKind = "run" | "node" | "tool" | "event";
export type SpanStatus = "running" | "ok" | "error" | "warning" | "approval" | "info" | "unfinished";

export interface Span {
  id: string;
  kind: SpanKind;
  name: string;
  agent: string | null;
  status: SpanStatus;
  startTs: string;
  endTs?: string;
  durationMs?: number;
  events: RunEvent[];
  evidenceIds: string[];
  children: Span[];
}

type Payload = Record<string, unknown>;

const RUN_LEVEL = new Set(["run.status_changed", "run.concluded", "report.ready", "replay.status_changed", "replay.compared"]);
// write_report seals the event log and emits no node.completed; the run's conclusion is its end.
const REPORT_NODE = "write_report";
const CONCLUSION = new Set(["run.concluded", "report.ready"]);

const str = (v: unknown): string | null => (typeof v === "string" && v ? v : null);
const ids = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : []);

function eventStatus(event: RunEvent): SpanStatus {
  const p = event.payload as Payload;
  switch (event.type) {
    case "error":
      return "error";
    case "budget.warning":
      return "warning";
    case "approval.requested":
      return p.status === "pending" ? "approval" : "info";
    case "verification.completed":
      return p.verdict === "rejected" ? "error" : p.verdict === "inconclusive" ? "warning" : "ok";
    case "replay.status_changed":
      return p.to === "failed" ? "error" : "info";
    default:
      return describe(event).tone === "error" ? "error" : "info";
  }
}

function span(kind: SpanKind, name: string, event: RunEvent, agent: string | null, status: SpanStatus): Span {
  return { id: `${kind}:${event.seq}`, kind, name, agent, status, startTs: event.ts, events: [event], evidenceIds: [], children: [] };
}

function close(s: Span, event: RunEvent, durationMs: unknown, status: SpanStatus): void {
  s.endTs = event.ts;
  s.durationMs = typeof durationMs === "number" ? durationMs : Date.parse(event.ts) - Date.parse(s.startTs);
  s.events.push(event);
  // A node that logged an error stays failed even though it completed.
  if (s.status !== "error") s.status = status;
}

export function buildTrace(events: RunEvent[], { active }: { active: boolean }): Span {
  const sorted = [...events].sort((a, b) => a.seq - b.seq);
  const first = sorted[0];
  const root: Span = {
    id: "run",
    kind: "run",
    name: "Run",
    agent: null,
    status: active ? "running" : "ok",
    startTs: first?.ts ?? new Date(0).toISOString(),
    events: [],
    evidenceIds: [],
    children: [],
  };
  const openNodes: Span[] = [];
  const openTools: Span[] = [];
  const latest = <T extends Span>(list: T[], match: (s: T) => boolean) => [...list].reverse().find(match);
  const remove = (list: Span[], s: Span) => list.splice(list.indexOf(s), 1);

  for (const event of sorted) {
    const p = event.payload as Payload;
    const agent = str(p.agent);
    const node = str(p.node);
    switch (event.type) {
      case "node.started": {
        const s = span("node", node ?? "node", event, agent, "running");
        root.children.push(s);
        openNodes.push(s);
        break;
      }
      case "node.completed": {
        const s = latest(openNodes, (n) => n.name === node);
        if (s) {
          close(s, event, p.durationMs, "ok");
          remove(openNodes, s);
        }
        break;
      }
      case "tool.started": {
        const parent = latest(openNodes, (n) => n.agent === agent) ?? openNodes.at(-1) ?? root;
        const s = span("tool", str(p.tool) ?? "tool", event, agent, "running");
        parent.children.push(s);
        openTools.push(s);
        break;
      }
      case "tool.completed": {
        const s = latest(openTools, (t) => t.name === str(p.tool) && t.agent === agent);
        if (s) {
          close(s, event, p.durationMs, p.status === "ok" ? "ok" : "error");
          s.evidenceIds = ids(p.evidenceIds);
          remove(openTools, s);
        }
        break;
      }
      default: {
        const status = eventStatus(event);
        const log = span("event", describe(event).text, event, agent, status);
        log.evidenceIds = ids(p.evidenceIds);
        if (RUN_LEVEL.has(event.type)) {
          root.children.push(log);
          const report = CONCLUSION.has(event.type) ? latest(openNodes, (n) => n.name === REPORT_NODE) : undefined;
          if (report) {
            close(report, event, undefined, "ok");
            remove(openNodes, report);
          }
          break;
        }
        const parent =
          (node && latest(openNodes, (n) => n.name === node)) || (agent && latest(openNodes, (n) => n.agent === agent)) || openNodes.at(-1) || root;
        parent.children.push(log);
        if (parent.kind === "node") {
          if (event.type === "error") {
            // The node returns straight after an error event without a node.completed.
            close(parent, event, undefined, "error");
            parent.status = "error";
            remove(openNodes, parent);
          } else if (status === "approval") parent.status = "approval";
        }
      }
    }
  }

  const last = sorted.at(-1);
  if (!active) {
    for (const s of [...openNodes, ...openTools]) s.status = "unfinished";
    if (last) {
      root.endTs = last.ts;
      root.durationMs = Date.parse(last.ts) - Date.parse(root.startTs);
    }
  }
  return root;
}

export interface TraceRow {
  span: Span;
  depth: number;
}

/** The rows the tree shows, depth-first; children of collapsed spans are skipped. The run span
 * itself is the header, so rows start at its children with depth 0. */
export function flattenTrace(root: Span, collapsed: ReadonlySet<string>): TraceRow[] {
  const rows: TraceRow[] = [];
  const walk = (s: Span, depth: number) => {
    rows.push({ span: s, depth });
    if (!collapsed.has(s.id)) for (const c of s.children) walk(c, depth + 1);
  };
  for (const c of root.children) walk(c, 0);
  return rows;
}

/** Counts for the trace header. */
export function traceStats(root: Span): { nodes: number; tools: number; errors: number } {
  let nodes = 0;
  let tools = 0;
  let errors = 0;
  const walk = (s: Span) => {
    if (s.kind === "node") nodes += 1;
    if (s.kind === "tool") tools += 1;
    if (s.status === "error" && s.kind !== "node") errors += 1;
    s.children.forEach(walk);
  };
  root.children.forEach(walk);
  return { nodes, tools, errors };
}
