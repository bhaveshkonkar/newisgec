"""Import Elecon EON-Series average weights into the `dimension` table.

The catalogue prints "Average Weight [kg]" per series/size for each mounting
variant (horizontal H/HN and torque-arm T). The app's nomenclature is always
horizontal (-HN-HB-), so:

  net_weight_kg              <- horizontal variant  (used for pricing)
  net_weight_kg_torque_arm   <- torque-arm variant  (reference only)

Idempotent: rerunning replaces the vendor-1 weight rows.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import psycopg

DB = 'postgresql://gearbox:gearbox@localhost:5433/gearbox'
JSON = Path(__file__).resolve().parent / 'elecon_weights.json'
VENDOR_ID = 1


def main() -> int:
    rows = json.loads(JSON.read_text(encoding='utf-8'))

    # horizontal first, then torque-arm
    def rank(v: str) -> int:
        return 0 if v in ('H', 'HN', 'HD') else 1

    by_size: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        by_size[(r['series'], r['size'])].append(r)
    for v in by_size.values():
        v.sort(key=lambda r: rank(r['variant']))

    with psycopg.connect(DB) as c:
        # remove previously imported weight rows for this vendor
        c.execute("""
            DELETE FROM dimension d
            USING gear_size g, gear_series s
            WHERE d.gear_size_id = g.id AND g.series_id = s.id
              AND s.vendor_id = %s
              AND d.dim_name IN ('net_weight_kg','net_weight_kg_torque_arm')
        """, (VENDOR_ID,))

        inserted = skipped = torque = 0
        missing = []
        for (series, size), variants in sorted(by_size.items()):
            h = variants[0]
            gs = c.execute("""
                SELECT g.id FROM gear_size g
                JOIN gear_series s ON s.id = g.series_id
                WHERE s.vendor_id = %s AND s.series_code = %s AND g.size = %s
            """, (VENDOR_ID, series, size)).fetchone()
            if not gs:
                skipped += 1
                continue
            gear_size_id = gs[0]
            c.execute("""
                INSERT INTO dimension (gear_size_id, dim_name, weight_kg,
                                       source_page, vendor_id)
                VALUES (%s,'net_weight_kg',%s,%s,%s)
            """, (gear_size_id, h['weight_kg'], h['page'], VENDOR_ID))
            inserted += 1
            if len(variants) > 1:
                t = variants[1]
                c.execute("""
                    INSERT INTO dimension (gear_size_id, dim_name, weight_kg,
                                           source_page, vendor_id)
                    VALUES (%s,'net_weight_kg_torque_arm',%s,%s,%s)
                """, (gear_size_id, t['weight_kg'], t['page'], VENDOR_ID))
                torque += 1

        # what the catalog has no weight table for
        for series, size in c.execute("""
            SELECT s.series_code, g.size FROM gear_size g
            JOIN gear_series s ON s.id = g.series_id
            WHERE s.vendor_id = %s
              AND NOT EXISTS (
                SELECT 1 FROM dimension d WHERE d.gear_size_id = g.id
                  AND d.dim_name = 'net_weight_kg')
            ORDER BY s.series_code, g.size
        """, (VENDOR_ID,)).fetchall():
            missing.append(f'{series}-{size}')

    print(f'inserted net_weight_kg: {inserted}')
    print(f'inserted net_weight_kg_torque_arm: {torque}')
    print(f'series/size not in catalog weight table: {skipped}')
    if missing:
        by_ser = defaultdict(list)
        for m in missing:
            ser, size = m.rsplit('-', 1)
            by_ser[ser].append(size)
        for ser in sorted(by_ser):
            print(f'  {ser}: {", ".join(by_ser[ser])}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
