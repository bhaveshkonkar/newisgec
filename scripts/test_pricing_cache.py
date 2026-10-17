"""Pricing cache and unit-guard checks. No network required.

The bug this guards against: a quote that fails the plausibility band used to
be stored in the same slot as a good quote, so the first caller got the manual
fallback and every caller inside the TTL got per_kg_inr=None. A None that
depends on call ordering is worse than a stale number.
"""
from __future__ import annotations

import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from app import pricing  # noqa: E402

FAILS: list[str] = []

# captured before any test stubs it out, so the unit guard can exercise the
# real function
REAL_FETCH_LIVE = pricing._fetch_live


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def reset() -> None:
    pricing._CACHE.quote = None
    pricing._CACHE.quoted_at = 0.0
    pricing._CACHE.rejected_at = 0.0
    pricing._CACHE.rejected_note = None


class FakeLive(dict):
    pass


print("rejected quote must never be served as a price")
reset()
bad = {
    "per_kg_inr": None, "source": "rejected", "metal": "JBP",
    "quote_unit": "mt", "raw_price_usd": 2600.0, "usd_inr": 88.0,
    "note": "out of plausible band",
}
pricing._fetch_live = lambda: dict(bad)
pricing._manual_per_kg = lambda: 65.0

first = pricing.get_metal_price()
second = pricing.get_metal_price()
third = pricing.get_metal_price()
check("first call falls back to the manual price", first["per_kg_inr"] == 65.0, str(first))
check("second call still returns a price, not None", second["per_kg_inr"] == 65.0, str(second))
check("third call still returns a price, not None", third["per_kg_inr"] == 65.0, str(third))
check("all three calls agree", first["per_kg_inr"] == second["per_kg_inr"] == third["per_kg_inr"])
check("the rejection reason is not lost", bool(third.get("rejected_note")), str(third))

print("\na rejected feed must not be refetched on every call")
calls = {"n": 0}


def counting_bad():
    calls["n"] += 1
    return dict(bad)


reset()
pricing._fetch_live = counting_bad
for _ in range(5):
    pricing.get_metal_price()
check("feed fetched at most once inside the reject window", calls["n"] == 1, f"fetched {calls['n']}x")

print("\nno override and a rejected feed -> explicit no-price, never a wrong number")
reset()
pricing._fetch_live = lambda: dict(bad)
pricing._manual_per_kg = lambda: None
r1 = pricing.get_metal_price()
r2 = pricing.get_metal_price()
check("returns per_kg_inr None when nothing is usable", r1["per_kg_inr"] is None, str(r1))
check("and does so consistently", r2["per_kg_inr"] is None, str(r2))
check("rejection note is carried through", bool(r2.get("rejected_note")))

print("\na good quote is cached and reused")
reset()
good = {
    "per_kg_inr": 64.2, "source": "metalcharts", "metal": "ALI",
    "quote_unit": "mt", "raw_price_usd": 2600.0, "usd_inr": 88.0,
    "fetched_at": "2026-01-01T00:00:00+00:00",
}
pricing._fetch_live = lambda: dict(good)
pricing._manual_per_kg = lambda: 65.0
g1 = pricing.get_metal_price()
g2 = pricing.get_metal_price()
check("live price is used when plausible", g1["per_kg_inr"] == 64.2, str(g1))
check("second call served from cache", g2["per_kg_inr"] == 64.2, str(g2))
check("cached quote is not polluted with a rejection note", not g2.get("rejected_note"), str(g2))

print("\nunit guard on the ambiguous JBP feed")
# the cache tests replaced _fetch_live with a stub; the guard needs the real one
pricing._fetch_live = REAL_FETCH_LIVE
saved = {k: __import__("os").environ.get(k) for k in
         ("METALCHARTS_API_KEY", "METAL_SYMBOL", "METAL_UNIT")}


def with_env(**over):
    import os
    os.environ["METALCHARTS_API_KEY"] = "test-key"
    os.environ.pop("METAL_STEEL_PER_KG", None)
    for k, v in over.items():
        os.environ[k] = v


reset()
with_env(METAL_SYMBOL="JBP", METAL_UNIT="mt")
check("JBP with an assumed mass unit is refused", pricing._fetch_live() is None,
      str(pricing._fetch_live()))
with_env(METAL_SYMBOL="JBP", METAL_UNIT="banana")
check("an unknown unit is refused", pricing._fetch_live() is None)
for k, v in saved.items():
    if v is None:
        __import__("os").environ.pop(k, None)
    else:
        __import__("os").environ[k] = v

print("\n" + "=" * 50)
if FAILS:
    print(f"PRICING: {len(FAILS)} FAILURE(S): {', '.join(FAILS)}")
    sys.exit(1)
print("PRICING: ALL PASS")
sys.exit(0)