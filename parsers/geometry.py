import re
from dataclasses import dataclass, field

import pdfplumber

NUM_RE = re.compile(r'^[0-9]+(\.[0-9]+)?\*?$')
N1_VALUES = {1500, 1000, 750}


def center(w):
    return (w['x0'] + w['x1']) / 2.0


def is_num(t):
    return bool(NUM_RE.match(t.strip()))


def num_val(t):
    return float(t.strip().rstrip('*'))


def is_starred(t):
    return t.strip().endswith('*')


@dataclass
class Block:
    kind: str                 # 'power' | 'thermal'
    label_idx: int
    sizes_idx: int = None
    sizes: list = field(default_factory=list)     # [(size_text, x_center), ...]
    iN_anchor: float = None
    n1_anchor: float = None
    n2_anchor: float = None
    series: str = None
    section: str = None       # P.cooling tag for thermal

    def anchors(self):
        a = []
        if self.iN_anchor is not None:
            a.append(('iN', self.iN_anchor))
        if self.n1_anchor is not None:
            a.append(('n1', self.n1_anchor))
        if self.n2_anchor is not None:
            a.append(('n2', self.n2_anchor))
        for i, (sz, xc) in enumerate(self.sizes):
            a.append((f'sz:{i}', xc))
        return a


def _shift_words(page):
    """Mirror-spread pages store their content one page-width to the LEFT
    (min x0 < 0). Shift every word right so coordinates are page-local."""
    words = page.extract_words(use_text_flow=False)
    if words and min(w['x0'] for w in words) < -50:
        W = page.width
        for w in words:
            w['x0'] += W
            w['x1'] += W
    return words


def group_lines(page, tol=2.2):
    """Cluster words into visual lines (left->right), keyed by top."""
    words = sorted(_shift_words(page), key=lambda w: w['top'])
    lines = []
    cur = None
    for w in words:
        if cur is not None and w['top'] - cur['top'] <= tol:
            cur['words'].append(w)
        else:
            cur = {'top': w['top'], 'words': [w]}
            lines.append(cur)
    for ln in lines:
        ln['words'].sort(key=lambda x: (x['x0'], x['x1']))
    return lines


def line_text(ln):
    return ' '.join(w['text'] for w in ln['words'])


def ascending_ints(nums):
    """True if the numeric list is integral and strictly ascending."""
    if len(nums) < 3:
        return False
    vals = []
    for t in nums:
        t = t.strip().rstrip('*')
        if not t.isdigit():
            return False
        vals.append(int(t))
    return all(vals[i] < vals[i + 1] for i in range(len(vals) - 1))


def find_sizes_row(lines, label_idx, band=None, max_scan=8, span=260):
    """First line below a 'Gear unit Size' label whose numeric run ascends.
    When a band [x0, x1] is given, only numbers whose centre falls within
    band +/- span count -- this isolates one table's columns when two tables
    share the same line (e.g. '14...26 15...26')."""
    end = min(label_idx + max_scan, len(lines))
    for i in range(label_idx + 1, end):
        ln = lines[i]
        if band is not None:
            lo, hi = band[0] - span, band[1] + span
            nums = [w['text'] for w in ln['words']
                    if is_num(w['text']) and lo <= center(w) <= hi]
        else:
            nums = [w['text'] for w in ln['words'] if is_num(w['text'])]
        if ascending_ints(nums):
            return i
    return None


def _label_groups(ln):
    """Consecutive 'Gear unit Size' word groups on a line -> [(x0, x1), ...]."""
    ws = ln['words']
    groups = []
    i = 0
    while i < len(ws) - 2:
        t = [w['text'].lower() for w in ws[i:i + 3]]
        if t == ['gear', 'unit', 'size']:
            groups.append((ws[i]['x0'], ws[i + 2]['x1']))
            i += 3
        else:
            i += 1
    return groups


def _power_headers(lines):
    """All 'i n1 n2' header tuples (x-centers), in left->right order."""
    out = []
    for ln in lines:
        ws = ln['words']
        for i in range(len(ws) - 2):
            if (ws[i]['text'] == 'i' and ws[i + 1]['text'] == 'n1'
                    and ws[i + 2]['text'] == 'n2'
                    and ws[i + 1]['x0'] - ws[i]['x1'] < 60
                    and ws[i + 2]['x0'] - ws[i + 1]['x1'] < 60):
                out.append((center(ws[i]), center(ws[i + 1]), center(ws[i + 2])))
    out.sort(key=lambda t: t[0])
    return out


def detect_blocks(page_lines):
    """Detect power & thermal table blocks from 'i n1 n2' headers +
    'Gear unit Size' labels; sort left->right. Mirrored pages are already
    normalised by group_lines()."""
    thermal_top = None
    for ln in page_lines:
        if any(w['text'].startswith('Thermal') for w in ln['words']):
            thermal_top = ln['top'] if thermal_top is None else min(thermal_top, ln['top'])

    blocks = []
    for i, ln in enumerate(page_lines):
        for (x0, x1) in _label_groups(ln):
            si = find_sizes_row(page_lines, i, band=(x0, x1))
            if si is None:
                continue
            b = Block(kind='power', label_idx=i, sizes_idx=si)
            lo, hi = x0 - 260, x1 + 260
            for w in page_lines[si]['words']:
                if is_num(w['text']) and lo <= center(w) <= hi:
                    b.sizes.append((w['text'].rstrip('*'), center(w)))
            if thermal_top is not None and page_lines[si]['top'] > thermal_top:
                b.kind = 'thermal'
            if b.kind == 'thermal':
                # 'n1' header may sit on the sizes row itself or a line or
                # two above it (dual-table layouts interleave these).
                for start in range(si, max(si - 3, -1), -1):
                    hit = next((center(w) for w in page_lines[start]['words']
                                if w['text'] == 'n1'), None)
                    if hit is not None:
                        b.n1_anchor = hit
                        break
            blocks.append(b)

    powers = [b for b in blocks if b.kind == 'power']
    for b, h in zip(sorted(powers, key=lambda b: b.sizes[0][1]),
                    _power_headers(page_lines)):
        b.iN_anchor, b.n1_anchor, b.n2_anchor = h

    blocks.sort(key=lambda b: b.sizes[0][1])
    return blocks


def page_has_thermal_caption(lines):
    """First line covering upper thermal-caption boundary for power tables."""
    for i, ln in enumerate(lines):
        words = ' '.join(w['text'] for w in ln['words'])
        for kw in ('Thermal', 'Nominal', 'Operating'):
            if kw in words:
                return i
    return len(lines)