import type { CSSProperties, ReactNode } from "react";
import { LpIcon } from "./LpIcon";

/** The demo workload's slow query, used by the scripted sections (the X-Ray uses `SELECT *`). */
export const DEMO_SQL_PLAIN = "SELECT o.id, o.status, o.total_cents, o.created_at\nFROM   orders o\nWHERE  o.customer_id = $1\nORDER BY o.created_at DESC\nLIMIT  20;";

export function DemoSql() {
  return (
    <>
      <span className="k">SELECT</span> o.id, o.status, o.total_cents, o.created_at{"\n"}
      <span className="k">FROM</span>   orders o{"\n"}
      <span className="k">WHERE</span>  o.customer_id = <span className="s">$1</span>
      {"\n"}
      <span className="k">ORDER BY</span> o.created_at <span className="k">DESC</span>
      {"\n"}
      <span className="k">LIMIT</span>  <span className="s">20</span>;
    </>
  );
}

export function Ddl() {
  return (
    <>
      <span className="k">CREATE INDEX</span> <span className="k">ON</span> orders (customer_id, created_at <span className="k">DESC</span>);
    </>
  );
}

export function Spin() {
  return (
    <span className="spin" style={{ display: "inline-flex", color: "var(--running)" }}>
      <LpIcon name="loader" size={13} />
    </span>
  );
}

export function EvChip({ id }: { id: string }) {
  return (
    <span className="chip-ev">
      <LpIcon name="layers" size={11} />
      {id}
    </span>
  );
}

export type CheckTone = "verified" | "inconclusive" | "rejected";
export function Check({ tone = "verified", size = 14 }: { tone?: CheckTone; size?: number }) {
  const name = tone === "verified" ? "checkCircle" : tone === "inconclusive" ? "alert" : "xCircle";
  return (
    <span style={{ color: `var(--${tone})`, display: "inline-flex" }}>
      <LpIcon name={name} size={size} />
    </span>
  );
}

export function Illus({ children, style }: { children: ReactNode; style?: CSSProperties }) {
  return (
    <span className="illus" style={style}>
      {children}
    </span>
  );
}
