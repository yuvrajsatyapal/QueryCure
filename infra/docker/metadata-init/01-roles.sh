#!/bin/bash
# Local development only: LOGIN roles for the restricted app user and the retention job.
# Production operators create these roles themselves; migrations only GRANT (DATABASE_DESIGN §5).
set -euo pipefail
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v app_pw="${QC_APP_PASSWORD:-qc_local_dev_only}" \
  -v retention_pw="${QC_RETENTION_PASSWORD:-qc_local_dev_only}" <<'SQL'
SELECT 'CREATE ROLE qc_app' WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'qc_app') \gexec
SELECT 'CREATE ROLE qc_retention' WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'qc_retention') \gexec
ALTER ROLE qc_app WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD :'app_pw';
ALTER ROLE qc_retention WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD :'retention_pw';
SQL
