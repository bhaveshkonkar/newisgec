"""Import the extracted EON-Series power/thermal tables into Postgres.

Run:  D:\\gearbox-selector\\.venv\\Scripts\\python.exe scripts\\import_gearbox.py
"""
import sys
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

sys.path.insert(0, r'D:\gearbox-selector')

import psycopg
from parsers.tables import extract
from parsers.manifest import SERIES

DB = 'postgresql://gearbox:gearbox@localhost:5433/gearbox'
THERMAL_AMBIENT = 20       # thermal tables are rated at 20 deg C
THERMAL_ED = 100
SOURCE = 'Elecon G B_EON-Series.pdf'

PAGE_WANTED = {8: ['S1'], 9: ['S1'],
               10: ['S2', 'S3'], 11: ['S2', 'S3'],
               12: ['S4', 'K2'], 13: ['S4', 'K2'],
               14: ['K3', 'K4'], 15: ['K3', 'K4']}


def round4(v):
    return Decimal(str(v)).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)


def validate(power, thermal):
    errs = []
    for r in power:
        m = SERIES[r['series']]
        if r['size'] not in m['sizes']:
            errs.append(f"power {r['series']} size {r['size']} not in manifest")
        if r['ratio'] not in m['ratios']:
            errs.append(f"power {r['series']} ratio {r['ratio']} not in manifest")
    for r in thermal:
        m = SERIES[r['series']]
        if r['size'] not in m['sizes']:
            errs.append(f"thermal {r['series']} size {r['size']} not in manifest")
        lo, hi = r['ratio_iN'].split('..')
        rng = [x for x in m['ratios'] if lo and hi and
               Decimal(str(x)) >= Decimal(lo) and Decimal(str(x)) <= Decimal(hi)]
        if not rng:
            errs.append(f"thermal {r['series']} range {r['ratio_iN']} "
                        f"touches no manifest ratio")
    if errs:
        raise SystemExit('validation failed:\n  ' + '\n  '.join(errs[:20]))


def main():
    power, thermal = extract()
    validate(power, thermal)
    print(f'extracted: power {len(power)}, thermal {len(thermal)}')

    with psycopg.connect(DB) as conn:
        conn.execute('''TRUNCATE import_log, extraction_audit,
                        power_rating, thermal_capacity, actual_ratio,
                        dimension, gear_size, gear_series RESTART IDENTITY
                        CASCADE''')

        # series + sizes
        for code, m in SERIES.items():
            conn.execute(
                'INSERT INTO gear_series (series_code, gear_type) '
                'VALUES (%s, %s) ON CONFLICT (series_code) DO NOTHING',
                (code, m['gear_type']))
            sid = conn.execute(
                'SELECT id FROM gear_series WHERE series_code = %s',
                (code,)).fetchone()[0]
            for sz in m['sizes']:
                conn.execute(
                    'INSERT INTO gear_size (series_id, size) VALUES (%s, %s) '
                    'ON CONFLICT (series_id, size) DO NOTHING',
                    (sid, sz))

        sized = {}
        for code, m in SERIES.items():
            sid = conn.execute(
                'SELECT id FROM gear_series WHERE series_code = %s',
                (code,)).fetchone()[0]
            for sz in m['sizes']:
                gid = conn.execute(
                    'SELECT id FROM gear_size WHERE series_id = %s AND size = %s',
                    (sid, sz)).fetchone()[0]
                sized[(code, sz)] = gid

        def upsert_power(row):
            gid = sized[(row['series'], row['size'])]
            n2 = round4(row['n1'] / float(row['ratio']))
            conn.execute(
                '''INSERT INTO power_rating
                     (gear_size_id, ratio_iN, n1_rpm, n2_rpm,
                      power_kw, requires_forced_lube, source_page)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (gear_size_id, ratio_iN, n1_rpm, n2_rpm)
                   DO NOTHING''',
                (gid, row['ratio'], row['n1'], n2, row['power'],
                 row['forced'], row['page']))

        def upsert_thermal(row):
            gid = sized[(row['series'], row['size'])]
            conn.execute(
                '''INSERT INTO thermal_capacity
                     (gear_size_id, ratio_iN, cooling_type, n1_rpm,
                      amb_temp_c, ed_pct, power_kw, source_page)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (gear_size_id, ratio_iN, cooling_type,
                                n1_rpm, amb_temp_c, ed_pct) DO NOTHING''',
                (gid, row['ratio_iN'], row['cooling'], row['n1'],
                 THERMAL_AMBIENT, THERMAL_ED, row['power'], row['page']))

        seen = defaultdict(int)
        for r in power:
            upsert_power(r)
            seen[(r['series'], r['page'], 'power')] += 1
        for r in thermal:
            upsert_thermal(r)
            seen[(r['series'], r['page'], 'thermal')] += 1

        stored_power = conn.execute(
            'SELECT count(*) FROM power_rating').fetchone()[0]
        stored_thermal = conn.execute(
            'SELECT count(*) FROM thermal_capacity').fetchone()[0]

        stored_src = {}
        for (series, page, section) in seen:
            if section == 'power':
                cnt = conn.execute(
                    '''SELECT count(*) FROM power_rating p
                       JOIN gear_size g ON g.id = p.gear_size_id
                       JOIN gear_series gs ON gs.id = g.series_id
                       WHERE gs.series_code = %s AND p.source_page = %s''',
                    (series, page)).fetchone()[0]
            else:
                cnt = conn.execute(
                    '''SELECT count(*) FROM thermal_capacity t
                       JOIN gear_size g ON g.id = t.gear_size_id
                       JOIN gear_series gs ON gs.id = g.series_id
                       WHERE gs.series_code = %s AND t.source_page = %s''',
                    (series, page)).fetchone()[0]
            stored_src[(series, page, section)] = cnt

        for key, n in seen.items():
            conn.execute(
                '''INSERT INTO extraction_audit
                     (series_code, source_page, section, rows_seen,
                      rows_stored, validated, notes)
                   VALUES (%s,%s,%s,%s,%s,FALSE,%s)''',
                (*key, n, stored_src[key], SOURCE))

        conn.execute(
            '''INSERT INTO import_log (source_file, rows_imported, status)
               VALUES (%s, %s, 'ok')''',
            (SOURCE, stored_power + stored_thermal))

        print(f'stored: power {stored_power}, thermal {stored_thermal}')
        print('import ok')


if __name__ == '__main__':
    main()