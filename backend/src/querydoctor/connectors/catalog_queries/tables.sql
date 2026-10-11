SELECT
    c.oid::bigint AS oid,
    n.nspname::text AS schema_name,
    c.relname::text AS name,
    c.relkind::text AS kind,
    CASE WHEN c.reltuples < 0 THEN NULL ELSE c.reltuples::float8 END AS estimated_rows,
    c.relpages AS pages,
    pg_total_relation_size(c.oid) AS total_bytes,
    s.n_live_tup,
    s.n_dead_tup,
    s.n_mod_since_analyze,
    s.seq_scan,
    s.idx_scan,
    s.last_analyze,
    s.last_autoanalyze
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
LEFT JOIN pg_stat_all_tables s ON s.relid = c.oid
WHERE c.oid = ANY(%(oids)s::oid[])
ORDER BY n.nspname, c.relname
