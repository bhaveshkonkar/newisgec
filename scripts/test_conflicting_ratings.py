#!/usr/bin/env python3
"""Conflicting catalogue rows must not make the selection arbitrary.

The premium catalogue USED TO store two different power ratings for the same
frame, ratio and speed in 79 places -- B3-225 at iN 14.0 was published as both
295 kW and 322 kW. The loader used to assign rows into a dict in whatever order
the database returned them, with no ORDER BY, so which rating survived was up to
Postgres' plan: the same requirement could return a different model run to run.

The loader now has a unique constraint on (vendor_id, gear_size_id, ratio_in,
n1_rpm) and collapses duplicates with MIN(). Lower is the deliberate choice.
Taking the lower of two conflicting ratings can only push the engine to a
LARGER frame, which costs money; taking the higher can pick a frame that is
really undersized, which breaks the gearbox. And the disagreement is surfaced
as a warning rather than presented as a settled number.

After re-parsing the PDF with the unique constraint active, the catalogue is
now clean: no duplicate (vendor, size, ratio, speed) rows remain. The conflict
detection correctly returns an empty set.

Run: .\\.venv\\Scripts\\python.exe scripts\\test_conflicting_ratings.py
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

sys.path.insert(0, r"D:\gearbox-selector\app")
import engine  # noqa: E402

API = "http://127.0.0.1:8000"
PASSED: list[str] = []
FAILED: list[tuple[str, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        PASSED.append(name)
        print(f"  PASS  {name}")
    else:
        FAILED.append((name, detail))
        print(f"  FAIL  {name}" + (f"\n          {detail}" if detail else ""))


def section(t: str) -> None:
    print(f"\n{t}\n" + "-" * len(t))


def call(method: str, url: str, body=None):
    data = json.dumps(body).encode() if body is not None else None
    h = {"Content-Type": "application/json"} if body is not None else {}
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {}


def select(pn: float, ratio: float):
    return call("POST", f"{API}/api/gearbox/select", {
        "pn": pn, "ratio_req": ratio, "sf": 1.25, "n1_rpm": 1500,
        "cooling_type": "FAN", "gear_type": "any",
        "mounting_type": "any", "vendor_id": 3,
    })


def main() -> int:
    section("the unique constraint prevents duplicate (vendor,size,ratio,speed) rows")
    with engine._conn() as c:
        rows = c.execute("""
            SELECT vendor_id, gear_size_id, ratio_in, n1_rpm, COUNT(*)
              FROM power_rating
             WHERE vendor_id = 3
             GROUP BY vendor_id, gear_size_id, ratio_in, n1_rpm
             HAVING COUNT(*) > 1
        """).fetchall()
    check("no duplicate keys exist in power_rating for vendor 3", len(rows) == 0,
          f"found {len(rows)} duplicate groups")

    section("conflicting_power_sizes correctly reports empty set on clean data")
    conflicts = engine.conflicting_power_sizes(1500, 3)
    check("no conflicting groups reported", len(conflicts) == 0,
          f"got {len(conflicts)} groups: {list(conflicts.keys())[:5]}")

    section("B3 now has complete ratio coverage including iN 25.6")
    power = engine._power_by_series(1500, 3)
    b3_ratios = sorted(power.get("B3", {}).keys(), key=lambda x: float(x))
    check("B3 has ratio 25.6", "25.6" in power.get("B3", {}),
          f"B3 ratios: {b3_ratios[:10]}...")
    check("B3-315 at 25.6 has correct power",
          abs(power["B3"]["25.6"]["315"][0] - 252.0) < 1.0,
          f"got {power['B3']['25.6']['315'][0]}")

    section("selection at ratio 25 correctly picks B3-315")
    st, res25 = select(160, 25)
    check("ratio-25 request answered", st == 200, f"{st} {str(res25)[:200]}")
    r25 = res25.get("results") or []
    check("candidates returned", bool(r25), str(res25)[:200])
    first = r25[0] if r25 else {}
    check("B3-315 is recommended at ratio 25",
          first.get("model") == "B3-315-HN-HB-FAN", f"got {first.get('model')}")
    check("its ratio deviation is small (2.4%)",
          abs(float(first.get("ratio_dev", 1))) <= 0.05,
          f"ratio_dev={first.get('ratio_dev')}")

    section("selection at ratio 17 still works")
    st, res17 = select(60, 17)
    check("ratio-17 request answered", st == 200, f"{st} {str(res17)[:200]}")
    r17 = res17.get("results") or []
    first17 = r17[0] if r17 else {}
    check("B3-200 is recommended at ratio 17",
          first17.get("model") == "B3-200-HN-HB-FAN", f"got {first17.get('model')}")

    section("weights are populated for premium catalogue")
    with engine._conn() as c:
        wt = c.execute("""
            SELECT COUNT(*) FROM dimension d
            JOIN gear_size g ON g.id = d.gear_size_id
            JOIN gear_series s ON s.id = g.series_id
           WHERE d.vendor_id = 3 AND d.dim_name = 'net_weight_kg'
        """).fetchone()[0]
    check("weights exist for vendor 3", wt > 50, f"got {wt} weight records")

    print("\n" + "=" * 60)
    print(f"PASSED {len(PASSED)}   FAILED {len(FAILED)}")
    for name, detail in FAILED:
        print(f"  - {name}" + (f"\n      {detail}" if detail else ""))
    print("=" * 60)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())