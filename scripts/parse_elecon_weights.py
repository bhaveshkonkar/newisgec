"""DEPRECATED - superseded by extract_elecon_weights.py.

The rotated-char approach below only read pages whose glyphs were printed
normally, so it silently skipped the whole S2 and K2 series (their spreads
double every glyph, e.g. 'SS22....1144'), leaving 25 sizes with no weight.

Use `python scripts/extract_elecon_weights.py --strict --write` instead; it
handles the doubled glyphs and writes elecon_weights.json. This module is kept
for reference only and refuses to overwrite that file.
"""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

import pdfplumber

SUPERSEDED = "superseded by scripts/extract_elecon_weights.py (run with --write)"

PDF = Path(r'D:\gearbox-selector\data\catalog\Elecon G B_EON-Series.pdf')
FIRST_PAGE, LAST_PAGE = 18, 76

SIZE_RE = re.compile(r'^([SK])(\d)\.\.(\d+)$')
NUM_RE = re.compile(r'^\d+(\.\d+)?$')
X_TOL = 14.0      # +-pt window around a column header x
ROW_TOL = 6.0     # +-pt window for "same text row"
GAP_TOL = 16.0    # max vertical gap still considered the same data table
SIDE_LO, SIDE_HI = 150.0, 430.0   # size label sits this far left of weight col


def _rotated_header_xs(page) -> list[tuple[float, float, float]]:
    """(weight_x, oil_x, header_bottom) for every rotated weight header."""
    clusters: dict[int, list] = defaultdict(list)
    for ch in page.chars:
        if not ch.get('upright', True):
            clusters[round(ch['x0'])].append(ch)

    weight = []
    for x, chars in clusters.items():
        txt = ''.join(c['text'] for c in sorted(chars, key=lambda c: -c['top']))
        if 'AverageWeight' not in txt.replace(' ', ''):
            continue
        top = min(c['top'] for c in chars)
        bottom = max(c['bottom'] for c in chars)
        # the oil header sits just to the right of the weight header
        oil_x = None
        for ox, ochars in clusters.items():
            otxt = ''.join(c['text'] for c in
                           sorted(ochars, key=lambda c: -c['top']))
            if 'OilQuantity' not in otxt.replace(' ', ''):
                continue
            if abs(ox - x) <= X_TOL:
                oil_x = float(ox)
                break
        weight.append((float(x), oil_x, bottom))
    return weight


TYPE_RE = re.compile(r'^([SK]\d)([A-Z]{1,3})$')


def _variant_labels(page) -> list[tuple[float, str, str]]:
    """(x0, series, variant) for each 'S4H' / 'K3T' style type caption."""
    out = []
    for w in page.extract_words():
        m = TYPE_RE.match(w['text'])
        if m:
            out.append((w['x0'], m.group(1), m.group(2)))
    return out


def _variant_for(labels, wx: float, series: str) -> str:
    """Nearest caption on the same half of the page names the variant."""
    cands = [l for l in labels if l[1] == series]
    if not cands:
        return 'H'
    x0, _, variant = min(cands, key=lambda l: abs(l[0] - wx))
    return variant


def parse_page(page, page_no: int) -> list[dict]:
    headers = _rotated_header_xs(page)
    if not headers:
        return []
    labels = _variant_labels(page)

    words = page.extract_words()
    size_words = [w for w in words if SIZE_RE.match(w['text'])]
    num_words = [w for w in words if NUM_RE.match(w['text'])]
    if not size_words or not num_words:
        return []

    out = []
    for wx, ox, header_bottom in headers:
        # the data table belonging to this header is the first contiguous run
        # of rows below it (the Foundation table further down reuses this x)
        rows: dict[float, list] = {}
        for w in num_words:
            if abs(w['x0'] - wx) <= X_TOL and w['top'] > header_bottom:
                rows.setdefault(round(w['top']), []).append(w)
        if not rows:
            continue
        tops = sorted(rows)
        run = [tops[0]]
        for t in tops[1:]:
            if t - run[-1] <= GAP_TOL:
                run.append(t)
            else:
                break

        for t in run:
            size_w = [w for w in size_words
                      if abs(w['top'] - t) <= ROW_TOL
                      and SIDE_LO <= (wx - w['x0']) <= SIDE_HI]
            if not size_w:
                continue
            sw = min(size_w, key=lambda w: abs(wx - w['x0']))
            m = SIZE_RE.match(sw['text'])
            series = m.group(1) + m.group(2)
            wt = float(min(rows[t], key=lambda w: abs(w['x0'] - wx))['text'])
            oil = None
            if ox is not None:
                oc = [w for w in num_words
                      if abs(w['x0'] - ox) <= X_TOL and abs(w['top'] - t) <= ROW_TOL]
                if oc:
                    oil = float(min(oc, key=lambda w: abs(w['x0'] - ox))['text'])
            out.append({'series': series,
                        'series_no': m.group(2), 'size': m.group(3),
                        'variant': _variant_for(labels, wx, series),
                        'weight_kg': wt, 'oil_l': oil, 'page': page_no})
    return out


def main() -> int:
    rows: list[dict] = []
    with pdfplumber.open(PDF) as pdf:
        for pno in range(FIRST_PAGE, min(LAST_PAGE, len(pdf.pages)) + 1):
            page = pdf.pages[pno - 1]
            try:
                got = parse_page(page, pno)
            except Exception as exc:            # keep going on odd layouts
                print(f'  ! page {pno}: {exc}', file=sys.stderr)
                continue
            if got:
                rows.extend(got)
                print(f'page {pno}: {len(got):2d} sizes  '
                      f'{got[0]["series"]}..{got[0]["size"]} .. '
                      f'{got[-1]["series"]}..{got[-1]["size"]}')

    # newest page wins for a duplicated series/size/variant
    merged: dict[tuple[str, str, str], dict] = {}
    for r in sorted(rows, key=lambda r: r['page']):
        merged[(r['series'], r['size'], r['variant'])] = r

    print(f'\n=== {len(merged)} series/size/variant weights parsed '
          f'({len(rows)} raw rows) ===')
    by_series: dict[str, dict[str, list[dict]]] = defaultdict(dict)
    for r in merged.values():
        by_series[r['series']].setdefault(r['variant'], []).append(r)
    for series in sorted(by_series, key=lambda s: (s[0], int(s[1:]))):
        for variant in sorted(by_series[series]):
            items = sorted(by_series[series][variant],
                           key=lambda r: int(r['size']))
            shown = ', '.join(f"{i['size']}={i['weight_kg']:g}kg"
                              + (f"/{i['oil_l']:g}L" if i['oil_l'] else '')
                              for i in items)
            print(f'  {series}-{variant}: {shown}')

    out = Path(__file__).resolve().parent / 'elecon_weights.json'
    if out.exists() and '--force' not in sys.argv:
        import json
        print(f'NOT writing {out}: {SUPERSEDED} '
              f'(delete it first or pass --force)',
              file=sys.stderr)
        return 1
    import json
    out.write_text(json.dumps(
        [{'series': r['series'], 'size': r['size'],
          'variant': r['variant'], 'weight_kg': r['weight_kg'],
          'oil_l': r['oil_l'], 'page': r['page']}
         for r in merged.values()], indent=1), encoding='utf-8')
    print(f'\nwrote {out}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
