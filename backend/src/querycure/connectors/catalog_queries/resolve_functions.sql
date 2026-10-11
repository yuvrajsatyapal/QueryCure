SELECT p.proname::text AS name, array_agg(DISTINCT n.nspname::text) AS schemas
FROM pg_proc p
JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE p.proname = ANY(%(names)s::text[])
GROUP BY p.proname
