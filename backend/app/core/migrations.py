from pathlib import Path

import asyncpg

from app.core.config import settings

_MIGRATIONS_DIR = Path(__file__).parents[3] / "supabase" / "migrations"

_CREATE_MIGRATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     TEXT        PRIMARY KEY,
    applied_at  TIMESTAMPTZ DEFAULT now()
);
"""


async def run_pending_migrations() -> None:
    """
    Apply any unapplied *.sql files from supabase/migrations/ in version order.
    Skips gracefully if DATABASE_URL is not configured (e.g. CI, tests).
    """
    if not settings or not settings.database_url:
        print("Migrations: DATABASE_URL not set — skipping")
        return

    conn: asyncpg.Connection = await asyncpg.connect(settings.database_url)
    try:
        await conn.execute(_CREATE_MIGRATIONS_TABLE)

        rows = await conn.fetch("SELECT version FROM schema_migrations ORDER BY version")
        applied = {row["version"] for row in rows}

        pending = sorted(p for p in _MIGRATIONS_DIR.glob("*.sql") if p.stem not in applied)

        if not pending:
            print("Migrations: all up to date")
            return

        for path in pending:
            version = path.stem
            print(f"Migrations: applying {version} ...")
            async with conn.transaction():
                await conn.execute(path.read_text())
                await conn.execute("INSERT INTO schema_migrations (version) VALUES ($1)", version)
            print(f"Migrations: ✓ {version}")

    finally:
        await conn.close()
