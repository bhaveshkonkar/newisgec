"""Import the Elecon quotation/price list xlsx into Postgres.

  - price_quote : raw log rows (K/S series positions)
  - model_price : per-model unit-price card (most recent quote wins)

Run:  D:\\gearbox-selector\\.venv\\Scripts\\python.exe scripts\\import_prices.py
"""
import re
import sys
from decimal import Decimal

sys.path.insert(0, r'D:\gearbox-selector')

import openpyxl
import psycopg

SRC = r'C:\Users\konka\Downloads\Gearbox Price list (1).xlsx'
DB = 'postgresql://gearbox:gearbox@localhost:5433/gearbox'

K_SERIES = re.compile(r'^(K|S)\d')


def _num(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if not s:
        return None
    return float(s)


def _weight(v):
    if v is None:
        return None
    m = re.match(r'^[\d.]+', str(v).strip())
    return float(m.group()) if m else None


def main():
    wb = openpyxl.load_workbook(SRC, data_only=True, read_only=True)
    rows = list(wb['GearBOX '].iter_rows(values_only=True))

    quotes = []
    for r in rows[5:]:
        model = str(r[11]).strip() if r[11] else None
        if not model or not K_SERIES.match(model):
            continue
        price = _num(r[13])
        quotes.append({  # col1..col14 -> sn, project, code, kw, rpm, gr,
            # type, hb, cooling, lube, sf, model, weight, price
            'sn': _num(r[0]),
            'project': str(r[1]).strip() if r[1] else None,
            'billing': str(r[2]).strip() if r[2] else None,
            'kw': _num(r[3]),
            'rpm': _num(r[4]),
            'gr': str(r[5]).strip() if r[5] else None,
            'gtype': str(r[6]).strip() if r[6] else None,
            'hb': str(r[7]).strip() if r[7] else None,
            'cooling': str(r[8]).strip() if r[8] else None,
            'lube': str(r[9]).strip() if r[9] else None,
            'sf': _num(r[10]),
            'model': model,
            'weight': _weight(r[12]),
            'price': price,
        })

    with psycopg.connect(DB) as conn:
        conn.execute('TRUNCATE price_quote, model_price RESTART IDENTITY')
        for q in quotes:
            conn.execute('''INSERT INTO price_quote
                (sn, project, billing_code, kw, rpm, gr, gear_type, hb,
                 cooling, lubrication, sf, model_code, weight_kg,
                 gearbox_price, source_file)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                (q['sn'], q['project'], q['billing'], q['kw'], q['rpm'],
                 q['gr'], q['gtype'], q['hb'], q['cooling'], q['lube'],
                 q['sf'], q['model'], q['weight'], q['price'], SRC))

        # most-recent quote price per model (higher = later quote)
        rows = conn.execute('''
            SELECT model_code, max(gearbox_price), count(*)
              FROM price_quote
             WHERE gearbox_price IS NOT NULL
             GROUP BY model_code''').fetchall()
        for model, price, n in rows:
            conn.execute('''INSERT INTO model_price (model_code, unit_price_inr, n_quotes)
                VALUES (%s,%s,%s) ON CONFLICT (model_code) DO UPDATE
                SET unit_price_inr = EXCLUDED.unit_price_inr''',
                (model, Decimal(str(price)), n))

        nq = conn.execute('SELECT count(*) FROM price_quote').fetchone()[0]
        np = conn.execute('SELECT count(*) FROM model_price').fetchone()[0]
        print(f'price_quote {nq}, model_price {np}')


if __name__ == '__main__':
    main()