"""Extraction-level quality gates (operate on the fresh parse output).

These complement script/verify.py (which checks the *database*): they
re-validated the parse itself and would catch geometry/parser regressions.

Gates:
  * n2_consistency    printed 'n2' column must equal n1 / iN of the ratio
                      class we bound the row to (catalog prints both).
  * mirror_pages      pages 8|9, 10|11, 12|13, 14|15 are booklet mirrors:
                      identical row sets, so a perfect independent re-read.
  * thermal_tiling    per (series,size,cooling) the ratio ranges must cover
                      one contiguous run of the nominal ratio axis (no
                      interior holes, no overlaps). Coarse 'a..b' bands that
                      skip an adjacent nominal step are by-design, so the
                      check is done on nominal-ratio membership, not on
                      interval adjacency.
"""
from __future__ import annotations

import re
from collections import defaultdict

from parsers.manifest import SERIES

N2_TOL = 0.04            # |printed_n2 - n1/iN| / (n1/iN), worst observed 2.93%
MIRROR_PAIRS = [(8, 9), (10, 11), (12, 13), (14, 15)]
STAR_RE = re.compile(r'(?<![.\d])\d+(?:\.\d+)?\*')


def n2_consistency(power):
    """printed n2 column vs n1 / ratio-class."""
    issues, checked, worst = [], 0, 0.0
    for r in power:
        if not r['n2']:
            continue
        checked += 1
        exp = r['n1'] / float(r['ratio'])
        rel = abs(r['n2'] - exp) / exp
        worst = max(worst, rel)
        if rel > N2_TOL:
            issues.append(
                f"n2 mismatch {r['series']}-{r['size']} iN {r['ratio']} "
                f"@{r['n1']}: printed {r['n2']} vs n1/iN {exp:.3f} "
                f"({rel * 100:.1f}%) [page {r['page']}]")
    return issues, {'checked': checked, 'worst_rel_pct': round(worst * 100, 3)}


def mirror_pages(power):
    """booklet spreads must parse to identical row sets."""
    by = defaultdict(set)
    for r in power:
        by[r['page']].add((r['series'], r['size'], r['ratio'], r['n1'],
                           round(r['power'], 4), r['forced']))
    issues = []
    for a, b in MIRROR_PAIRS:
        sa, sb = by.get(a, set()), by.get(b, set())
        if sa != sb:
            for d in sorted(sa - sb)[:6]:
                issues.append(f'mirror p{a} only: {d}')
            for d in sorted(sb - sa)[:6]:
                issues.append(f'mirror p{b} only: {d}')
    return issues, {'pairs': len(MIRROR_PAIRS)}


def thermal_tiling(thermal):
    """nominal-ratio coverage: contiguous run, no holes, no overlaps."""
    nominal = {s: sorted(float(x) for x in m['ratios'])
               for s, m in SERIES.items()}
    groups = defaultdict(set)
    for r in thermal:
        lo, _, hi = r['ratio_iN'].partition('..')
        groups[(r['series'], r['size'], r['cooling'])].add((float(lo), float(hi)))

    issues, n_empty = [], 0
    for (series, size, cooling), ranges in sorted(groups.items()):
        noms = nominal[series]
        covered, counts = set(), defaultdict(int)
        for lo, hi in ranges:
            for r in noms:
                if lo - 1e-9 <= r <= hi + 1e-9:
                    covered.add(r)
                    counts[r] += 1
        if not covered:
            n_empty += 1
            issues.append(f'tiling {series}-{size} [{cooling}]: '
                          f'ranges {sorted(ranges)} cover no nominal ratio')
            continue
        i0, i1 = noms.index(min(covered)), noms.index(max(covered))
        missing = set(noms[i0:i1 + 1]) - covered
        ovl = {r for r, c in counts.items() if c > 1}
        if missing:
            issues.append(f'tiling {series}-{size} [{cooling}]: interior '
                          f'ratio hole(s) {sorted(missing)}')
        if ovl:
            issues.append(f'tiling {series}-{size} [{cooling}]: ratio '
                          f'covered by >1 band: {sorted(ovl)}')
    return issues, {'groups': len(groups), 'empty_groups': n_empty}


def forced_flags(power):
    """forced-lube '*' flags verified geometrically against the printed page:
    every cell we flag as forced must have a literal '*' glyph at the same
    (x, y) as the cell token (independent of word/tokenization)."""
    import pdfplumber
    from parsers.tables import PDF, SERIES_POWER_PAGES

    forced = [r for r in power if r['forced']]
    issues = []
    star_chars = {}
    with pdfplumber.open(PDF) as pdf:
        for page_no in sorted({r['page'] for r in power}):
            chars = pdf.pages[page_no - 1].chars
            if any(c['x0'] < -50 for c in chars):
                W = pdf.pages[page_no - 1].width
                chars = [{**c, 'x0': c['x0'] + W} for c in chars]
            star_chars[page_no] = [
                (c['x0'], c['top']) for c in chars if c['text'] == '*']

    flagged = 0
    for r in forced:
        flagged += 1
        near = [s for s in star_chars.get(r['page'], [])
                if r['cx0'] - 1.0 <= s[0] <= r['cx1'] + 1.0
                and abs(s[1] - r['top']) < 4.5]
        if not near:
            issues.append(
                f'forced {r["series"]}-{r["size"]} iN {r["ratio"]} '
                f'@{r["n1"]} page {r["page"]}: no "*" glyph in token x-range '
                f'[{r["cx0"]:.1f}, {r["cx1"]:.1f}] at y={r["top"]:.1f}')
    return issues, {'flagged_cells': flagged, 'checked': len(power)}