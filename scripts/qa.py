"""QA harness: fresh-parse the EON-Series catalog and gate on BOTH the
extraction (parsers/qa_gates.py) and the database (imported rows).

Run:  D:\\gearbox-selector\\.venv\\Scripts\\python.exe scripts\\qa.py
Exit code 0 = all gates pass, 1 = any extraction gate fails
    (the DB section is informational here; see scripts/verify.py for the
     DB-only suite).
"""
import hashlib
import sys
from collections import defaultdict

sys.path.insert(0, r'D:\gearbox-selector')

from parsers.tables import extract, PDF
from parsers.qa_gates import (n2_consistency, mirror_pages, thermal_tiling,
                              forced_flags)

DB = 'postgresql://gearbox:gearbox@localhost:5433/gearbox'


def pdf_fingerprint():
    h = hashlib.sha256()
    with open(PDF, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def reconcile_db(power, thermal):
    """PDF keys vs imported DB keys (both directions)."""
    import psycopg
    pdf_power = {(r['series'], r['size'], r['ratio'], r['n1'])
                 for r in power}
    pdf_th = {(r['series'], r['size'], r['cooling'], r['ratio_iN'])
              for r in thermal}
    issues, notes = [], []
    try:
        with psycopg.connect(DB) as c:
            db_power = set(c.execute(
                "SELECT gs.series_code, sz.size, p.ratio_iN, p.n1_rpm "
                "FROM power_rating p JOIN gear_size sz ON sz.id=p.gear_size_id "
                "JOIN gear_series gs ON gs.id=sz.series_id").fetchall())
            db_th = set(c.execute(
                "SELECT gs.series_code, sz.size, tc.cooling_type, tc.ratio_iN "
                "FROM thermal_capacity tc JOIN gear_size sz ON sz.id=tc.gear_size_id "
                "JOIN gear_series gs ON gs.id=sz.series_id").fetchall())
            notes.append(f'DB: power {len(db_power)}, thermal {len(db_th)} (unique keys)')
    except Exception as e:
        issues.append(f'reconcile: DB unreachable: {e}')
        return issues, notes
    for k in sorted(pdf_power - db_power)[:10]:
        issues.append(f'reconcile: PDF power row missing in DB: {k}')
    for k in sorted(db_power - pdf_power)[:10]:
        issues.append(f'reconcile: DB power row absent from fresh parse: {k}')
    for k in sorted(pdf_th - db_th)[:10]:
        issues.append(f'reconcile: PDF thermal row missing in DB: {k}')
    for k in sorted(db_th - pdf_th)[:10]:
        issues.append(f'reconcile: DB thermal row absent from fresh parse: {k}')
    if len(pdf_power - db_power) > 10:
        issues.append(f'reconcile: ...and {len(pdf_power - db_power) - 10} more')
    if len(pdf_th - db_th) > 10:
        issues.append(f'reconcile: ...and {len(pdf_th - db_th) - 10} more')
    return issues, notes


def main():
    fails, notes = [], []
    fp = pdf_fingerprint()
    notes.append(f'pdf sha256: {fp[:16]}…')

    power, thermal = extract()
    notes.append(f'parse: power {len(power)} rows, thermal {len(thermal)} rows')

    for name, gate, data in (
        ('n2 column self-consistency', n2_consistency, power),
        ('mirror page equality', mirror_pages, power),
        ('thermal ratio tiling', thermal_tiling, thermal),
        ("forced-lube '*' flags", forced_flags, power),
    ):
        issues, stats = gate(data)
        notes.append(f'{name}: {stats} -> '
                     f'{"ok" if not issues else f"{len(issues)} issue(s)"}')
        fails.extend(f'{name}: {i}' for i in issues)

    rec_issues, rec_notes = reconcile_db(power, thermal)
    notes.extend(rec_notes)
    fails.extend(rec_issues)

    print('\n'.join(notes))
    print()
    if fails:
        print('QA FAILURES:')
        print('\n'.join('  - ' + f for f in fails))
        sys.exit(1)
    print('qa: ALL EXTRACTION GATES PASS')
    print('pdf fingerprint: ' + fp)


if __name__ == '__main__':
    main()