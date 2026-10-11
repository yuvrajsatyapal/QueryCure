SELECT
    l.locktype,
    l.mode,
    coalesce(n.nspname || '.' || c.relname, '') AS relation,
    count(*) FILTER (WHERE l.granted)::int AS granted,
    count(*) FILTER (WHERE NOT l.granted)::int AS waiting
FROM pg_locks l
LEFT JOIN pg_class c ON c.oid = l.relation
LEFT JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE (l.database = (SELECT oid FROM pg_database WHERE datname = current_database())
       OR l.database IS NULL)
  AND l.pid <> pg_backend_pid()
GROUP BY 1, 2, 3
ORDER BY waiting DESC, granted DESC, 1, 2, 3
LIMIT 50
