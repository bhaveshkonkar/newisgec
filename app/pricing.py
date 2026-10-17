"""Steel / metal price lookup with graceful fallback.

Price for a selected gearbox = average net weight (from the catalogue's
dimension tables, `dimension.net_weight_kg`) x steel price per kg.

Provider: MetalCharts API (https://api.metalcharts.org, Bearer mc_live_...)
  GET /v1/prices?symbols=JBP   -> {"data": {"JBP": {"price": 3109.98, ...}}}
  GET /v1/currency?base=USD    -> {"rates": {"INR": 96.33, ...}}

Unit handling: MetalCharts quotes each metal in its own basis
(gold XAU = per troy ounce, copper HG = per pound, steel JBP = per METRIC
TONNE). `METAL_UNIT` declares which basis the price is in and is converted
to INR/kg:
  mt  -> / 1000                 (steel, aluminium, nickel, zinc, lead, tin)
  lb  -> * 2.20462262           (COMEX copper)
  toz -> * 32.1507466           (gold, silver, platinum, palladium)

Source chain (first usable wins):
  1. Live MetalCharts price x USD/INR from the same API
  2. Last live quote cached in-process (TTL)
  3. Manual fallback STEEL_PRICE_PER_KG_INR from .env
A quote outside PLAUSIBLE_INR_PER_KG is rejected as a unit/feed error and
falls back, so a wrong METAL_UNIT can never print a bogus price.
"""
from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE_URL = 'https://api.metalcharts.org'
ENV_FILE = Path(__file__).resolve().parent.parent / '.env'

# price basis -> multiplier that converts one quoted unit into one kg
UNIT_TO_KG = {
    'mt': 1 / 1000.0,          # metric tonne
    'lb': 2.20462262,           # avoirdupois pound
    'toz': 32.1507466,          # troy ounce (1 kg = 32.1507466 troy oz)
    'kg': 1.0,
}

PRICE_TTL_S = 600     # refresh spot price at most every 10 minutes
# A refused quote suppresses refetching for this long. Short enough that a
# fixed feed recovers quickly, long enough not to hammer a broken endpoint.
REJECTED_RETRY_S = 300
FX_TTL_S = 3600       # USD/INR at most hourly
PLAUSIBLE_INR_PER_KG = (5.0, 5000.0)  # guard against wrong-unit / bad feed

# Which unit the publisher actually quotes each series in, taken from the
# publisher's own symbol page rather than guessed from magnitude. Guessing
# "mt" for a feed that quotes "kg" silently multiplies or divides by 1000 and
# prints a price that looks reasonable and is wrong, so a symbol with no
# documented basis is refused outright instead of assumed.
#
#   https://metalcharts.org/metals/jbp
#     "Symbol JBP / Unit mt / Category base / Exchange LME"
#     "The current steel spot price is $3098.47 per metric ton"
DOCUMENTED_UNITS = {
    'JBP': 'mt',    # Japanese steel series, quoted USD per metric tonne
    'ALI': 'mt',
    'NI': 'mt',
    'ZN': 'mt',
    'PB': 'mt',
    'SN': 'mt',
    'LC': 'mt',
    'HG': 'lb',     # COMEX copper, USD per avoirdupois pound
    'XAU': 'toz',
    'XAG': 'toz',
    'XPT': 'toz',
    'XPD': 'toz',
    'UXA': 'lb',
}


def _load_env() -> None:
    """Tiny .env loader (KEY=VALUE) so pricing works regardless of how the
    server was launched."""
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, _, v = line.partition('=')
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _env(key: str, default: str | None = None) -> str | None:
    return os.environ.get(key) or default


def _manual_per_kg() -> float | None:
    raw = _env('STEEL_PRICE_PER_KG_INR')
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


class _Cache:
    quote: dict | None = None
    quoted_at: float = 0.0
    fx: dict | None = None
    fx_at: float = 0.0
    # when the feed last returned a quote we refused to price from
    rejected_at: float = 0.0
    rejected_note: str | None = None


_CACHE = _Cache()


