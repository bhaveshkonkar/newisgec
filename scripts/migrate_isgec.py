"""Apply the isgec schema to the live database and seed the dev profile.

init/*.sql only runs on Postgres's *first* init of an empty volume, so
anything already applied has to be re-applied here. Every statement is
idempotent and lives in init/05_isgec.sql -- this script just executes it
plus the seed row that SQL cannot know about.

Run:  D:\\gearbox-selector\\.venv\\Scripts\\python.exe scripts\\migrate_isgec.py
"""
from __future__ import annotations

from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_SQL = ROOT / "init" / "05_isgec.sql"
DB = "postgresql://gearbox:gearbox@localhost:5433/gearbox"

# Stable dev identity for the single-user phase. Phase 14 swaps
# getCurrentUser() to Supabase Auth; every project row already points at
# this UUID so nothing needs migrating.
DEV_USER_ID = "00000000-0000-4000-8000-000000000001"
DEV_EMAIL = "bhavesh.konkar@isgec.com"
DEV_NAME = "Bhavesh Konkar"


def run() -> None:
    with psycopg.connect(DB) as c:
        c.execute(SCHEMA_SQL.read_text(encoding="utf-8"))
        print("applied", SCHEMA_SQL.name)

        c.execute("""
            INSERT INTO isgec.profiles (id, email, full_name, initials, is_admin)
            VALUES (%s, %s, %s, 'BK', true)
            ON CONFLICT (id) DO UPDATE
              SET full_name = EXCLUDED.full_name,
                  email      = EXCLUDED.email""",
            (DEV_USER_ID, DEV_EMAIL, DEV_NAME))
        print(f"seeded profile {DEV_USER_ID} ({DEV_NAME})")

        print("\nisgec tables:")
        for t, in c.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'isgec' ORDER BY 1""").fetchall():
            print("  ", t)

        print("\nFK cascade check (project delete must take children with it):")
        for t, col in (("project_modules", "project_id"),
                       ("documents", "project_id"),
                       ("chat_sessions", "project_id")):
            d = c.execute("""
                SELECT confdeltype FROM pg_constraint
                WHERE conrelid = %s::regclass AND conname IN (
                    SELECT conname FROM pg_constraint
                    WHERE conrelid = %s::regclass AND contype='f')""",
                (f"isgec.{t}", f"isgec.{t}")).fetchall()
            print(f"   {t}.{col}: {[r[0] for r in d]}  (c='cascade', n='set null')")

        print("\nmodule_type CHECK values:")
        ck = c.execute("""
            SELECT pg_get_constraintdef(oid) FROM pg_constraint
            WHERE conrelid='isgec.project_modules'::regclass AND contype='c'
        """).fetchone()[0]
        print("  ", ck[:200])

    print("\nisgec schema ready.")


if __name__ == "__main__":
    run()