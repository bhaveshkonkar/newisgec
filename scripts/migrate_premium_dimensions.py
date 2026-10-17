"""Import Premium shaft + foundation dimensions into the `dimension` table.

`premium_dimensions.json` is produced by extract_premium_dimensions.py.  Each
row is one table of one unit type: `dims` already carries the found_* / shaft_*
prefix the reasoning layer keys on, so the migration writes the names verbatim.

Idempotent: rerunning replaces the vendor-3 dimension rows and leaves every
row the weight migrator (migrate_premium_weights.py) wrote untouched.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import psycopg

DB = 'postgresql://gearbox:gearbox@localhost:5433/gearbox'
JSON = Path(__file__).resolve().parent / 'premium_dimensions.json'
VENDOR_ID = 3
PREFIXES = ('shaft_', 'found_')


def main() -> int:
    rows = json.loads(JSON.read_text(encoding='utf-8'))

    with psycopg.connect(DB) as c:
        c.execute("""
            DELETE FROM dimension d
            USING gear_size g, gear_series s
            WHERE d.gear_size_id = g.id AND g.series_id = s.id
              AND s.vendor_id = %s
              AND (d.dim_name LIKE 'shaft_%%' OR d.dim_name LIKE 'found_%%')
        """, (VENDOR_ID,))

        inserted = skipped = 0
        size_cache: dict[tuple[str, str], str | None] = {}

        def gear_size_id(series: str, size: str):
            key = (series, size)
            if key not in size_cache:
                gs = c.execute("""
                    SELECT g.id FROM gear_size g
                    JOIN gear_series s ON s.id = g.series_id
                    WHERE s.vendor_id = %s AND s.series_code = %s AND g.size = %s
                """, (VENDOR_ID, series, size)).fetchone()
                size_cache[key] = gs[0] if gs else None
            return size_cache[key]

        for r in rows:
            gid = gear_size_id(r['series'], r['size'])
            if not gid:
                skipped += 1
                continue
            for name, value_mm in r['dims'].items():
                c.execute("""
                    INSERT INTO dimension (gear_size_id, dim_name, value_mm,
                                           source_page, vendor_id)
                    VALUES (%s,%s,%s,%s,%s)
                """, (gid, name, value_mm, r['page'], VENDOR_ID))
                inserted += 1

        missing = {}
        for prefix in PREFIXES:
            missing[prefix] = c.execute("""
                SELECT count(*) FROM gear_size g
                JOIN gear_series s ON s.id = g.series_id
                WHERE s.vendor_id = %s
                  AND NOT EXISTS (
                    SELECT 1 FROM dimension d WHERE d.gear_size_id = g.id
                      AND d.dim_name LIKE %s || '%%')
            """, (VENDOR_ID, prefix,)).fetchone()[0]

    print(f'inserted dimension values: {inserted}')
    print(f'rows skipped (size not in catalogue): {skipped}')
    for prefix, n in missing.items():
        print(f'sizes missing {prefix}* dims: {n}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
