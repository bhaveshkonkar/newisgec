"""Import Elecon shaft + foundation dimensions into the `dimension` table.

`elecon_dimensions.json` carries two tables per size/mounting:

  * shaft_*  - input/intermediate/output shaft diameters and lengths plus the
               overall V/W/D/L/M/A/Y values;
  * found_*  - the foundation/footing layout letters A B C C1 E F h H1 H2
               J(K) N O P R S T (and G on the torque-arm pages).

Idempotent: rerunning replaces the vendor-1 dimension rows and keeps every
row the weight migrator wrote.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import psycopg

DB = 'postgresql://gearbox:gearbox@localhost:5433/gearbox'
JSON = Path(__file__).resolve().parent / 'elecon_dimensions.json'
VENDOR_ID = 1
PREFIX = {'shaft': 'shaft_', 'foundation': 'found_'}


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
        nmissing = {t: 0 for t in PREFIX}
        by_series_size: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
        for r in rows:
            by_series_size[(r['table'], r['series'], r['size'])].append(r)

        for key in sorted(by_series_size):
            table, series, size = key
            gs = c.execute("""
                SELECT g.id FROM gear_size g
                JOIN gear_series s ON s.id = g.series_id
                WHERE s.vendor_id = %s AND s.series_code = %s AND g.size = %s
            """, (VENDOR_ID, series, size)).fetchone()
            if not gs:
                skipped += 1
                continue
            gear_size_id = gs[0]
            prefix = PREFIX[table]
            for r in by_series_size[key]:
                for name, value_mm in r['dims'].items():
                    c.execute("""
                        INSERT INTO dimension (gear_size_id, dim_name, value_mm,
                                               source_page, vendor_id)
                        VALUES (%s,%s,%s,%s,%s)
                    """, (gear_size_id, prefix + name, value_mm, r['page'], VENDOR_ID))
                    inserted += 1
            nmissing[table] += 0

        # how many sizes still have no foundation dims
        for t, prefix in PREFIX.items():
            n = c.execute("""
                SELECT count(*) FROM gear_size g
                JOIN gear_series s ON s.id = g.series_id
                WHERE s.vendor_id = %s
                  AND NOT EXISTS (
                    SELECT 1 FROM dimension d WHERE d.gear_size_id = g.id
                      AND d.dim_name LIKE %s || '%%')
            """, (VENDOR_ID, prefix,)).fetchone()[0]
            nmissing[t] = n

    print(f'inserted dimension values: {inserted}')
    print(f'series/size not found in catalogue: {skipped}')
    for t, n in nmissing.items():
        print(f'sizes missing {PREFIX[t]}* dims: {n}')
    return 0


if __name__ == '__main__':
    sys.exit(main())