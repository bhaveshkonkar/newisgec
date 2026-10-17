"""Geometry-based extraction of the EON-Series power & thermal tables.

Layout facts exploited (verified with word-level dumps on pages 8 & 14):
  * power header 'i N n1 n2' + sizes row, then ratio groups of 3 rows
    (1500 / 1000 / 750 rpm). The ratio token is on its own line vertically
    centred against the group (approx on the 1000-row).
  * thermal header 'Transmission n1' + sizes row, then P1..P4 sections each
    preceded by a 'Thermal Capacity P ...(kW)...' caption line; each group
    carries an 'a to b' ratio-range caption landing on the 1000-row.
  * blank cells are *not printed* -> nearest-column-centre assignment leaves
    them NULL naturally.
  * two tables share a page side-by-side (interleaved by y) -> every token is
    assigned to the nearest anchor across all detected blocks on the page,
    which cleanly partitions left/right tables.
"""
import re

from parsers.geometry import (center, group_lines, is_num, num_val, is_starred,
                              detect_blocks)
from parsers.manifest import (SERIES, SERIES_POWER_PAGES, COOLING_BY_CAPTION,
                              THERMAL_PAGE, THERMAL_ED)

PDF = r'D:\gearbox-selector\data\catalog\Elecon G B_EON-Series.pdf'
RANGE_RE = re.compile(r'(\d+(?:\.\d+)?)\s*to\s*(\d+(?:\.\d+)?)')


def _nearest(anchor_list, x):
    """anchor_list = [(blk_index, kind, center)] -> (blk_index, kind)."""
    return min(anchor_list, key=lambda t: abs(x - t[2]))[:2]


def _row_groups(recs):
    """Split a block's n1-row stream into strict 1500/1000/750 triples."""
    recs.sort(key=lambda r: r['top'])
    groups, cur = [], []
    for r in recs:
        if r['n1'] == 1500:
            if cur:
                groups.append(cur)
            cur = []
        cur.append(r)
    if cur:
        groups.append(cur)

    out = []
    for g in groups:
        n1s = [r['n1'] for r in g]
        if n1s != [1500, 1000, 750]:
            raise ValueError(f'bad rpm group {n1s}')
        mid = sum(r['top'] for r in g) / 3.0
        rng = None
        for r in g:
            if r['n1'] == 1000:
                m = RANGE_RE.search(r.get('raw', r['text']))
                if m:
                    rng = (m.group(1), m.group(2))
        out.append({'ratio': None, 'rng': rng, 'mid': mid,
                    'rows': g})
    return out


