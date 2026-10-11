SELECT
    s.schemaname::text AS schema_name,
    s.relname::text AS name,
    s.heap_blks_read,
    s.heap_blks_hit,
    s.idx_blks_read,
    s.idx_blks_hit
FROM pg_statio_all_tables s
WHERE s.relid = ANY(%(oids)s::oid[])
ORDER BY s.schemaname, s.relname
