import type { TargetCapabilities } from "@/lib/api/types";

/** ok ✓, a limitation ! (warning), or a refusal ✕ (failed): always with the words. */
function Item({ ok, text, refusal = false }: { ok: boolean; text: string; refusal?: boolean }) {
  const mark = ok ? "✓" : refusal ? "✕" : "!";
  const color = ok ? "text-verified" : refusal ? "text-rejected" : "text-inconclusive";
  return (
    <li className="flex items-start gap-2 text-sm">
      <span aria-hidden className={`w-3 ${color}`}>
        {mark}
      </span>
      <span>{text}</span>
    </li>
  );
}

export function CapabilityChecklist({ capabilities: c }: { capabilities: TargetCapabilities }) {
  return (
    <div className="flex flex-col gap-2">
      <p className="font-mono text-xs text-muted">PostgreSQL {c.serverVersion}</p>
      <ul className="flex flex-col gap-1">
        <Item refusal ok={!c.isSuperuser} text={c.isSuperuser ? "Superuser (refused)" : "Not a superuser"} />
        <Item refusal ok={!c.canCreateRole} text={c.canCreateRole ? "Can create roles (refused)" : "Cannot create roles"} />
        <Item ok={c.canReadAllStats} text={c.canReadAllStats ? "Reads all statistics (pg_read_all_stats)" : "Limited statistics access"} />
        <Item
          ok={c.hasPgStatStatements}
          text={c.hasPgStatStatements ? "pg_stat_statements installed" : "pg_stat_statements not installed"}
        />
        <Item ok={c.sslInUse} text={c.sslInUse ? "Connection uses TLS" : "Connection is not encrypted"} />
      </ul>
      {(c.warnings ?? []).length > 0 ? (
        <ul className="flex flex-col gap-1 text-sm text-inconclusive">
          {(c.warnings ?? []).map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
