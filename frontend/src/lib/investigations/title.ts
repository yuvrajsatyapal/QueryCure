/* A deterministic title for a query, built from its text alone (UI_UX §3.14). No LLM and no network:
 * the same SQL always yields the same title. Comments and literals are dropped before reading, so
 * nothing inside them can surface in the title. This is a reading aid, not a parser: the server's
 * validator stays the authority on what the SQL means. */

const MAX_LENGTH = 120;
const MAX_TABLES = 3;
const MAX_COLUMNS = 2;

type Token = { kind: "ident" | "quoted" | "number" | "punct" | "op" | "param"; text: string };

const KEYWORDS = new Set([
  "select", "from", "where", "join", "inner", "left", "right", "full", "outer", "cross", "natural", "on", "using",
  "and", "or", "not", "null", "true", "false", "is", "in", "like", "ilike", "between", "exists", "as", "with",
  "recursive", "materialized", "group", "by", "order", "having", "limit", "offset", "union", "intersect", "except",
  "all", "distinct", "case", "when", "then", "else", "end", "asc", "desc", "nulls", "first", "last", "lateral",
  "only", "window", "returning", "fetch", "interval", "any", "some", "similar",
]);
const CLAUSE_END = new Set(["group", "order", "limit", "offset", "having", "window", "union", "intersect", "except", "returning", "fetch"]);
const COMPARISON = new Set(["=", "<", ">", "<=", ">=", "<>", "!=", "like", "ilike", "in", "is", "between", "similar", "~", "~*"]);
const AGGREGATES = new Set(["count", "sum", "avg", "min", "max"]);

function tokenize(sql: string): Token[] {
  const tokens: Token[] = [];
  let i = 0;
  const n = sql.length;
  while (i < n) {
    const ch = sql[i] ?? "";
    const next = sql[i + 1] ?? "";
    if (/\s/.test(ch)) {
      i += 1;
    } else if (ch === "-" && next === "-") {
      while (i < n && sql[i] !== "\n") i += 1;
    } else if (ch === "/" && next === "*") {
      const close = sql.indexOf("*/", i + 2);
      i = close === -1 ? n : close + 2;
    } else if (ch === "'" || ((ch === "e" || ch === "E") && next === "'")) {
      i += ch === "'" ? 1 : 2;
      while (i < n) {
        if (sql[i] === "\\" && ch !== "'") i += 2;
        else if (sql[i] === "'" && sql[i + 1] === "'") i += 2;
        else if (sql[i] === "'") break;
        else i += 1;
      }
      i += 1;
    } else if (ch === "$" && /[0-9]/.test(next)) {
      let j = i + 1;
      while (j < n && /[0-9]/.test(sql[j] ?? "")) j += 1;
      tokens.push({ kind: "param", text: sql.slice(i, j) });
      i = j;
    } else if (ch === "$") {
      // Dollar-quoted string: $$…$$ or $tag$…$tag$.
      const tag = /^\$[A-Za-z_]*\$/.exec(sql.slice(i))?.[0];
      if (tag) {
        const close = sql.indexOf(tag, i + tag.length);
        i = close === -1 ? n : close + tag.length;
      } else {
        i += 1;
      }
    } else if (ch === '"') {
      let j = i + 1;
      let text = "";
      while (j < n) {
        if (sql[j] === '"' && sql[j + 1] === '"') {
          text += '"';
          j += 2;
        } else if (sql[j] === '"') break;
        else {
          text += sql[j];
          j += 1;
        }
      }
      tokens.push({ kind: "quoted", text });
      i = j + 1;
    } else if (/[A-Za-z_]/.test(ch)) {
      let j = i + 1;
      while (j < n && /[A-Za-z0-9_$]/.test(sql[j] ?? "")) j += 1;
      tokens.push({ kind: "ident", text: sql.slice(i, j).toLowerCase() });
      i = j;
    } else if (/[0-9]/.test(ch)) {
      let j = i + 1;
      while (j < n && /[0-9.]/.test(sql[j] ?? "")) j += 1;
      tokens.push({ kind: "number", text: sql.slice(i, j) });
      i = j;
    } else if ("(),.;".includes(ch)) {
      tokens.push({ kind: "punct", text: ch });
      i += 1;
    } else {
      let j = i + 1;
      while (j < n && "<>=!~*".includes(sql[j] ?? "") && "<>=!~".includes(ch)) j += 1;
      tokens.push({ kind: "op", text: sql.slice(i, j) });
      i = j;
    }
  }
  return tokens;
}

const isName = (t: Token | undefined): t is Token =>
  t !== undefined && (t.kind === "quoted" || (t.kind === "ident" && !KEYWORDS.has(t.text)));
const isWord = (t: Token | undefined, word: string) => t?.kind === "ident" && t.text === word;