def _get_json(path: str, key: str) -> dict | None:
    url = f'{BASE_URL}{path}'
    req = urllib.request.Request(url, headers={
        'Authorization': f'Bearer {key}',
        'Accept': 'application/json',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0',
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except Exception:
        return None


def _usd_inr(key: str) -> float | None:
    if _CACHE.fx is not None and (time.time() - _CACHE.fx_at) < FX_TTL_S:
        return _CACHE.fx
    data = _get_json('/v1/currency?base=USD', key)
    rate = ((data or {}).get('rates') or {}).get('INR')
    if not rate:
        return None
    _CACHE.fx, _CACHE.fx_at = float(rate), time.time()
    return _CACHE.fx


def _fetch_live() -> dict | None:
    """MetalCharts spot price for METAL_SYMBOL + USD/INR, converted to INR/kg."""
    key = _env('METALCHARTS_API_KEY')
    symbol = _env('METAL_SYMBOL', 'JBP')
    unit = _env('METAL_UNIT', 'mt').lower()
    if not key:
        return None
    if unit not in UNIT_TO_KG:
        return None

    documented = DOCUMENTED_UNITS.get(symbol.upper())
    if documented is None:
        print(f"[pricing] {symbol} has no documented quote basis; refusing to "
              f"guess a unit. Add it to DOCUMENTED_UNITS from the publisher's "
              f"symbol page first.")
        return None
    if unit != documented:
        print(f"[pricing] METAL_UNIT='{unit}' contradicts the publisher's "
              f"documented basis for {symbol} ('{documented}'); refusing to "
              f"convert.")
        return None


    data = _get_json('/v1/prices?symbols=' + urllib.parse.quote(symbol), key)
    quote = ((data or {}).get('data') or {}).get(symbol)
    if not quote or quote.get('price') is None:
        return None
    fx = _usd_inr(key)
    if not fx:
        return None

    per_kg = float(quote['price']) * UNIT_TO_KG[unit] * fx
    lo, hi = PLAUSIBLE_INR_PER_KG
    if not (lo <= per_kg <= hi):
        # unit mismatch or broken feed -> refuse to price with it
        return {
            'per_kg_inr': None,
            'source': 'rejected',
            'metal': symbol,
            'quote_unit': unit,
            'raw_price_usd': float(quote['price']),
            'usd_inr': fx,
            'note': (f'JBP-style quote {quote["price"]} USD per {unit} -> '
                     f'{per_kg:,.2f} INR/kg is outside the plausible steel '
                     f'band {lo}-{hi}; check METAL_UNIT'),
            'fetched_at': quote.get('timestamp'),
        }

    return {
        'per_kg_inr': round(per_kg, 2),
        'source': 'metalcharts',
        'metal': symbol,
        'quote_unit': unit,
        'raw_price_usd': float(quote['price']),
        'usd_inr': fx,
        'currency': 'INR',
        'unit': 'kg',
        'fetched_at': quote.get('timestamp'),
    }


def _fallback(note: str | None = None) -> dict:
    """Manual override, else an explicit no-price. Never raises.

    The rejection note rides along even when a manual price is returned. A
    substituted number with no trace of why is the failure mode worth avoiding:
    the operator sees a plausible price and has no signal that the live feed
    was refused.
    """
    manual = _manual_per_kg()
    if manual is not None:
        out = {
            'per_kg_inr': manual,
            'source': 'manual',
            'metal': None,
            'quote_unit': None,
            'currency': 'INR',
            'unit': 'kg',
            'fetched_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        }
        if note:
            out['rejected_note'] = note
        return out
    return {'per_kg_inr': None, 'source': None, 'metal': None,
            'quote_unit': None, 'currency': 'INR', 'unit': 'kg',
            'fetched_at': None,
            'rejected_note': note}


def get_metal_price() -> dict:
    """Live-or-cached metal quote in INR/kg, else manual fallback.

    A quote that fails the plausibility band is *not* cached as a price. It is
    recorded only as a rejection, which suppresses refetching for a while and
    lets the manual override answer. Caching the rejection as if it were a
    quote would make the first call return a fallback price and every call
    inside the TTL return None, which reads downstream as "no price exists".
    """
    now = time.time()

    if _CACHE.quote is not None and _CACHE.quote.get('per_kg_inr') is not None:
        if (now - _CACHE.quoted_at) < PRICE_TTL_S:
            return _CACHE.quote

    # feed is known bad; do not hammer it, answer from the override
    if _CACHE.rejected_note and (now - _CACHE.rejected_at) < REJECTED_RETRY_S:
        return _fallback(_CACHE.rejected_note)

    live = _fetch_live()
    if live is not None and live.get('source') == 'rejected':
        print(f"[pricing] {live['note']}")
        _CACHE.rejected_at = now
        _CACHE.rejected_note = live['note']
        return _fallback(live['note'])

    if live is not None:
        _CACHE.quote = live
        _CACHE.quoted_at = now
        _CACHE.rejected_note = None
        print(f"[pricing] steel {live['per_kg_inr']} INR/kg "
              f"({live['metal']} {live['raw_price_usd']} USD/{live['quote_unit']} "
              f"x {live['usd_inr']})")
        return live

    return _fallback()


def enrich(candidates: list[dict]) -> dict:
    """Attach price fields to candidate rows. Mutates rows in place.

    Each row must already carry `weight_kg` (None when the catalogue has no
    published weight for that model, e.g. PREMIUM E.T.L. cases).

    When a row has no published weight but its series has an estimate basis
    (Elecon K2 / S2), an INDICATIVE weight + price is attached separately as
    `*_indicative` so published and estimated figures never mix.
    """
    quote = get_metal_price()
    per_kg = quote['per_kg_inr']
    import engine
    for c in candidates:
        w = c.get('weight_kg')
        c['price_per_kg_inr'] = per_kg
        c['price_source'] = quote['source']
        c['price_fetched_at'] = quote['fetched_at']
        c['est_price_inr'] = round(w * per_kg, 2) if w is not None and per_kg else None

        c['weight_kg_indicative'] = None
        c['est_price_inr_indicative'] = None
        c['estimate_basis'] = None
        if w is None and per_kg:
            est = engine.indicative_weight(
                c.get('series'), c.get('size'), c.get('vendor_id'))
            if est:
                c['weight_kg_indicative'] = est['weight_kg']
                c['est_price_inr_indicative'] = round(
                    est['weight_kg'] * per_kg, 2)
                c['estimate_basis'] = est
    return quote


_load_env()