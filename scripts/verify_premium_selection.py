"""Verify the premium-catalog selection for 160 kW / ratio 25 / S/F 1.25.

Independent of the engine: this reads the catalogue rows directly and applies
the documented rule by hand, then compares with what the engine returned. If
the two disagree, one of them is wrong and the difference is the bug.
"""
import sys
sys.path.insert(0, "app")

from engine import _conn  # noqa: E402
import engine  # noqa: E402

KW, RATIO, SF = 160.0, 25.0, 1.25
PN = KW * SF

conn = _conn()
cur = conn.cursor()

print("=" * 72)
print(f"REQUEST: {KW:g} kW, ratio {RATIO:g}, S/F {SF}")
print(f"Required PN = {KW:g} x {SF} = {PN:g} kW")
print("=" * 72)

cur.execute("SELECT id, code, name FROM vendor ORDER BY id")
vendors = cur.fetchall()
print("\nVENDORS")
for v in vendors:
    print(f"  id={v[0]}  {v[1]}  {v[2]}")

# ---------------------------------------------------------------- per vendor
for vid, vcode, vname in vendors:
    print("\n" + "-" * 72)
    print(f"VENDOR {vcode} (id={vid})")
    print("-" * 72)

    # what did the engine actually pick, and for which rating speed?
    for speed in engine.CATALOG_SPEEDS:
        res = engine.select(
            kw=KW, rpm=1500, gr=RATIO, sf=SF,
            gear_type="any", hb="YES", cooling="FAN",
            lubrication="SPLASH", vendor_id=vid,
        )
        cands = res["candidates"]
        if not cands:
            print(f"  @{speed} rpm: no candidates")
            continue
        top = cands[0]
        print(f"  @{speed} rpm -> {top['model']}  "
              f"rated {top['power_kw']} kW (need {PN:g})  "
              f"iN {top['ratio_iN']} dev {top['ratio_dev']:.3f}  "
              f"out {top['n2_actual']} rpm")
        print(f"              warnings: {top.get('warnings') or 'none'}")
        print("              top 4 ranked:")
        for c in cands[:4]:
            print(f"                {c['model']:<26} {c['power_kw']:>7} kW  "
                  f"iN {c['ratio_iN']:<6} dev {c['ratio_dev']:.3f}  "
                  f"power_ok={c['power_ok']}")
        break

    # independent check straight from the rating table
    cur.execute("""
        SELECT gs.series_code, g.size, pr.ratio_iN, pr.power_kw
          FROM power_rating pr
          JOIN gear_size g    ON g.id = pr.gear_size_id
          JOIN gear_series gs ON gs.id = g.series_id
         WHERE pr.vendor_id = %s AND gs.series_code = 'B3'
           AND pr.n1_rpm = 1500
         ORDER BY pr.ratio_iN, g.size
    """, (vid,))
    rows = cur.fetchall()
    if not rows:
        print(f"\n  This vendor publishes no B3 series. Nothing to check here.")
        continue

    # the catalogue prints discrete ratio classes; find the one nearest 25
    ratios = sorted({r[2] for r in rows
                  if r[2] is not None and str(r[2]).lower() != "none"})
    if not ratios:
        print("\n  B3 publishes no ratios at all. Cannot verify.")
        continue
    nearest = min(ratios, key=lambda x: abs(float(x) - RATIO))
    print(f"\n  B3 ratio classes published: {ratios}")
    print(f"  nearest to {RATIO:g} -> iN {nearest} "
          f"(deviation {abs(float(nearest)-RATIO)/RATIO*100:.1f}%)")

    at = [(r[1], float(r[3])) for r in rows
      if r[2] is not None and str(r[2]).lower() != "none"
      and float(r[2]) == float(nearest)]
    at.sort(key=lambda x: int(x[0]))
    print(f"\n  B3 sizes at iN {nearest}:")
    for size, pw in at:
        flag = "OK " if pw >= PN else "no "
        print(f"    size {size:>4}  {pw:>8.2f} kW   {flag}")

    qualifying = [(s, p) for s, p in at if p >= PN]
    if qualifying:
        want = min(qualifying, key=lambda x: int(x[0]))
        print(f"\n  smallest B3 size meeting PN at iN {nearest}: "
              f"size {want[0]} ({want[1]} kW) -> B3-{want[0]}-HN-HB-FAN")
    else:
        print(f"\n  NO B3 size meets PN={PN:g} kW at iN {nearest}; "
              f"largest is size {at[-1][0]} at {at[-1][1]} kW")

    # is there anything smaller that meets PN at ANY published ratio?
    print(f"\n  smallest B3 size meeting PN={PN:g} kW at ANY ratio:")
    ok = [(r[1], float(r[3]), r[2]) for r in rows
      if r[2] is not None and str(r[2]).lower() != "none"
      and float(r[3]) >= PN]
    if ok:
        ok.sort(key=lambda x: int(x[0]))
        seen = set()
        for size, pw, ri in ok:
            if size in seen:
                continue
            seen.add(size)
            print(f"    size {size:>4}  {pw:>8.2f} kW at iN {ri}")
    else:
        print("    none")

cur.close()
conn.close()
print("\n" + "=" * 72)