"""Deterministic gearbox selection engine.

Inputs mirror the quotation-log columns:
  kw (required power, kW), rpm (input speed), gr (reduction ratio, e.g.
  '17:1' or 13), gear_type (helical|bevel_helical|any), hb (YES/NO),
  cooling (FAN|FLS|Natural), lubrication (SPLASH|FLS|MDP|Lube Pump),
  sf (service factor).

Rules:
  required_PN = kw * sf
  ratio_req   = gr  ->  nearest printed ratio class per series
  smallest size whose rated power >= PN   (thermal capacity is advisory
  only and never blocks the selection)

Results carry the supplier model code / nomenclature as used in the
price list (e.g. K2-25-HN-HB-FAN) plus its unit price when known.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from parsers.manifest import SERIES

import est_weight

DB = 'postgresql://gearbox:gearbox@localhost:5433/gearbox'

SERIES_ORDER = ['S1', 'S2', 'S3', 'S4', 'K2', 'K3', 'K4']
GEAR_TYPE = {'helical', 'bevel_helical'}

CATALOG_SPEEDS = (1500, 1000, 750)
AMBIENT = 40  # thermal derating reference


def _num(s) -> float:
    return float(s)


def _conn():
    return psycopg.connect(DB)


def nearest_speed(rpm):
    return min(CATALOG_SPEEDS, key=lambda s: abs(s - rpm))


def parse_ratio(gr):
    if gr is None:
        return None
    m = re.search(r'\d+(?:\.\d+)?', str(gr))
    return float(m.group()) if m else None


def _parse_ratio_sf(sf):
    return float(sf)


def _factors(vendor_id: int = 1) -> dict:
    with _conn() as c:
        fw = {(cool, float(amb)): float(f)
              for cool, amb, f in c.execute(
                  'SELECT cooling_type, amb_temp_c, fw FROM ambient_factor WHERE vendor_id = %s', (vendor_id,))}
    return {'fw': fw}


def _power_by_series(n1: int, vendor_id: int = 1) -> dict:
    """(series, ratio, size) -> (power_kw, forced_lube) at one rating speed.

    The premium catalogue holds conflicting rows for the same frame, ratio and
    speed -- 79 such groups, e.g. B3-225 at iN 14 published as both 295 kW and
    322 kW. Reading them with a plain dict assignment let whichever row the
    database happened to return last win, with no ORDER BY to make that
    reproducible: the same requirement could return different models run to
    run, and the power figure shown to the user was arbitrary.

    Duplicates are collapsed with MIN() on purpose. Picking the lower of two
    conflicting ratings can only make the engine choose a LARGER frame, which
    costs money; picking the higher can choose a frame that is actually
    undersized, which breaks the gearbox. When in doubt, assume less capacity.

    The conflict is not hidden: conflicting_power_sizes() reports it so the
    caller can warn that the vendor must confirm.
    """
    with _conn() as c:
        rows = c.execute('''
            SELECT gs.series_code, sz.size, pr.ratio_iN,
                   MIN(float8(pr.power_kw)) AS power_kw,
                   bool_or(pr.requires_forced_lube) AS forced
            FROM power_rating pr
            JOIN gear_size sz ON sz.id = pr.gear_size_id
            JOIN gear_series gs ON gs.id = sz.series_id
            WHERE pr.n1_rpm = %s AND pr.vendor_id = %s
              AND pr.ratio_iN IS NOT NULL AND pr.ratio_iN::text <> 'None'
            GROUP BY gs.series_code, sz.size, pr.ratio_iN''',
                       (n1, vendor_id)).fetchall()
    out: dict = {}
    for code, size, ratio, pw, forced in rows:
        out.setdefault(code, {}).setdefault(ratio, {})[size] = (float(pw), bool(forced))
    return out


def conflicting_power_sizes(n1: int, vendor_id: int = 1) -> dict:
    """(series, size, ratio) -> (min_kw, max_kw) where the catalogue disagrees.

    Returned so the caller can say "the catalogue lists two values for this
    size, confirm with the vendor" instead of presenting one of them as fact.
    """
    with _conn() as c:
        rows = c.execute('''
            SELECT gs.series_code, sz.size, pr.ratio_iN,
                   MIN(float8(pr.power_kw)), MAX(float8(pr.power_kw))
            FROM power_rating pr
            JOIN gear_size sz ON sz.id = pr.gear_size_id
            JOIN gear_series gs ON gs.id = sz.series_id
            WHERE pr.n1_rpm = %s AND pr.vendor_id = %s
              AND pr.ratio_iN IS NOT NULL AND pr.ratio_iN::text <> 'None'
            GROUP BY gs.series_code, sz.size, pr.ratio_iN
            HAVING COUNT(*) > 1
               AND MIN(float8(pr.power_kw)) <> MAX(float8(pr.power_kw))''',
                       (n1, vendor_id)).fetchall()
    return {(code, size, ratio): (float(lo), float(hi))
            for code, size, ratio, lo, hi in rows}


def _thermal_by_series(n1: int, vendor_id: int = 1) -> dict:
    with _conn() as c:
        rows = c.execute('''
            SELECT gs.series_code, sz.size, tc.cooling_type,
                   tc.ratio_in, tc.power_kw
            FROM thermal_capacity tc
            JOIN gear_size sz ON sz.id = tc.gear_size_id
            JOIN gear_series gs ON gs.id = sz.series_id
            WHERE tc.n1_rpm = %s AND tc.amb_temp_c = 20 AND tc.ed_pct = 100 AND tc.vendor_id = %s''',
            (n1, vendor_id)).fetchall()
    out = {}
    for code, size, cooling, rng, pw in rows:
        # Handle both range format (lo..hi) and single value format
        if '..' in rng:
            lo, _, hi = rng.partition('..')
            lo, hi = float(lo), float(hi)
        else:
            # Single ratio value - treat as exact match point
            val = float(rng)
            lo = hi = val
        out.setdefault((code, size, cooling), []).append(
            (lo, hi, float(pw)))
    return out


def _thermal_power(thermal, code, size, cooling, ratio_req):
    for lo, hi, pw in thermal.get((code, size, cooling), []):
        if lo <= ratio_req <= hi:
            return pw
    return None


def _weights_by_model(vendor_id: int) -> dict:
    """Average net weight per (series_code, size) from the dimension table."""
    with _conn() as c:
        rows = c.execute('''
            SELECT s.series_code, g.size, d.weight_kg
            FROM dimension d
            JOIN gear_size g ON g.id = d.gear_size_id
            JOIN gear_series s ON s.id = g.series_id
            WHERE d.dim_name = %s AND d.vendor_id = %s AND d.weight_kg IS NOT NULL''',
            ('net_weight_kg', vendor_id)).fetchall()
    return {(code, size): float(w) for code, size, w in rows}


def _nomenclature(series, size, cooling_tag):
    """Canonical Elecon-style model code.

    K4 (quadruple-stage bevel-helical) models use the HD-SD style seen in
    Elecon references (e.g. K4-18-HD-SD); S1-S4/K2/K3 use HN-HB-[FAN|FLS].
    """
    base = f'{series}-{size}'
    if series == 'K4':
        return f'{base}-HD-SD' + (f'-{cooling_tag}' if cooling_tag else '')
    return f'{base}-HN-HB-{cooling_tag}' if cooling_tag else f'{base}-HN'


def _get_vendor_series(vendor_id: int) -> dict:
    """Get available series for a vendor from DB."""
    with _conn() as c:
        rows = c.execute('''
            SELECT series_code, gear_type
            FROM gear_series
            WHERE vendor_id = %s
            ORDER BY series_code''', (vendor_id,)).fetchall()
    return {code: {'gear_type': gt} for code, gt in rows}


MOUNTING_TYPES = ('foot', 'torque_arm')


def _mountings_by_series(vendor_id: int) -> dict:
    """series_code -> set of mountings the catalogue records for it.

    A missing key means UNKNOWN, not "no mounting". The distinction matters:
    K2, S2 and H4 have no weight rows at all in the imported catalogue, so we
    genuinely cannot say what mounting they come in. Treating unknown as a
    non-match would quietly hide real gearboxes; treating it as a match
    would quietly promise something we cannot verify. The caller is told
    instead.
    """
    try:
        with _conn() as c:
            rows = c.execute('''
                SELECT s.series_code, m.mounting_type
                FROM series_mounting m
                JOIN gear_series s ON s.id = m.series_id
                WHERE s.vendor_id = %s''', (vendor_id,)).fetchall()
    except Exception:
        # table absent on a pre-migration database: everything is unknown
        return {}
    out: dict = {}
    for code, mt in rows:
        out.setdefault(code, set()).add(mt)
    return out


def select(kw, rpm, gr, gear_type='any', hb='YES', cooling='FAN',
           lubrication='SPLASH', sf=1.5, select_closest_power=False,
           vendor_id: int = 1, mounting_type='any'):
    factors = _factors(vendor_id)
    pn = kw * _parse_ratio_sf(sf)
    ratio_req = parse_ratio(gr)
    if ratio_req is None:
        raise ValueError('missing ratio')
    n1 = nearest_speed(rpm)

    # The catalogue only carries power and thermal ratings at 1500, 1000 and
    # 750 rpm, so an entered speed has to be snapped to one of those. Real
    # motors run at 1440, 1420, 960, 1780 and so on, so this snapping happens
    # constantly -- and an engineer defending a purchase enquiry must be told,
    # not left to assume their number was used. Report it only when the speed
    # actually moved, so an exact catalogue speed stays quiet.
    speed_shifted = float(rpm) != float(n1)

    cool_map = {'FAN': 'fan', 'FLS': 'fan', 'Natural': 'none',
                'YES': 'none', 'NA': 'none'}
    cooling_cls = cool_map.get(str(cooling).strip().upper(), 'none')
    fw = factors['fw'].get((cooling_cls, float(AMBIENT)), 1.0)

    power = _power_by_series(n1, vendor_id)
    thermal = _thermal_by_series(n1, vendor_id)
    weights = _weights_by_model(vendor_id)
    conflicts = conflicting_power_sizes(n1, vendor_id)

    # Get series for this vendor
    vendor_series = _get_vendor_series(vendor_id)
    series_codes = list(vendor_series.keys())
    if gear_type in GEAR_TYPE:
        series_codes = [s for s in series_codes if vendor_series[s]['gear_type'] == gear_type]

    # Mounting filter. Strict, but never silent: series whose mounting is
    # unrecorded are excluded from a specific request and named in the
    # response, because "we cannot verify these" and "these do not exist"
    # are very different sentences to an engineer signing off a selection.
    mounting_wanted = str(mounting_type or 'any').strip().lower()
    mounting_unknown: list = []
    mounting_note: str | None = None
    have: dict = {}
    if mounting_wanted != 'any':
        if mounting_wanted not in MOUNTING_TYPES:
            raise ValueError(
                f'unknown mounting_type {mounting_wanted!r}; '
                f'expected one of {", ".join(MOUNTING_TYPES)}, any')
        have = _mountings_by_series(vendor_id)
        keep = []
        for s in series_codes:
            offered = have.get(s)
            if not offered:
                mounting_unknown.append(s)
            elif mounting_wanted in offered:
                keep.append(s)
        series_codes = keep
        if mounting_unknown:
            mounting_note = (
                f'{len(mounting_unknown)} series excluded because the catalogue does '
                f"not record their mounting arrangement, so it cannot be confirmed "
                f"as {mounting_wanted}: {', '.join(sorted(mounting_unknown))}. "
                f'Treat the result as a shortlist, not an exhaustive list.'
            )
        if not series_codes:
            raise ValueError(
                f'no series in this catalogue is published with a '
                f'{mounting_wanted} mounting')

    candidates = []
    for code in series_codes:
        if code not in power:
            continue
        ratios = [r for r in power[code]]
        ratios.sort(key=_num)
        best_ratio = min(ratios, key=lambda r: abs(_num(r) - ratio_req))
        sz_vals = power[code][best_ratio]
        sizes = sorted(sz_vals, key=lambda s: int(s))
        if select_closest_power:
            # pick size with minimum |power - PN|
            size = min(sizes, key=lambda s: abs(sz_vals[s][0] - pn))
            pw, forced = sz_vals[size]
            power_ok = pw >= pn
        else:
            qualifying = [s for s in sizes if sz_vals[s][0] >= pn]
            if not qualifying:
                size, pw, forced = sizes[-1], sz_vals[sizes[-1]][0], sz_vals[sizes[-1]][1]
                power_ok = False
            else:
                size, pw, forced = qualifying[0], sz_vals[qualifying[0]][0], sz_vals[qualifying[0]][1]
                power_ok = True

        th_cap = _thermal_power(thermal, code, size, cooling_cls, ratio_req)
        th_eff = th_cap * fw if th_cap is not None else None
        thermal_ok = th_eff is not None and th_eff >= pn

        ratio_dev = abs(_num(best_ratio) - ratio_req) / ratio_req if ratio_req else 0.0
        cooling_tag = 'FLS' if (forced or lubrication == 'FLS') else (
            'FAN' if cooling_cls == 'fan' else '')
        model = _nomenclature(code, size, cooling_tag)
        if lubrication == 'MDP':
            model += '-MDP'

        # Get gear_type from vendor_series (fetched at start of function)
        gear_type_for_code = vendor_series[code]['gear_type']
        wkg = weights.get((code, size))
        candidates.append({
            'series': code,
            'gear_type': gear_type_for_code,
            'size': size,
            'model': model,
            'ratio_req': ratio_req,
            'ratio_iN': best_ratio,
            'ratio_dev': round(ratio_dev, 3),
            'n1_rpm': n1,
            'n2_actual': round(n1 / _num(best_ratio), 2),
            'power_kw': pw,
            'power_ok': power_ok,
            'forced_lube': forced,
            'thermal_kw': th_cap,
            'thermal_kw_effective': round(th_eff, 1) if th_eff else None,
            'thermal_ok': bool(thermal_ok),
            'required_pn': round(pn, 2),
            'sf': float(sf),
            # 'hb' is the legacy YES/NO field. It has never driven selection
            # and still does not; mounting_type is the real attribute.
            'hb': str(hb).upper(),
            'mounting_type': mounting_wanted,
            'mountings_offered': sorted(have.get(code) or []),
            'cooling': str(cooling).strip().upper(),
            'lubrication': str(lubrication).strip().upper(),
            'vendor_id': vendor_id,
            'weight_kg': wkg,
            # Present only when the catalogue lists conflicting ratings for
            # this exact size/ratio/speed. Carried through so the API can
            # warn instead of presenting the lower figure as settled fact.
            'power_conflict': list(conflicts.get((code, size, best_ratio)) or ()) or None,
        })

    def key(c):
        size = int(c['size'])
        try:
            series_idx = SERIES_ORDER.index(c['series'])
        except ValueError:
            series_idx = len(SERIES_ORDER)  # unknown series last
        # Power adequacy dominates. Ratio deviation is a tie-breaker only:
        # ranking by ratio first would happily return an undersized gearbox
        # that happens to hit the ratio almost exactly, which is the one
        # thing a gearbox must never do.
        return (not c['power_ok'], c['ratio_dev'], size, series_idx)

    candidates.sort(key=key)
    return {'ratio_req': ratio_req, 'pn': round(pn, 2), 'sf': float(sf),
            'ambient_fw': fw,
            'mounting_type': mounting_wanted,
            'mounting_note': mounting_note,
            'candidates': candidates}


def summarize(req: dict) -> str:
    top = req['candidates'][0]
    lines = [f"Required power `PN = {top['required_pn']} kW` "
             f"(S/F {req['sf']}), ratio ≈ **{req['ratio_req']}**, "
             f"thermal derating fw = {req['ambient_fw']}."]
    for c in req['candidates'][:3]:
        status = 'MATCH'
        if not c['power_ok']:
            status = 'undersized'
        elif not c['thermal_ok']:
            status = 'thermal note (advisory)'
        lines.append(
            f"- **{c['model']}** — {c['series']}-{c['size']} · iN {c['ratio_iN']} "
            f"→ n2 {c['n2_actual']} rpm · {c['power_kw']} kW rated, thermal "
            f"{c['thermal_kw_effective']} kW — {status}")
    return '\n'.join(lines)


def series_belongs_to(series: str, vendor_id: int) -> bool:
    with _conn() as c:
        return bool(c.execute('''
            SELECT 1 FROM gear_series WHERE series_code = %s AND vendor_id = %s
            LIMIT 1''', (series, vendor_id)).fetchone())


def published_weight(series: str, size: str,
                     vendor_id: int | None = None) -> float | None:
    """Single published net weight for a series+size, or None."""
    sql = '''
        SELECT d.weight_kg FROM dimension d
        JOIN gear_size g ON g.id = d.gear_size_id
        JOIN gear_series s ON s.id = g.series_id
        WHERE d.dim_name = 'net_weight_kg' AND d.weight_kg IS NOT NULL
          AND s.series_code = %s AND g.size = %s'''
    params: list = [series, str(size)]
    if vendor_id is not None:
        sql += ' AND s.vendor_id = %s'
        params.append(vendor_id)
    sql += ' LIMIT 1'
    with _conn() as c:
        row = c.execute(sql, tuple(params)).fetchone()
    return float(row[0]) if row else None


def indicative_weight(series: str, size: str,
                      vendor_id: int | None = None) -> dict | None:
    """Estimated weight for series the catalogue does not publish."""
    def lookup(donor: str, dsize: str):
        return published_weight(donor, dsize, vendor_id)
    return est_weight.indicative_weight(series, size, lookup)


def series_with_weights(vendor_id: int | None = None) -> list[str]:
    """Series codes that have at least one published net weight."""
    sql = '''
        SELECT DISTINCT s.series_code
        FROM dimension d
        JOIN gear_size g ON g.id = d.gear_size_id
        JOIN gear_series s ON s.id = g.series_id
        WHERE d.dim_name = 'net_weight_kg' AND d.weight_kg IS NOT NULL'''
    params: list = []
    if vendor_id is not None:
        sql += ' AND s.vendor_id = %s'
        params.append(vendor_id)
    sql += ' ORDER BY s.series_code'
    with _conn() as c:
        return [r[0] for r in c.execute(sql, tuple(params)).fetchall()]


def series_size_exists(series: str, size: str) -> bool:
    """True if any vendor carries this series+size (weight or not)."""
    with _conn() as c:
        return bool(c.execute('''
            SELECT 1 FROM gear_size g
            JOIN gear_series s ON s.id = g.series_id
            WHERE s.series_code = %s AND g.size = %s LIMIT 1''',
            (series, str(size))).fetchone())


def weights_for(series: str, size: str, vendor_id: int | None = None) -> list[dict]:
    """Net weight rows for one series+size (optionally one vendor only)."""
    sql = '''
        SELECT s.vendor_id, v.code, v.name, s.series_code, g.size,
               d.weight_kg, d.source_page
        FROM dimension d
        JOIN gear_size g ON g.id = d.gear_size_id
        JOIN gear_series s ON s.id = g.series_id
        JOIN vendor v ON v.id = s.vendor_id
        WHERE d.dim_name = 'net_weight_kg' AND d.weight_kg IS NOT NULL
          AND s.series_code = %s AND g.size = %s'''
    params: list = [series, str(size)]
    if vendor_id is not None:
        sql += ' AND s.vendor_id = %s'
        params.append(vendor_id)
    sql += ' ORDER BY s.vendor_id'
    with _conn() as c:
        rows = c.execute(sql, tuple(params)).fetchall()
    return [{'vendor_id': r[0], 'vendor_code': r[1], 'vendor_name': r[2],
             'series': r[3], 'size': r[4], 'weight_kg': float(r[5]),
             'source_page': r[6]} for r in rows]


def get_vendors() -> list[dict]:
    """Return list of available vendors."""
    with _conn() as c:
        rows = c.execute('SELECT id, code, name, description FROM vendor WHERE is_active ORDER BY id').fetchall()
    return [{'id': r[0], 'code': r[1], 'name': r[2], 'description': r[3]} for r in rows]


def select_multi_vendor(kw, rpm, gr, gear_type='any', hb='YES', cooling='FAN',
                         lubrication='SPLASH', sf=1.5, select_closest_power=False) -> dict:
    """Run selection across all active vendors and return combined results."""
    vendors = get_vendors()
    all_results = {}
    for v in vendors:
        try:
            res = select(kw, rpm, gr, gear_type, hb, cooling, lubrication, sf,
                         select_closest_power, vendor_id=v['id'])
            if res['candidates']:
                all_results[v['code']] = {
                    'vendor': v,
                    'result': res
                }
        except Exception as e:
            all_results[v['code']] = {'vendor': v, 'error': str(e)}
    return {'ratio_req': parse_ratio(gr),
            'pn': kw * sf, 'sf': sf, 'vendors': all_results}


def compare_vendors(kw, rpm, gr, gear_type='any', hb='YES', cooling='FAN',
                    lubrication='SPLASH', sf=1.5, vendor_id=None) -> list[dict]:
    """Return flat list of best candidate per vendor for comparison table.

    vendor_id is accepted for API compatibility but ignored — comparison
    always spans all active vendors.
    """
    multi = select_multi_vendor(kw, rpm, gr, gear_type, hb, cooling, lubrication, sf)
    rows = []
    for vcode, vdata in multi['vendors'].items():
        if 'result' in vdata and vdata['result']['candidates']:
            top = vdata['result']['candidates'][0]
            rows.append({
                'vendor': vcode,
                'vendor_name': vdata['vendor']['name'],
                'model': top['model'],
                'series': top['series'],
                'size': top['size'],
                'ratio_iN': top['ratio_iN'],
                'ratio_dev': top['ratio_dev'],
                'n1_rpm': top['n1_rpm'],
                'n2_actual': top['n2_actual'],
                'power_kw': top['power_kw'],
                'power_ok': top['power_ok'],
                'thermal_kw_effective': top['thermal_kw_effective'],
                'thermal_ok': top['thermal_ok'],
                'required_pn': top.get('required_pn', round(kw * sf, 2)),
                'weight_kg': top.get('weight_kg'),
            })
    rows.sort(key=lambda r: (not r['power_ok'], r['ratio_dev']))
    return rows