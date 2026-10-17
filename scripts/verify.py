"""Post-import verification: golden datapoints, manifest completeness,
   monotonicity of the power surface (size & ratio), thermal sanity.

Run:  D:\\gearbox-selector\\.venv\\Scripts\\python.exe scripts\\verify.py
Exit code 0 = all gates pass, 1 = any gate fails.
"""
import sys
from decimal import Decimal

sys.path.insert(0, r'D:\gearbox-selector')

import psycopg
from parsers.manifest import SERIES

DB = 'postgresql://gearbox:gearbox@localhost:5433/gearbox'
N1 = 1500

GOLD_POWER = [
    ('S1', '11', '1.25', '84'),
    ('S2', '26', '22.4', '850'),
    ('S3', '26', '112', '183'),
    ('S4', '26', '560', '33'),
    ('K2', '26', '22.4', '579'),
    ('K3', '26', '25', '701'),
    ('K4', '26', '225', '90'),
]

GOLD_THERMAL = [
    ('K3', '26', 'none', '20..35.5', '330'),
    ('K3', '26', 'fan', '20..35.5', '672'),
    ('K3', '26', 'fan', '40..100', '620'),
    ('K3', '26', 'coil', '20..100', '584'),
    ('K3', '26', 'fan_coil', '20..100', '1141'),
    ('S2', '26', 'fan', '5.6..14', '976'),
    ('K2', '26', 'none', '12.5..22.4', '527'),
]

GOLD_FORCED = [('K3', '26', '25', True)]


# Source-faithful inversions verified against raw PDF text (page 14,
# K4 block, size column x=1004.7): the catalog itself prints these.
# selection-engine input is still monotone-safe because ratios are
# looked up by exact nominal class.
KNOWN_SRC_INVERSIONS = {
    ('K4', '23', '112', '125'),   # prints 59 then 64
    ('K4', '23', '200', '225'),   # prints 33 then 36
}


def q(conn, sql, args=()):
    return conn.execute(sql, args).fetchall()


def main():
    fails, notes = [], []
    with psycopg.connect(DB) as conn:
        # --- golden power rows
        for series, size, ratio, expect in GOLD_POWER:
            got = q(conn, '''
                SELECT p.power_kw, p.requires_forced_lube
                FROM power_rating p
                JOIN gear_size g ON g.id = p.gear_size_id
                JOIN gear_series gs ON gs.id = g.series_id
                WHERE gs.series_code = %s AND g.size = %s
                  AND p.ratio_iN = %s AND p.n1_rpm = %s''',
                (series, size, ratio, N1))
            pw = got[0][0] if got else None
            fixed = got[0][1] if got else None
            if pw is None or Decimal(str(pw)) != Decimal(expect):
                fails.append(f'POWER golden {series}-{size} iN={ratio} '
                             f'@{N1}: expect {expect}, got {pw}')
            for s, z, r, want_forced in GOLD_FORCED:
                if series == s and size == z and ratio == r and fixed != want_forced:
                    fails.append(f'POWER forced-lube flag {series}-{z} '
                                 f'iN={r}: expect {want_forced}, got {fixed}')
            notes.append(f'power golden ok: {series}-{size} iN={ratio} = {pw} kW')

        # --- golden thermal rows (rated at 20C, ed 100)
        for series, size, cool, rng, expect in GOLD_THERMAL:
            got = q(conn, '''
                SELECT t.power_kw FROM thermal_capacity t
                JOIN gear_size g ON g.id = t.gear_size_id
                JOIN gear_series gs ON gs.id = g.series_id
                WHERE gs.series_code = %s AND g.size = %s
                  AND t.cooling_type = %s AND t.ratio_iN = %s
                  AND t.n1_rpm = %s AND t.amb_temp_c = 20 AND t.ed_pct = 100''',
                (series, size, cool, rng, N1))
            pw = got[0][0] if got else None
            if pw is None or Decimal(str(pw)) != Decimal(expect):
                fails.append(f'THERMAL golden {series}-{size} [{cool}] '
                             f'{rng} @{N1}: expect {expect}, got {pw}')
            notes.append(f'thermal golden ok: {series}-{size} [{cool}] '
                         f'{rng} = {pw} kW')

        # --- manifest completeness: every series has all sizes & ratios
        for code, m in SERIES.items():
            sizes = q(conn, '''
                SELECT g.size FROM gear_size g
                JOIN gear_series gs ON gs.id = g.series_id
                WHERE gs.series_code = %s ORDER BY g.size''', (code,))
            db_sizes = [x[0] for x in sizes]
            if db_sizes != m['sizes']:
                fails.append(f'SIZES {code}: manifest {m["sizes"]} '
                             f'vs db {db_sizes}')

        # --- monotonicity: power not decreasing in ratio then in size
        for code in SERIES:
            rows = q(conn, '''
                SELECT g.size, p.ratio_iN, p.power_kw
                FROM power_rating p
                JOIN gear_size g ON g.id = p.gear_size_id
                JOIN gear_series gs ON gs.id = g.series_id
                WHERE gs.series_code = %s AND p.n1_rpm = %s
                  AND p.requires_forced_lube = FALSE
                ORDER BY g.size''', (code, N1))
            by_size = {}
            for size, ratio, pw in rows:
                by_size.setdefault(size, {})[str(ratio)] = Decimal(str(pw))
            ratios = sorted(SERIES[code]['ratios'],
                            key=lambda r: Decimal(str(r)))
            bad, quirks, known = 0, 0, 0
            for size in by_size:
                pairs = [(r, by_size[size][r]) for r in ratios
                         if by_size[size].get(r) is not None]
                for (r1, v1), (r2, v2) in zip(pairs, pairs[1:]):
                    if v2 > v1:
                        bump = v2 - v1
                        tol = max(Decimal('2'), v2 * Decimal('0.02'))
                        if bump > tol:
                            if (code, size, r1, r2) in KNOWN_SRC_INVERSIONS:
                                known += 1
                            else:
                                bad += 1
                        else:
                            quirks += 1
            if bad:
                fails.append(f'MONO {code}: {bad} large ratio-inversions '
                             f'(>2kW or 2%)')
            sizes_sorted = sorted(
                (Decimal(sz) if sz.isdigit() else sz)
                for sz in by_size) if by_size else []
            cross_bad = 0
            for i in range(1, len(sizes_sorted)):
                a, b = sizes_sorted[i - 1], sizes_sorted[i]
                sa, sb = str(a), str(b)
                for ratio in ratios:
                    va, vb = (by_size.get(sa, {}).get(ratio),
                              by_size.get(sb, {}).get(ratio))
                    if va is not None and vb is not None and vb < va:
                        cross_bad += 1
            if cross_bad:
                fails.append(f'MONO {code}: {cross_bad} size-pairs '
                             f'non-monotonic in size')
            notes.append(f'mono ok: {code} '
                         f'({len(by_size)} sizes, {len(ratios)} ratios, '
                         f'{quirks} small source-rounding quirks)')

        # --- thermal row counts sanity
        tp = q(conn, 'SELECT count(*) FROM thermal_capacity')[0][0]
        pk = q(conn, 'SELECT count(*) FROM power_rating')[0][0]
        if pk < 3000 or tp < 1000:
            fails.append(f'row counts off: power {pk}, thermal {tp}')
        notes.append(f'totals: power {pk}, thermal {tp}')

    print('\n'.join(notes))
    if fails:
        print('\nFAILURES:')
        print('\n'.join('  - ' + f for f in fails))
        sys.exit(1)
    print('verify: ALL GATES PASS')


if __name__ == '__main__':
    main()