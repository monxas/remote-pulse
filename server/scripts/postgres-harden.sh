#!/usr/bin/env sh
# Postgres role hardening for the Remote-Pulse server (review F8-5).
#
# Run as root on the DB host (LXC 280). Strips REPLICATION + TRUNCATE rights
# from `rp_app` so an app-level compromise cannot bypass the immutability
# triggers on `commands` (audit log) by replication-role tricks or TRUNCATE.
#
# Idempotent. Safe to re-run.
set -eu

DB_NAME="${RP_DB_NAME:-remote_pulse}"
APP_ROLE="${RP_APP_ROLE:-rp_app}"

echo "→ Hardening Postgres role '$APP_ROLE' on database '$DB_NAME'..."

sudo -u postgres psql -v ON_ERROR_STOP=1 -d "$DB_NAME" <<SQL
-- 1. Strip REPLICATION (prevents session_replication_role=replica trigger bypass)
ALTER ROLE ${APP_ROLE} NOREPLICATION;

-- 2. Revoke TRUNCATE on the immutable audit log
REVOKE TRUNCATE ON TABLE commands FROM ${APP_ROLE};

-- 3. Revoke DROP/ALTER implicitly: app role should not own the table
--    (ownership stays with the migrations role, here 'postgres').
--    Verify ownership:
SELECT tablename, tableowner FROM pg_tables WHERE tablename = 'commands';

-- 4. Sanity check: app role must NOT be superuser
SELECT rolname, rolsuper, rolreplication, rolbypassrls
FROM pg_roles
WHERE rolname = '${APP_ROLE}';
SQL

echo "✓ Hardening applied"
echo
echo "Verification queries:"
sudo -u postgres psql -d "$DB_NAME" -c "
SELECT rolname, rolsuper, rolreplication, rolbypassrls
FROM pg_roles
WHERE rolname = '${APP_ROLE}';
"
