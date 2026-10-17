"""Verify the init/ scripts build the same schema as the live database.

The live `gearbox` database accreted schema over months of one-off migrations.
init/ is supposed to reproduce it from nothing. That equivalence is easy to
break and hard to notice, because the live DB keeps working either way -- it
just leaves a fresh deployment subtly wrong.

This drops a disposable database, replays every init script in order three
times (idempotency is part of the contract), diffs the result against the live
schema, and drops the disposable database again.

    .venv\\Scripts\\python.exe scripts\\test_fresh_init.py

Exits non-zero on any table/column drift.
"""
from __future__ import annotations

import subprocess
import sys

DB = "gearbox"
TEST_DB = "gearbox_freshtest"
PG = ["docker", "exec", "-i", "gearbox-db", "psql", "-U", "gearbox", "-v", "ON_ERROR_STOP=1"]

SCRIPTS = [
    "init/00_vendor.sql",
    "init/01_schema.sql",
    "init/02_accuracy.sql",
    "init/03_thermal_speed.sql",
    "init/04_prices.sql",
    "init/05_isgec.sql",
    "init/06_catalogue_seed.sql",
]

# Row counts that must match the live database. Comparing only the *schema*
# is not enough: a fresh build can have a perfect schema and zero gearboxes in
# it, which is exactly what happened before 06_catalogue_seed.sql existed.
CATALOGUE_TABLES = [
    "vendor", "gear_series", "gear_size", "power_rating", "thermal_capacity",
    "dimension", "series_mounting", "catalog_page", "ambient_factor",
    "duty_factor", "service_factor", "application", "altitude_factor",
]


def psql(db: str, sql: str, quiet: bool = True) -> str:
    cmd = PG + ["-d", db, "-t", "-A", "-F", "|", "-c", sql]
    if quiet:
        cmd += ["-q"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"psql failed on {db}: {r.stderr.strip()[:400]}")
    return r.stdout


def replay(db: str, script: str) -> None:
    with open(script, "r", encoding="utf-8") as fh:
        sql = fh.read()
    r = subprocess.run(PG + ["-d", db, "-q"], input=sql,
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{script} failed: {r.stderr.strip()[:600]}")


def schema_of(db: str) -> dict[str, set[str]]:
    """{'public.table': {'col:type', ...}, 'isgec.table': {...}}"""
    rows = psql(db, """
        SELECT table_schema || '.' || table_name, column_name || ':' || data_type
          FROM information_schema.columns
         WHERE table_schema IN ('public', 'isgec')
           AND table_name <> 'alembic_version'
    """)
    out: dict[str, set[str]] = {}
    for line in rows.splitlines():
        if not line.strip():
            continue
        table, col = line.split("|", 1)
        out.setdefault(table, set()).add(col)
    return out


def main() -> int:
    print(f"dropping {TEST_DB} if present")
    psql("postgres", f'DROP DATABASE IF EXISTS "{TEST_DB}"')

    print(f"creating {TEST_DB}")
    psql("postgres", f'CREATE DATABASE "{TEST_DB}"')

    failures: list[str] = []
    try:
        for run in range(1, 4):
            print(f"\n-- replay {run}/3")
            for s in SCRIPTS:
                try:
                    replay(TEST_DB, s)
                    print(f"   ok   {s}")
                except RuntimeError as exc:
                    failures.append(str(exc))
                    print(f"   FAIL {s}\n        {exc}")

        print("\n-- schema diff against live")
        live = schema_of(DB)
        fresh = schema_of(TEST_DB)

        only_live = sorted(set(live) - set(fresh))
        only_fresh = sorted(set(fresh) - set(live))

        for t in only_live:
            print(f"   MISSING in fresh: {t}")
            failures.append(f"table missing from fresh init: {t}")
        for t in only_fresh:
            print(f"   EXTRA in fresh:   {t}")

        for t in sorted(set(live) & set(fresh)):
            miss = live[t] - fresh[t]
            extra = fresh[t] - live[t]
            for c in sorted(miss):
                print(f"   COLUMN missing: {t}.{c}")
                failures.append(f"column missing from fresh init: {t}.{c}")
            for c in sorted(extra):
                print(f"   column extra:   {t}.{c}")

        print("\n-- catalogue data (fresh vs live)")
        for t in CATALOGUE_TABLES:
            f = psql(TEST_DB, f"SELECT count(*) FROM public.{t}").strip()
            lv = psql(DB, f"SELECT count(*) FROM public.{t}").strip()
            ok = f == lv
            print(f"   {t:20s} fresh={f:>6s}  live={lv:>6s}{'' if ok else '   <-- MISMATCH'}")
            if not ok:
                failures.append(f"row count mismatch in {t}: fresh={f} live={lv}")

        # the failure mode this file exists to catch
        empty = psql(TEST_DB, "SELECT count(*) FROM public.gear_series").strip()
        if empty == "0":
            failures.append("fresh init produced a schema with no gear series")
            print("   FATAL: fresh database has no gear series")
        else:
            print(f"   fresh database carries {empty} gear series "
                  f"({psql(TEST_DB, 'SELECT count(*) FROM public.power_rating').strip()} "
                  f"power ratings)")

        print("\n-- backfilled mounting")
        rows = psql(TEST_DB, """
            SELECT s.series_code, string_agg(m.mounting_type, ',' ORDER BY m.mounting_type)
              FROM series_mounting m JOIN gear_series s ON s.id = m.series_id
             GROUP BY 1 ORDER BY 1
        """)
        print("  " + (rows.strip().replace("\n", "\n  ") or "(none)"))
        if rows.strip() == "":
            failures.append("series_mounting backfill produced no rows")

    finally:
        print(f"\ndropping {TEST_DB}")
        psql("postgres", f'DROP DATABASE IF EXISTS "{TEST_DB}"')

    print("\n" + "=" * 60)
    if failures:
        print(f"FRESH INIT: {len(failures)} problem(s)")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("FRESH INIT: SCHEMA MATCHES LIVE, 3 IDEMPOTENT PASSES")
    return 0


if __name__ == "__main__":
    sys.exit(main())