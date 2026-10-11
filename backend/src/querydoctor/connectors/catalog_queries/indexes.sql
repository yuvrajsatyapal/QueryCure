SELECT
    i.indrelid::bigint AS table_oid,
    ic.relname::text AS name,
    pg_get_indexdef(i.indexrelid) AS definition,
    i.indisunique AS is_unique,
    i.indisprimary AS is_primary,
    i.indisvalid AS is_valid,
    pg_relation_size(i.indexrelid) AS size_bytes,
    s.idx_scan
FROM pg_index i
JOIN pg_class ic ON ic.oid = i.indexrelid
LEFT JOIN pg_stat_all_indexes s ON s.indexrelid = i.indexrelid
WHERE i.indrelid = ANY(%(oids)s::oid[])
ORDER BY i.indrelid, ic.relname