def _data_records(page, page_no, wanted_series):
    lines = group_lines(page)
    blocks = detect_blocks(lines)

    powers = [b for b in blocks if b.kind == 'power']
    thermals = [b for b in blocks if b.kind == 'thermal']
    if len(powers) != len(thermals):
        raise ValueError(f'page {page_no}: power({len(powers)}) != thermal({len(thermals)}) blocks')
    if len(powers) != len(wanted_series):
        raise ValueError(f'page {page_no}: got {len(powers)} power blocks, '
                         f'{wanted_series} expected')
    for b, s in zip(powers, wanted_series):
        b.series = s
    for b, s in zip(thermals, wanted_series):
        b.series = s

    anchor_list = []
    for bi, b in enumerate(blocks):
        for k, x in (('iN', b.iN_anchor), ('n1', b.n1_anchor), ('n2', b.n2_anchor)):
            if x is not None:
                anchor_list.append((bi, k, x))
        for i, (sz, xc) in enumerate(b.sizes):
            anchor_list.append((bi, f'sz:{i}', xc))

    # thermal section captions -> (top, cooling, x0, x1)
    # caption x-extent comes from the caption keywords only, so a line that
    # mixes one table's data with the other table's caption stays scoped.
    CKW = {'thermal', 'capacity', 'fan', 'coil', 'cooling', 'with',
           'without', 'for', 'gear', 'unit'}
    captions = []
    for li, ln in enumerate(lines):
        words = [w['text'] for w in ln['words']]
        if 'Thermal' in words and 'Capacity' in words and 'P' in words:
            jt = ' '.join(words).lower()
            if 'fan and' in jt:
                cooling = 'fan_coil'
            elif 'cooling coil' in jt:
                cooling = 'coil'
            elif 'fan' in jt:
                cooling = 'fan'
            else:
                cooling = 'none'
            kw = [w for w in ln['words'] if w['text'].lower() in CKW]
            c0 = min(w['x0'] for w in kw)
            c1 = max(w['x1'] for w in kw)
            captions.append((ln['top'], cooling, c0, c1))
    captions.sort()

    def section_for(b, top):
        cool = 'none'
        xs0, xs1 = b.sizes[0][1], b.sizes[-1][1]
        for c_top, cooling, c0, c1 in captions:
            if c_top >= top:
                break
            if c0 <= xs1 and c1 >= xs0:
                cool = cooling
        return cool

    # per-table vertical bands, used to break anchor x-ties (p8 power & thermal
    # share the exact same size-column x, so the y-band decides which table).
    # A band only ends at the next block that OVERLAPS the same size x-range
    # (side-by-side tables like K3/K4 interleave at the same y and must not
    # truncate each other).
    by_row = sorted(blocks, key=lambda b: b.sizes_idx)
    band_end = {}
    for j, b in enumerate(by_row):
        xa = (b.sizes[0][1], b.sizes[-1][1])
        end = 1e9
        for o in by_row:
            if o is b or o.sizes_idx <= b.sizes_idx:
                continue
            xb = (o.sizes[0][1], o.sizes[-1][1])
            if xa[0] <= xb[1] and xb[0] <= xa[1]:
                end = min(end, lines[o.sizes_idx]['top'])
        band_end[id(b)] = end

    def band_of(top):
        for b in by_row:
            if lines[b.sizes_idx]['top'] <= top < band_end[id(b)]:
                return [i for i, x in enumerate(blocks) if x is b][0]
        return None

    def band_has(bi, top):
        b = blocks[bi]
        return lines[b.sizes_idx]['top'] <= top < band_end[id(b)]

    def wb_nearest(x, top, near=4.0):
        """nearest anchor, breaking cross-block ties via the candidate's OWN
        y-band.  power & thermal tables of the same series share size x but
        their column centres can drift ~1-2pt, so a token that lands close to
        two blocks' anchors must go to whichever block's band holds its row."""
        best = (None, None)
        best_d = None
        tied = []
        for t in anchor_list:
            d = abs(x - t[2])
            if best_d is None or d < best_d - 0.5:
                best_d, best, tied = d, t[:2], [t[:2]]
            elif abs(d - best_d) <= 0.5:
                tied.append(t[:2])
        if len(tied) > 1:
            for (bi2, k2) in tied:
                if bi2 is not None and band_has(bi2, top):
                    return (bi2, k2)
        if best[0] is not None and band_has(best[0], top):
            return best
        alt = None
        for t in anchor_list:
            d = abs(x - t[2])
            if d <= best_d + near:
                bi2, k2 = t[:2]
                if (bi2 != best[0] and bi2 is not None and band_has(bi2, top)
                        and (alt is None or d < alt[0])):
                    alt = (d, (bi2, k2))
        if alt:
            return alt[1]
        return best

    # partition data-area lines by table, then per-table cluster into rows
    area_start = min(b.sizes_idx for b in blocks) + 1
    sub = {}          # block index -> [(li, top, words), ...]
    cands = {i: [] for i in range(len(blocks))}
    for li in range(area_start, len(lines)):
        ln = lines[li]
        numerics = [w for w in ln['words'] if is_num(w['text'])]
        if not numerics:
            continue
        parts = {}
        for w in numerics:
            bi, k = wb_nearest(center(w), ln['top'])
            parts.setdefault(bi, []).append(w)
            if k == 'iN':
                cands[bi].append((w['top'], w['text']))
        for bi, ws in parts.items():
            sub.setdefault(bi, []).append((li, ln['top'], ws))

    def raw_near(top):
        parts = []
        for li in range(area_start, len(lines)):
            if abs(lines[li]['top'] - top) <= 4.0:
                parts.append(' '.join(w['text'] for w in lines[li]['words']))
        return ' | '.join(parts)

    for bi, b in enumerate(blocks):
        items = sub.get(bi, [])
        items.sort(key=lambda it: it[1])
        rows = []
        for li, top, ws in items:
            if rows and top - rows[-1]['top'] <= 3.0:
                rows[-1]['words'].extend(ws)
                rows[-1]['lines'].add(li)
            else:
                rows.append({'top': top, 'words': list(ws),
                             'lines': {li}})
        for r in rows:
            r['words'].sort(key=lambda w: (w['x0'], w['x1']))
            r['raw'] = raw_near(r['top'])
            r['text'] = ' '.join(w['text'] for w in r['words'])
            r['n1'] = None
            r['n2'] = None
            r['vals'] = {}
            for w in r['words']:
                t = w['text']
                bi2, k = wb_nearest(center(w), r['top'])
                if bi2 != bi:
                    continue
                if k == 'n1' and t in ('1500', '1000', '750'):
                    r['n1'] = int(t)
                elif k == 'n2':
                    r['n2'] = num_val(t)
                elif k.startswith('sz:'):
                    _cx0, _cx1 = w['x0'], w['x1']
                    r['vals'][int(k.split(':')[1])] = (num_val(t), is_starred(t), _cx0, _cx1)
        sub[bi] = [r for r in rows if r['n1']]

    power_records, thermal_records = [], []
    for bi, b in enumerate(blocks):
        triples = _row_groups(sub[bi])
        if b.kind == 'power':
            for t in triples:
                ratio = None
                for c_top, c_text in sorted(cands[bi], key=lambda c: abs(c[0] - t['mid'])):
                    ratio = c_text
                    break
                for g in t['rows']:
                    for i, (val, starred, cx0, cx1) in g.get('vals', {}).items():
                        size = b.sizes[i][0]
                        n2 = g.get('n2') if g.get('n2') else None
                        power_records.append({
                            'series': b.series, 'size': size, 'ratio': ratio,
                            'n1': g['n1'], 'n2': n2, 'power': val,
                            'forced': starred, 'page': page_no,
                            'raw': g.get('raw', ''), 'top': g.get('top', 0.0),
                            'cx0': cx0, 'cx1': cx1,
                        })
        else:
            for t in triples:
                cooling = section_for(b, t['mid'])
                if t['rng'] is None:
                    text = ' | '.join(r['text'] for r in t['rows'])
                    raise ValueError(f'page {page_no} {b.series}: missing ratio range: {text}')
                ratio_iN = f"{t['rng'][0]}..{t['rng'][1]}"
                for g in t['rows']:
                    for i, (val, starred, _cx0, _cx1) in g.get('vals', {}).items():
                        size = b.sizes[i][0]
                        thermal_records.append({
                            'series': b.series, 'size': size,
                            'ratio_iN': ratio_iN, 'cooling': cooling,
                            'n1': g['n1'], 'power': val, 'page': page_no,
                        })
    return power_records, thermal_records


