SELECT
    s.queryid::text AS queryid,
    s.calls,
    s.total_exec_time::float8 AS total_exec_time_ms,
    s.mean_exec_time::float8 AS mean_exec_time_ms,
    s.rows,
    s.shared_blks_hit,
    s.shared_blks_read,
    s.temp_blks_written,
    left(s.query, 500) AS query
FROM pg_stat_statements s
WHERE s.dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
ORDER BY s.total_exec_time DESC
LIMIT %(limit)s
