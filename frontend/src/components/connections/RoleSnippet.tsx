const SQL = `CREATE ROLE querydoctor_inspector LOGIN PASSWORD 'choose-a-strong-password';
GRANT CONNECT ON DATABASE your_db TO querydoctor_inspector;
GRANT USAGE ON SCHEMA public TO querydoctor_inspector;
-- EXPLAIN needs SELECT on the tables it plans; nothing is ever executed.
GRANT SELECT ON ALL TABLES IN SCHEMA public TO querydoctor_inspector;
GRANT pg_read_all_stats TO querydoctor_inspector;`;

export function RoleSnippet() {
  return (
    <details className="rounded-md border border-border bg-surface-2 p-3 text-sm">
      <summary className="cursor-pointer font-medium">Create a restricted role for QueryDoctor</summary>
      <p className="mt-2 text-muted">
        Superuser, CREATEROLE and BYPASSRLS roles are refused. QueryDoctor only runs plain EXPLAIN and
        catalog reads in read-only sessions.
      </p>
      <pre className="mt-2 overflow-x-auto rounded-md bg-surface p-3 font-mono text-xs">{SQL}</pre>
    </details>
  );
}
