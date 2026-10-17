"""Extract the principal-dimension tables Premium prints for each unit type.

The Premium DIMENSIONS section comes in two-page pairs. The first page
("... PrincipalDimensions(mm) 1of2") carries two clean tables per unit type:

  * the housing/overall table, headed A B C D E F G H J K(K1 K2) L M N P ...
  * the shaft/bore table, headed P1 Q R S T U U1 V V1 V3 V4 W W1 ...

Both are located from the header row (the row that carries the "Unit Size"
words) and read with the same word-position logic as the Elecon extractor:
each numeric token is assigned to the column whose header centre its own centre
is nearest, so a row where the catalogue omits a cell (prints "-") or where a
rotated callout lands in the table still keeps every surviving number in the
right column.  Rotated drawing text is dropped outright (upright == False).

Column names come from the header's own letters -- duplicates get a numeric
suffix -- the housing table is stored under found_* and the shaft table under
shaft_* so the reasoning layer renders them as "foundation" / "shafts".

The second page of each pair ("... 2of2") prints shaft/keyway details as
tolerance lines ("45.018 ... 45.002 ...") that would mis-align a positional
parse, and the motorised (p53-54) and vertical VH/VB (p55-62) pages use
different layouts, so none of those are parsed here.

Run:  python scripts/extract_premium_dimensions.py --json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import pdfplumber

HERE = Path(__file__).resolve().parent
PDF = (HERE.parent / 'data' / 'uploads'
       / '00000000-0000-0000-0000-000000000001'
       / 'Premium_helical_gearboxes_catalogue.pdf')
FIRST_PAGE, LAST_PAGE = 27, 52            # principal (1of2) pages only
TITLE_RE = re.compile(r'Type\s+([A-Z]\d+)\s*(SF)?', re.I)
LABEL_RE = re.compile(r'^[A-Za-z]+\d*\*?$')
NUM_RE = re.compile(r'^-?\d+(?:\.\d+)?$')
INT_RE = re.compile(r'^\d+$')
ROW_TOL = 3.0


def series_of(title: str) -> tuple[str, str] | None:
    m = TITLE_RE.search(title)
    if not m:
        return None
    series = m.group(1).upper()
    sf = bool(m.group(2)) or 'shaft' in title.lower()
    return series, ('foot_shaft' if sf else 'foot')


def unique(names: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out: list[str] = []
    for raw in names:
        name = raw.rstrip('*')
        seen[name] = seen.get(name, 0) + 1
        out.append(name if seen[name] == 1 else f'{name}_{seen[name]}')
    return out


def cluster_rows(words: list[dict]) -> list[tuple[float, list[dict]]]:
    rows: list[tuple[float, list[dict]]] = []
    for w in sorted(words, key=lambda w: w['top']):
        if rows and abs(w['top'] - rows[-1][0]) <= ROW_TOL:
            rows[-1][1].append(w)
        else:
            rows.append((w['top'], [w]))
    return [(top, sorted(ws, key=lambda w: w['x0'])) for top, ws in rows]


def centre(w: dict) -> float:
    return (w['x0'] + w['x1']) / 2


def is_header(ws: list[dict]) -> bool:
    joined = re.sub(r'[^a-z]', '', ''.join(w['text'] for w in ws).lower())
    return 'unitsize' in joined or 'unitssize' in joined


def header_columns(ws: list[dict]) -> list[tuple[str, float]] | None:
    cols: list[tuple[str, float]] = []
    for w in ws:
        text = w['text'].strip()
        if text.lower() in {'unit', 'size', 'units', 'unitssize'}:
            continue
        if LABEL_RE.match(text):
            cols.append((text.rstrip('*'), centre(w)))
    return cols or None


def bands(cols: list[tuple[str, float]]) -> list[tuple[float, float]]:
    centers = [c for _, c in cols]
    if len(centers) == 1:
        return [(centers[0] - 10, centers[0] + 10)]
    edges = [centers[0] - (centers[1] - centers[0])]
    edges += [(a + b) / 2 for a, b in zip(centers, centers[1:])]
    edges.append(centers[-1] + (centers[-1] - centers[-2]))
    return list(zip(edges, edges[1:]))


def extract_page(page, page_no: int) -> list[dict]:
    title = next((ln.strip() for ln in (page.extract_text() or '').split('\n')
                  if ln.strip()), '')
    meta = series_of(title)
    if not meta:
        return []
    series, mounting = meta
    words = [w for w in page.extract_words(x_tolerance=1.5, y_tolerance=2)
             if w.get('upright', True)]
    rows = cluster_rows(words)
    out: list[dict] = []
    cols: list[tuple[str, float]] | None = None
    names: list[str] = []
    bnds: list[tuple[float, float]] = []
    table_idx = -1
    for _, ws in rows:
        if is_header(ws):
            table_idx += 1
            found = header_columns(ws)
            if not found:
                cols = None
                continue
            names = unique([n for n, _ in found])
            bnds = bands(found)
            first_x = found[0][1]
            cols = found
            continue
        if cols is None:
            continue
        size_word = ws[0]
        if not INT_RE.match(size_word['text']):
            continue
        if int(size_word['text']) < 100:
            continue
        if centre(size_word) >= first_x:          # not in the size column
            continue
        dims: dict[str, float] = {}
        prefix = 'found_' if table_idx == 0 else 'shaft_'
        for w in ws[1:]:
            if not NUM_RE.match(w['text']):
                continue
            cx = centre(w)
            idx = next((i for i, (lo, hi) in enumerate(bnds) if lo <= cx < hi),
                       None)
            if idx is None or idx >= len(names):
                continue
            dims[prefix + names[idx]] = float(w['text'])
        if not dims:
            continue
        out.append({'series': series, 'mounting': mounting,
                    'table': 'found' if table_idx == 0 else 'shaft',
                    'size': size_word['text'], 'page': page_no, 'dims': dims})
    return out


def extract() -> list[dict]:
    if not PDF.exists():
        print(f'PDF not found: {PDF}', file=sys.stderr)
        return []
    found: list[dict] = []
    with pdfplumber.open(PDF) as pdf:
        for pi in range(FIRST_PAGE - 1, min(LAST_PAGE, len(pdf.pages))):
            text = pdf.pages[pi].extract_text() or ''
            blob = re.sub(r'\s+', '', text).lower()
            if 'princip' not in blob or '2of2' in blob:
                continue
            found.extend(extract_page(pdf.pages[pi], pi + 1))
    return found


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--json', action='store_true', help='emit JSON')
    ap.add_argument('--write', action='store_true',
                    help='rewrite premium_dimensions.json from the parse')
    args = ap.parse_args()

    rows = extract()
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0

    stacked: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for r in rows:
        stacked[(r['series'], r['mounting'], r['size'])].append(r)
    n_found = sum(1 for r in rows if r['table'] == 'found')
    n_shaft = sum(1 for r in rows if r['table'] == 'shaft')
    print(f'{len(rows)} rows ({n_found} found, {n_shaft} shaft) across '
          f'{len(stacked)} series/mounting/size keys')
    last = ''
    for key in sorted(stacked, key=lambda k: (k[0], k[1], int(k[2]))):
        series, mounting, size = key
        if series != last:
            print(f'\n  {series}:')
            last = series
        r = stacked[key][0]
        sample = ', '.join(f'{k}={v:g}' for k, v in sorted(r['dims'].items())[:8])
        pages = ','.join(sorted({str(x['page']) for x in stacked[key]}))
        print(f'   {mounting} {size} (p{pages}): {len(r["dims"])} e.g. {sample}')

    if args.write:
        out = HERE / 'premium_dimensions.json'
        out.write_text(json.dumps(rows, indent=1), encoding='utf-8')
        print(f'wrote {out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
