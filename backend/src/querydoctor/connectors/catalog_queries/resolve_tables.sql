SELECT t.ord, c.oid::bigint AS oid, n.nspname::text AS schema_name, c.relname::text AS name
FROM unnest(%(schemas)s::text[], %(names)s::text[]) WITH ORDINALITY AS t (schema_name, name, ord)
JOIN pg_class c ON c.oid = to_regclass(
    CASE
        WHEN t.schema_name IS NULL THEN quote_ident(t.name)
        ELSE quote_ident(t.schema_name) || '.' || quote_ident(t.name)
    END
)
JOIN pg_namespace n ON n.oid = c.relnamespace
