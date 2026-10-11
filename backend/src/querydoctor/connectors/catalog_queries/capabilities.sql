SELECT
    current_setting('server_version_num')::int AS server_version_num,
    current_setting('server_version') AS server_version,
    r.rolsuper AS is_superuser,
    r.rolcreaterole AS can_create_role,
    r.rolbypassrls AS bypasses_rls,
    r.rolreplication AS is_replication_role,
    pg_has_role(current_user, 'pg_read_all_stats', 'MEMBER') AS can_read_all_stats,
    EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements') AS has_pg_stat_statements,
    COALESCE((SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()), false) AS ssl_in_use,
    (
        SELECT count(*)
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relowner = r.oid
          AND c.relkind IN ('r', 'p', 'm')
          AND n.nspname NOT IN ('pg_catalog', 'information_schema')
    ) AS owned_tables,
    ARRAY(
        SELECT nspname::text
        FROM pg_namespace
        WHERE has_schema_privilege(oid, 'USAGE')
          AND nspname NOT IN ('pg_catalog', 'information_schema')
          AND nspname NOT LIKE 'pg\_%%'
        ORDER BY 1
    ) AS schemas
FROM pg_roles r
WHERE r.rolname = current_user
