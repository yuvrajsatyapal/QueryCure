/* Query X-Ray: one illustrative query and its plan before and after
 * `CREATE INDEX ON orders (customer_id, created_at DESC)`. The plan shapes match a real PostgreSQL 17 run;
 * the timings shown with them come from the separate illustrative benchmark (bench.ts), not from this plan
 * (docs/design/prototypes/landing/README.md). */

export type XrayRow = "limit" | "sort" | "seq" | "idx" | "removed" | "note" | "baseline" | "result";
export type XrayViewId = "before" | "after";
export type EdgeTone = "hot" | "cool";

export type XrayView = {
  show: readonly XrayRow[];
  /** Indent level of the note under its operator. */
  noteLevel: number;
  note: string;
  /** Plan edges, child then parent, leaf first so the trace draws in execution order. */
  edges: readonly (readonly [XrayRow, XrayRow, EdgeTone])[];
  /** Operator the note's dotted leader attaches to. */
  leader: XrayRow;
};

export const XRAY_QUERY = "SELECT * FROM orders WHERE customer_id = $1 ORDER BY created_at DESC LIMIT 20";

export const XRAY_VIEWS: Record<XrayViewId, XrayView> = {
  before: {
    show: ["limit", "sort", "seq", "note", "baseline"],
    noteLevel: 3,
    note: "Reads every heap row of orders to find one customer's 47, then sorts them.",
    edges: [
      ["seq", "sort", "hot"],
      ["sort", "limit", "hot"],
    ],
    leader: "seq",
  },
  after: {
    show: ["limit", "idx", "removed", "note", "result"],
    noteLevel: 2,
    note: "In this example the index returns rows newest-first, so the scan stops after 20.",
    edges: [["idx", "limit", "cool"]],
    leader: "idx",
  },
};

/** Rows that fade out and in when switching views. The note's text changes, so it always does both. */
export function viewDiff(from: XrayViewId, to: XrayViewId): { leaving: XrayRow[]; entering: XrayRow[] } {
  if (from === to) return { leaving: [], entering: [] };
  const a = XRAY_VIEWS[from].show;
  const b = XRAY_VIEWS[to].show;
  return {
    leaving: a.filter((r) => r === "note" || !b.includes(r)),
    entering: b.filter((r) => r === "note" || !a.includes(r)),
  };
}

export type RowBox = { left: number; top: number; height: number };

/** Elbow from the child's left edge to the parent's spine, then up to the parent's bottom (plan coordinates). */
export function elbowPath(child: RowBox, parent: RowBox, spine: number): string {
  const y = child.top + Math.min(19, child.height / 2);
  return `M${child.left} ${y}H${parent.left + spine}V${parent.top + parent.height}`;
}
