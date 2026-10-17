"""Phase 0 migration: make a clean install reproducible + relax the
vendor-unsafe series_code uniqueness.

Why this exists
---------------
`vendor` and the `vendor_id` columns/FKs were only created by
scripts/migrate_add_vendor.py -- a manual script. Nothing in init/ created
them, so a fresh `docker-compose up` produced a database whose gear tables
referenced a non-existent vendor table and the engine crashed.

Also fixes two real defects found while inspecting the live DB:

1. `gear_series.series_code` had a GLOBAL UNIQUE. Two vendors may both
   publish a series called 'S1'; the second insert would fail.
   Relaxed to UNIQUE (vendor_id, series_code).

2. `ambient_factor` held rows for vendor_id=1 (Elecon) only, so
   engine._factors(3) returned {} and Premium selection silently ran with
   fw=1.0 -- i.e. no ambient derating at all. The factor rows are now
   replicated to every active vendor so both vendors derate identically.

Idempotent: safe to run any number of times.
Run:  D:\\gearbox-selector\\.venv\\Scripts\\python.exe scripts\\migrate_phase0.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]

DB = "postgresql://gearbox:gearbox@localhost:5433/gearbox"

# every table the vendor_id multi-vendor work touched, in backfill order
VENDOR_COLUMNS = [
    "gear_series",
    "gear_size",
    "power_rating",
    "thermal_capacity",
    "actual_ratio",
    "dimension",
    # factor / bookkeeping tables: no size chain, so these inherit Elecon
    "catalog_page",
    "import_log",
    "extraction_audit",
    "supplementary_model",
]

# how to derive vendor_id for the tables WITHOUT a size chain
SIMPLE_BACKFILL = ["ambient_factor", "altitude_factor", "application",
                   "duty_factor", "service_factor"]

STEPS: list[tuple[str, str]] = []


def run(c: psycopg.Connection) -> None:
    # ------------------------------------------------------------------
    print("1. vendor table")
    c.execute("""
        CREATE TABLE IF NOT EXISTS vendor (
            id          SERIAL PRIMARY KEY,
            code        TEXT NOT NULL UNIQUE,
            name        TEXT NOT NULL,
            description TEXT,
            is_active   BOOLEAN DEFAULT true,
            created_at  TIMESTAMP DEFAULT now())""")
    c.execute("""
        INSERT INTO vendor (code, name, description) VALUES
            ('elecon',  'Elecon',                    'Elecon EON-Series'),
            ('premium', 'Premium Helical Gearboxes', 'Premium helical catalogue')
        ON CONFLICT (code) DO NOTHING""")
    rows = c.execute("SELECT code, id FROM vendor ORDER BY id").fetchall()
    print("   vendors:", rows)
    elecon = next(r[1] for r in rows if r[0] == "elecon")
    active = [r[1] for r in rows]

    # ------------------------------------------------------------------
    print("2. vendor_id columns on gear tables")
    for tbl in VENDOR_COLUMNS:
        c.execute(f"ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS vendor_id INTEGER")
        c.execute(
            f"UPDATE {tbl} SET vendor_id = %s WHERE vendor_id IS NULL", (elecon,))
    for tbl in SIMPLE_BACKFILL:
        c.execute(f"ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS vendor_id INTEGER")
        c.execute(
            f"UPDATE {tbl} SET vendor_id = %s WHERE vendor_id IS NULL", (elecon,))

    # vendor_id is authoritative for the size-chain tables, so push it
    # *down* from the series so a size can never disagree with its series
    c.execute("""
        UPDATE gear_size gs SET vendor_id = s.vendor_id
        FROM gear_series s WHERE s.id = gs.series_id AND gs.vendor_id IS DISTINCT FROM s.vendor_id""")
    for tbl in ("power_rating", "thermal_capacity", "actual_ratio", "dimension"):
        c.execute(f"""
            UPDATE {tbl} t SET vendor_id = gs.vendor_id
            FROM gear_size gz JOIN gear_series gs ON gs.id = gz.series_id
            WHERE gz.id = t.gear_size_id AND t.vendor_id IS DISTINCT FROM gs.vendor_id""")

    # ------------------------------------------------------------------
    print("3. NOT NULL + FKs on the size-chain tables")
    c.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='gear_series'::regclass
                           AND conname='fk_gear_series_vendor') THEN
                ALTER TABLE gear_series ALTER COLUMN vendor_id SET NOT NULL;
                ALTER TABLE gear_series ADD CONSTRAINT fk_gear_series_vendor
                    FOREIGN KEY (vendor_id) REFERENCES vendor(id);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='gear_size'::regclass
                           AND conname='fk_gear_size_vendor') THEN
                ALTER TABLE gear_size ALTER COLUMN vendor_id SET NOT NULL;
                ALTER TABLE gear_size ADD CONSTRAINT fk_gear_size_vendor
                    FOREIGN KEY (vendor_id) REFERENCES vendor(id);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='power_rating'::regclass
                           AND conname='fk_power_rating_vendor') THEN
                ALTER TABLE power_rating ALTER COLUMN vendor_id SET NOT NULL;
                ALTER TABLE power_rating ADD CONSTRAINT fk_power_rating_vendor
                    FOREIGN KEY (vendor_id) REFERENCES vendor(id);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='thermal_capacity'::regclass
                           AND conname='fk_thermal_capacity_vendor') THEN
                ALTER TABLE thermal_capacity ALTER COLUMN vendor_id SET NOT NULL;
                ALTER TABLE thermal_capacity ADD CONSTRAINT fk_thermal_capacity_vendor
                    FOREIGN KEY (vendor_id) REFERENCES vendor(id);
            END IF;
        END $$""")

    # ------------------------------------------------------------------
    print("4. relax UNIQUE(series_code) -> UNIQUE(vendor_id, series_code)")
    dupes = c.execute("""
        SELECT series_code, count(*) FROM gear_series
        GROUP BY 1 HAVING count(*) > 1""").fetchall()
    if dupes:
        # never drop the constraint if it is currently load-bearing
        print("   !! cross-vendor duplicates exist, keeping global unique:", dupes)
    else:
        c.execute("ALTER TABLE gear_series "
                  "DROP CONSTRAINT IF EXISTS gear_series_series_code_key")
        c.execute("""DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint
                           WHERE conrelid='gear_series'::regclass
                             AND conname='gear_series_vendor_series_code_key') THEN
                ALTER TABLE gear_series
                    ADD CONSTRAINT gear_series_vendor_series_code_key
                    UNIQUE (vendor_id, series_code);
            END IF; END $$""")
        print("   -> UNIQUE (vendor_id, series_code)")

    # ------------------------------------------------------------------
    print("5. relax factor tables to per-vendor keys + replicate")
    # These 5 tables all had a GLOBAL unique on their natural key
    # (e.g. UNIQUE(cooling_type, amb_temp_c)), so per-vendor rows were
    # impossible. engine._factors(vendor_id) therefore returned {} for every
    # vendor except Elecon and silently applied fw=1.0 (no derating).
    # The derating curve is a property of a vendor's gearbox design, so the
    # key must include vendor_id.
    FACTOR_TABLES = [
        ("ambient_factor", ["cooling_type", "amb_temp_c"]),
        ("altitude_factor", ["altitude_m"]),
        ("application", ["code"]),
        ("duty_factor", ["hours_per_day"]),
        ("service_factor", ["load_class"]),
    ]
    for tbl, keycols in FACTOR_TABLES:
        try:
            with c.transaction():          # savepoint: one failure won't abort us
                for (n,) in c.execute(
                        "SELECT conname FROM pg_constraint "
                        "WHERE conrelid = %s::regclass AND contype = 'u'",
                        (tbl,)).fetchall():
                    c.execute(f'ALTER TABLE {tbl} DROP CONSTRAINT "{n}"')
                newname = f"{tbl}_vendor_key"
                c.execute(f'ALTER TABLE {tbl} ADD CONSTRAINT "{newname}" '
                          f'UNIQUE (vendor_id, {", ".join(keycols)})')

                # copy Elecon's reference rows to every other active vendor
                allc = [x.strip() for x in c.execute("""
                    SELECT string_agg(column_name, ',' ORDER BY ordinal_position)
                    FROM information_schema.columns
                    WHERE table_name = %s AND column_name NOT IN ('id', 'vendor_id')
                """, (tbl,)).fetchone()[0].split(",")]
                sel = ", ".join(f"src.{x}" for x in allc)
                wh = " AND ".join(
                    f"e.{k} IS NOT DISTINCT FROM src.{k}" for k in keycols)
                n = c.execute(f"""
                    INSERT INTO {tbl} ({", ".join(allc)}, vendor_id)
                    SELECT {sel}, v.id
                    FROM {tbl} src CROSS JOIN vendor v
                    WHERE src.vendor_id = %s
                      AND v.id <> %s
                      AND NOT EXISTS (
                          SELECT 1 FROM {tbl} e
                          WHERE e.vendor_id = v.id AND {wh})
                """, (elecon, elecon)).rowcount
                counts = c.execute(
                    f"SELECT vendor_id, count(*) FROM {tbl} "
                    "GROUP BY 1 ORDER BY 1").fetchall()
                print(f"   {tbl}: +{n} rows, per-vendor now {counts}")
        except psycopg.Error as e:
            print(f"   {tbl}: FAILED ({str(e).splitlines()[0][:70]})")

    # ------------------------------------------------------------------
    print("6. verify")
    chk = c.execute("""
        SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint
        WHERE conrelid='gear_series'::regclass AND contype='u'""").fetchall()
    for n, d in chk:
        print(f"   unique: {n} = {d}")
    nulls = c.execute("""
        SELECT count(*) FROM power_rating pr
        LEFT JOIN gear_size gz ON gz.id = pr.gear_size_id
        LEFT JOIN gear_series gs ON gs.id = gz.series_id
        WHERE gs.vendor_id IS DISTINCT FROM pr.vendor_id""").fetchone()[0]
    print(f"   power_rating rows disagreeing with their series vendor: {nulls}")


if __name__ == "__main__":
    with psycopg.connect(DB) as conn:
        run(conn)
    print("\nPhase 0 migration complete.")