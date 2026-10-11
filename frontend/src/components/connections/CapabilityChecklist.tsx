import type { TargetCapabilities } from "@/lib/api/types";

function Item({ ok, text }: { ok: boolean; text: string }) {
  return (
    <li className="flex items-start gap-2 text-sm">
      <span aria-hidden className={ok ? "text-verified" : "text-inconclusive"}>
        {ok ? "✓" : "!"}
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
        <Item ok={!c.isSuperuser} text={c.isSuperuser ? "Superuser (refused)" : "Not a superuser"} />
        <Item ok={!c.canCreateRole} text={c.canCreateRole ? "Can create roles (refused)" : "Cannot create roles"} />
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
