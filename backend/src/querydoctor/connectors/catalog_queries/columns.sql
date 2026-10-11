-- Numeric statistics only. Value-bearing pg_stats columns are deliberately not selected (T1.11).
SELECT
    a.attrelid::bigint AS table_oid,
    a.attname::text AS name,
    format_type(a.atttypid, a.atttypmod) AS data_type,
    a.attnotnull AS not_null,
    a.attnum AS position,
    st.null_frac::float8 AS null_frac,
    st.n_distinct::float8 AS n_distinct,
    st.avg_width AS avg_width,
    st.correlation::float8 AS correlation
FROM pg_attribute a
JOIN pg_class c ON c.oid = a.attrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
LEFT JOIN pg_stats st
    ON st.schemaname = n.nspname AND st.tablename = c.relname AND st.attname = a.attname
   AND NOT st.inherited
WHERE a.attrelid = ANY(%(oids)s::oid[])
  AND a.attnum > 0
  AND NOT a.attisdropped
ORDER BY a.attrelid, a.attnum
