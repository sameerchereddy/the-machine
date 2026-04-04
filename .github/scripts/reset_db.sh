#!/usr/bin/env bash
# Reset the local dev database — drops all tables and re-runs migrations.
# Requires DATABASE_URL in env or .env at repo root.
# Usage: bash .github/scripts/reset_db.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# Load .env if present
if [[ -f "$REPO_ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$REPO_ROOT/.env"
  set +a
fi

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "ERROR: DATABASE_URL is not set."
  exit 1
fi

MIGRATION="$REPO_ROOT/supabase/migrations/001_initial_schema.sql"

echo "Dropping all tables in public schema..."
psql "$DATABASE_URL" -c "
  DO \$\$ DECLARE
    r RECORD;
  BEGIN
    FOR r IN (SELECT tablename FROM pg_tables WHERE schemaname = 'public') LOOP
      EXECUTE 'DROP TABLE IF EXISTS ' || quote_ident(r.tablename) || ' CASCADE';
    END LOOP;
  END \$\$;
"

echo "Running migration: $MIGRATION"
psql "$DATABASE_URL" -f "$MIGRATION"

echo "Database reset complete."
