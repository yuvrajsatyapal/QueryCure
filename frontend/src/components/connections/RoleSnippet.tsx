const SQL = `CREATE ROLE querycure_inspector LOGIN PASSWORD 'choose-a-strong-password';
GRANT CONNECT ON DATABASE your_db TO querycure_inspector;
GRANT USAGE ON SCHEMA public TO querycure_inspector;
-- EXPLAIN needs SELECT on the tables it plans; nothing is ever executed.
GRANT SELECT ON ALL TABLES IN SCHEMA public TO querycure_inspector;
GRANT pg_read_all_stats TO querycure_inspector;`;

export function RoleSnippet() {
  return (
    <details className="rounded-md border border-border bg-surface-2 p-3 text-sm" open>
      <summary className="cursor-pointer font-medium">Create a restricted role for QueryCure</summary>
      <p className="mt-2 text-muted">
        Superuser, CREATEROLE and BYPASSRLS roles are refused. QueryCure only runs plain EXPLAIN and
        catalog reads in read-only sessions.
      </p>
      <pre tabIndex={0} className="mt-2 overflow-x-auto rounded-md border border-border bg-surface p-3 font-mono text-xs">{SQL}</pre>
    </details>
  );
}