def extract(pages=None):
    from pdfplumber import open as _open
    if pages is None:
        pages = sorted(SERIES_POWER_PAGES)
    power_all, thermal_all = [], []
    with _open(PDF) as pdf:
        for pno in pages:
            page = pdf.pages[pno - 1]
            pr, tr = _data_records(page, pno, SERIES_POWER_PAGES[pno])
            power_all.extend(pr)
            thermal_all.extend(tr)
    return power_all, thermal_all


if __name__ == '__main__':
    pwr, thm = extract()
    print(f'pages 8-15 -> power rows: {len(pwr)}, thermal rows: {len(thm)}')
    for r in [x for x in pwr if x['series'] == 'K3' and x['ratio'] == '25'
              and x['size'] == '26' and x['n1'] == 1500]:
        print('K3-26 iN=25 1500rpm ->', r['power'], 'kW',
              'forced_lube' if r['forced'] else '')

    print('\n-- manifest cross-check (power) --')
    by = {}
    for r in pwr:
        by.setdefault(r['series'], {'sizes': set(), 'ratios': set()})
        by[r['series']]['sizes'].add(r['size'])
        by[r['series']]['ratios'].add(r['ratio'])
    for s, meta in SERIES.items():
        got = by.get(s)
        if got is None:
            print(f'{s}: MISSING entirely')
            continue
        ms, mr = set(meta['sizes']), set(meta['ratios'])
        mmiss = ms - got['sizes']
        rmiss = mr - got['ratios']
        rextra = got['ratios'] - mr
        print(f"{s}: sizes ok={'no' if mmiss else 'yes'}"
              f"{f' MISSING {sorted(mmiss)}' if mmiss else ''} | "
              f"ratios ok={'no' if rmiss else 'yes'}"
              f"{f' MISSING {sorted(rmiss)}' if rmiss else ''}"
              f"{f' EXTRA {sorted(rextra)}' if rextra else ''}")

    print('\n-- manifest cross-check (thermal) --')
    tr = {}
    for r in thm:
        tr.setdefault((r['series'], r['cooling']),
                      {'ranges': set(), 'sizes': set()})
        tr[(r['series'], r['cooling'])]['ranges'].add(r['ratio_iN'])
        tr[(r['series'], r['cooling'])]['sizes'].add(r['size'])
    for k in sorted(tr):
        print(k, sorted(tr[k]['ranges']), 'sizes', len(tr[k]['sizes']),
              'min', min(tr[k]['sizes']), 'max', max(tr[k]['sizes']))