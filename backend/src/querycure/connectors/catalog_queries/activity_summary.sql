-- Aggregates only: no query text, user names or client addresses of other sessions.
SELECT
    coalesce(a.state, 'unknown') AS state,
    coalesce(a.wait_event_type, 'none') AS wait_event_type,
    count(*)::int AS sessions,
    coalesce(max(extract(epoch FROM now() - a.xact_start)), 0)::float8 AS longest_xact_seconds
FROM pg_stat_activity a
WHERE a.datname = current_database()
  AND a.pid <> pg_backend_pid()
  AND a.backend_type = 'client backend'
GROUP BY 1, 2
ORDER BY sessions DESC, state, wait_event_type
LIMIT 50
