#!/usr/bin/env python3
"""Persist Premium net weights into the existing `dimension` table.

dimension(dim_name='net_weight_kg', weight_kg, source_page, vendor_id)
covers every (series, size) that already exists in gear_size for vendor 3.
Catalog cells that are '-' or '*' (not offered / PREMIUM E.T.L.) are NOT
inserted and are reported as `needs_review` rows for human follow-up.
"""
from __future__ import annotations

import sys
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.parse_premium_weights import extract_rows  # noqa: E402

DB = 'postgresql://gearbox:gearbox@localhost:5433/gearbox'
DIM_NAME = 'net_weight_kg'
VENDOR_ID = 3


def main() -> None:
    rows = extract_rows()
    known = [r for r in rows if r['weight_kg'] is not None]
    missing = [r for r in rows if r['weight_kg'] is None]

    with psycopg.connect(DB) as conn:
        # idempotent: reset this vendor's weights before inserting
        conn.execute(
            'DELETE FROM dimension WHERE dim_name = %s AND vendor_id = %s',
            (DIM_NAME, VENDOR_ID))

        inserted = skipped = 0
        for r in known:
            gs = conn.execute('''
                SELECT g.id FROM gear_size g
                JOIN gear_series s ON s.id = g.series_id
                WHERE s.vendor_id = %s AND s.series_code = %s AND g.size = %s''',
                (VENDOR_ID, r['series'], str(r['size']))).fetchone()
            if not gs:
                skipped += 1
                continue
            conn.execute('''
                INSERT INTO dimension (gear_size_id, dim_name, value_mm,
                                       weight_kg, source_page, vendor_id)
                VALUES (%s, %s, NULL, %s, %s, %s)''',
                (gs[0], DIM_NAME, r['weight_kg'], r['source_page'], VENDOR_ID))
            inserted += 1

        # review list: catalog says no weight (or size beyond table) but the
        # model exists in our ratings DB
        reviewed = 0
        for r in sorted(missing, key=lambda r: (r['series'], r['size'])):
            gs = conn.execute('''
                SELECT g.id FROM gear_size g
                JOIN gear_series s ON s.id = g.series_id
                WHERE s.vendor_id = %s AND s.series_code = %s AND g.size = %s''',
                (VENDOR_ID, r['series'], str(r['size']))).fetchone()
            if not gs:
                continue
            reviewed += 1
            print(f"  needs_review  {r['series']}-{r['size']}  "
                  f"(catalog: no weight — PREMIUM E.T.L.)")

        print(f'inserted={inserted}  skipped_not_in_DB={skipped}  '
              f'review_flags={reviewed}')

        # sweep: any vendor-3 model still without a weight (e.g. H2-710 which
        # sits beyond the weight table's 630 column header)
        orphan = conn.execute('''
            SELECT s.series_code, g.size FROM gear_size g
            JOIN gear_series s ON s.id = g.series_id
            WHERE s.vendor_id = %s
              AND NOT EXISTS (SELECT 1 FROM dimension d
                              WHERE d.gear_size_id = g.id
                                AND d.dim_name = %s)
            ORDER BY s.series_code, g.size::int''',
            (VENDOR_ID, DIM_NAME)).fetchall()
        for code, size in orphan:
            print(f'  needs_review  {code}-{size}  (no weight in catalog)')


if __name__ == '__main__':
    main()