/** Reads `a.b.c` from position i; returns the last part and the index after the name. */
function qualifiedName(tokens: Token[], i: number): { name: string; end: number } | null {
  if (!isName(tokens[i])) return null;
  let name = tokens[i]?.text ?? "";
  let j = i + 1;
  while (tokens[j]?.text === "." && isName(tokens[j + 1])) {
    name = tokens[j + 1]?.text ?? name;
    j += 2;
  }
  return { name, end: j };
}

function pushUnique(list: string[], value: string) {
  if (!list.includes(value)) list.push(value);
}

function cteNames(tokens: Token[]): Set<string> {
  const names = new Set<string>();
  tokens.forEach((t, i) => {
    if (!isName(t)) return;
    let j = i + 1;
    if (tokens[j]?.text === "(") {
      while (j < tokens.length && tokens[j]?.text !== ")") j += 1;
      j += 1;
    }
    if (!isWord(tokens[j], "as")) return;
    j += 1;
    if (isWord(tokens[j], "not")) j += 1;
    if (isWord(tokens[j], "materialized")) j += 1;
    if (tokens[j]?.text === "(") names.add(t.text);
  });
  return names;
}

function tables(tokens: Token[]): string[] {
  const ctes = cteNames(tokens);
  const found: string[] = [];
  for (let i = 0; i < tokens.length; i += 1) {
    if (!isWord(tokens[i], "from") && !isWord(tokens[i], "join")) continue;
    let j = i + 1;
    for (;;) {
      while (isWord(tokens[j], "lateral") || isWord(tokens[j], "only")) j += 1;
      const ref = qualifiedName(tokens, j);
      if (!ref || tokens[ref.end]?.text === "(") break; // a subquery or a set-returning function
      if (!ctes.has(ref.name)) pushUnique(found, ref.name);
      j = ref.end;
      if (isWord(tokens[j], "as")) j += 2;
      else if (isName(tokens[j])) j += 1;
      if (!isWord(tokens[i], "from") || tokens[j]?.text !== ",") break;
      j += 1;
    }
  }
  return found;
}

/** Tokens of a clause, from after its keyword(s) to the next clause at the same nesting depth. */
function clause(tokens: Token[], start: number): Token[] {
  const out: Token[] = [];
  let depth = 0;
  for (let i = start; i < tokens.length; i += 1) {
    const t = tokens[i];
    if (!t) break;
    if (t.text === "(") depth += 1;
    if (t.text === ")") {
      if (depth === 0) break;
      depth -= 1;
    }
    if (depth === 0 && (t.text === ";" || (t.kind === "ident" && CLAUSE_END.has(t.text)))) break;
    out.push(t);
  }
  return out;
}

function filterColumns(tokens: Token[]): string[] {
  const found: string[] = [];
  tokens.forEach((t, i) => {
    if (!isWord(t, "where")) return;
    const body = clause(tokens, i + 1);
    body.forEach((c, k) => {
      const after = body[k + 1];
      const operator = after && (after.kind === "op" || after.kind === "ident") && COMPARISON.has(after.text);
      if (operator && isName(c)) pushUnique(found, c.text);
    });
  });
  return found.slice(0, MAX_COLUMNS);
}

function columnsAfter(tokens: Token[], first: string): string[] {
  const found: string[] = [];
  tokens.forEach((t, i) => {
    if (found.length > 0 || !isWord(t, first) || !isWord(tokens[i + 1], "by")) return;
    const body = clause(tokens, i + 2);
    for (let k = 0; k < body.length; k += 1) {
      const ref = qualifiedName(body, k);
      if (ref && body[ref.end]?.text !== "(") {
        pushUnique(found, ref.name);
        k = ref.end - 1;
      }
    }
  });
  return found;
}

export function suggestTitle(sql: string): string | null {
  const tokens = tokenize(sql);
  const names = tables(tokens);
  if (names.length === 0) return null;

  const shown = names.slice(0, MAX_TABLES).join(" + ");
  const parts = [names.length > MAX_TABLES ? `${shown} +${names.length - MAX_TABLES}` : shown];
  const filters = filterColumns(tokens);
  if (filters.length > 0) parts.push(`where ${filters.join(", ")}`);
  const groups = columnsAfter(tokens, "group").slice(0, MAX_COLUMNS);
  if (groups.length > 0) parts.push(`group by ${groups.join(", ")}`);
  else if (tokens.some((t, i) => t.kind === "ident" && AGGREGATES.has(t.text) && tokens[i + 1]?.text === "(")) parts.push("aggregate");
  const order = columnsAfter(tokens, "order")[0];
  if (order) parts.push(`order by ${order}`);
  const limitAt = tokens.findIndex((t) => isWord(t, "limit"));
  const limit = tokens[limitAt + 1];
  if (limitAt !== -1 && limit?.kind === "number") parts.push(`limit ${limit.text}`);

  const title = parts.join(" · ");
  return title.length > MAX_LENGTH ? `${title.slice(0, MAX_LENGTH - 1)}…` : title;
}
