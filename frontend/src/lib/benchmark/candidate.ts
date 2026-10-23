// Short descriptions of optimization candidates, derived from their recorded SQL only
// (FINAL_UI_POLISH §2.2). The parser accepts the three forms the sandbox allowlist accepts
// (backend sql/ddl_allowlist.py); anything else gets the generic kind label, never a guess.

const KIND_LABEL: Record<string, string> = {
  create_index: "Index candidate",
  query_rewrite: "Query rewrite",
  analyze_statistics: "Statistics refresh",
  extended_statistics: "Extended statistics",
};

const IDENT = String.raw`(?:"[^"]{1,63}"|[A-Za-z_][A-Za-z0-9_]*)`;
const TABLE = String.raw`(${IDENT}(?:\s*\.\s*${IDENT})?)`;
const INDEX_HEAD = new RegExp(String.raw`^create\s+index\s+(?:if\s+not\s+exists\s+)?(?:${IDENT}\s+)?on\s+(?:only\s+)?${TABLE}\s*(?:using\s+(\w+)\s*)?\(`, "i");
const STATS = new RegExp(String.raw`^create\s+statistics\s+(?:if\s+not\s+exists\s+)?(?:${IDENT}\s+)?(?:\(([^)]*)\)\s*)?on\s+(.+?)\s+from\s+${TABLE}$`, "i");
const ANALYZE = new RegExp(String.raw`^analyze\s+${TABLE}\s*(?:\(([^)]*)\))?$`, "i");

const unquote = (s: string) => s.trim().replace(/^"(.*)"$/, "$1");
/** `public.orders` → `orders`; other schemas stay qualified. */
const table = (s: string) => {
  const parts = s.split(".").map(unquote);
  return parts.length === 2 && parts[0]!.toLowerCase() === "public" ? parts[1]! : parts.join(".");
};
const tidy = (s: string) => unquote(s.replace(/\s+/g, " ").trim());

/** Contents of the parenthesis opening at `open`, and the index after its closing one. */
function balanced(s: string, open: number): [string, number] | null {
  let depth = 0;
  for (let i = open; i < s.length; i++) {
    if (s[i] === "(") depth++;
    else if (s[i] === ")" && --depth === 0) return [s.slice(open + 1, i), i + 1];
  }
  return null;
}

function splitTop(s: string): string[] {
  const out: string[] = [];
  let depth = 0;
  let start = 0;
  for (let i = 0; i < s.length; i++) {
    if (s[i] === "(") depth++;
    else if (s[i] === ")") depth--;
    else if (s[i] === "," && depth === 0) {
      out.push(s.slice(start, i));
      start = i + 1;
    }
  }
  out.push(s.slice(start));
  return out.map(tidy).filter(Boolean);
}

function describeIndex(sql: string): string | null {
  const head = INDEX_HEAD.exec(sql);
  if (!head) return null;
  const inner = balanced(sql, head[0].length - 1);
  if (!inner) return null;
  const columns = splitTop(inner[0]);
  if (columns.length === 0) return null;
  const rest = sql.slice(inner[1]).trim();
  const tail = /^(?:include\s*\(([^)]*)\)\s*)?(where\s+[\s\S]+)?$/i.exec(rest);
  if (!tail) return null;
  const method = head[2]?.toLowerCase();
  const parts = [`${columns.length > 1 ? "Composite index" : "Index"} on ${table(head[1]!)} (${columns.join(", ")})`];
  if (method && method !== "btree") parts.push(method);
  if (tail[1]) parts.push(`includes ${splitTop(tail[1]).join(", ")}`);
  if (tail[2]) parts.push("partial");
  return parts.join(" · ");
}

function describeStatement(raw: string): string | null {
  const sql = raw.trim().replace(/;\s*$/, "").trim();
  if (/^create\s+index\b/i.test(sql)) return describeIndex(sql);
  const stats = STATS.exec(sql);
  if (stats) {
    const kinds = stats[1] ? splitTop(stats[1]).map((k) => k.toLowerCase()) : [];
    const head = `Extended statistics on ${table(stats[3]!)} (${splitTop(stats[2]!).join(", ")})`;
    return kinds.length ? `${head} · ${kinds.join(", ")}` : head;
  }
  const analyze = ANALYZE.exec(sql);
  if (analyze) {
    const cols = analyze[2] ? ` (${splitTop(analyze[2]).join(", ")})` : "";
    return `Refresh planner statistics on ${table(analyze[1]!)}${cols}`;
  }
  return null;
}

export interface CandidateSql {
  kind: string;
  ddl: readonly string[];
  querySql: string | null;
}

export function candidateKindLabel(kind: string): string {
  return KIND_LABEL[kind] ?? kind.replaceAll("_", " ");
}

/** "Composite index on orders (customer_id, created_at)". Deterministic; no model involved. */
export function describeCandidate(c: CandidateSql): string {
  if (c.kind === "query_rewrite") return KIND_LABEL.query_rewrite!;
  if (c.ddl.length === 0) return candidateKindLabel(c.kind);
  const described = c.ddl.map(describeStatement);
  return described.every((d): d is string => d !== null) ? described.join(" + ") : candidateKindLabel(c.kind);
}
