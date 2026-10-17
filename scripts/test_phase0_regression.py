"""Phase 0 regression gate: the engine must still behave identically after
the vendor/unique/factor migration. Run before trusting anything else."""
import sys

sys.path.insert(0, r"D:\gearbox-selector\app")
import engine  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {label}: got={got!r} want={want!r}")
    if not ok:
        fails.append(label)


print("1. vendor catalog still readable")
for v in engine.get_vendors():
    print("   vendor", v)
check("elecon id", [v for v in engine.get_vendors() if v["id"] == 1] and 1, 1)

print("\n2. ambient factors now present for BOTH vendors")
# this is the bug Phase 0 fixed: _factors(3) used to return {}
for vid in (1, 3):
    f = engine._factors(vid)["fw"]
    print(f"   vendor {vid}: {len(f)} ambient factor rows {sorted(f.items())[:2]}")
    if not f:
        fails.append(f"ambient_factor empty for vendor {vid}")
check("vendor 3 has factors", bool(engine._factors(3)["fw"]), True)

print("\n3. series_code uniqueness relaxed, lookups still resolve")
for code, size in (("K3", "25"), ("S1", "20"), ("B3", "280"), ("H1", "280"),
                   ("B4", "315"), ("K2", "25")):
    print(f"   {code}-{size} exists: {engine.series_size_exists(code, size)}")

print("\n4. TEST 5 selection (400 kW, 1480 rpm, 17:1, bevel-helical, H/B YES, FAN, SPLASH, SF 1.5)")
r = engine.select(kw=400, rpm=1480, gr="17:1", gear_type="bevel_helical",
                  hb="YES", cooling="FAN", lubrication="SPLASH", sf=1.5,
                  vendor_id=1)
check("design power PN = kw*sf", r["pn"], 600.0)
check("catalog speed for 1480 rpm", engine.nearest_speed(1480), 1500)
check("requested ratio", r["ratio_req"], 17.0)
print("   ambient factor applied (fw):", r["ambient_fw"])
for c in r["candidates"][:4]:
    print(f"   {c['model']:22} iN={c['ratio_iN']:>6} n2={c['n2_actual']:>7} "
          f"kW={c['power_kw']:>7} power_ok={c['power_ok']} "
          f"thermal={c['thermal_kw_effective']} thermal_ok={c['thermal_ok']}")

print("\n5. smallest-size >= PN rule (the whole point of select_closest_power=False)")
for vid in (1, 3):
    rr = engine.select(kw=400, rpm=1480, gr="17:1", gear_type="any",
                       hb="YES", cooling="FAN", lubrication="SPLASH", sf=1.5,
                       vendor_id=vid)
    bad = [c["model"] for c in rr["candidates"]
           if c["power_ok"] and c["power_kw"] < rr["pn"]]
    check(f"vendor {vid}: no power_ok candidate below PN", bad, [])
    if vid == 3:
        print("   premium candidates:")
        for c in rr["candidates"][:3]:
            print(f"     {c['model']:22} kW={c['power_kw']:>6} ok={c['power_ok']}")

print("\n6. cross-vendor compare still runs (returns a flat list of best-per-vendor)")
try:
    rows = engine.compare_vendors(kw=100, rpm=1500, gr="25:1", gear_type="any",
                                  hb="YES", cooling="FAN", lubrication="SPLASH",
                                  sf=1.0)
    print(f"   compare_vendors -> {type(rows).__name__} of {len(rows)}")
    for r in rows:
        print(f"     {r['vendor']:8} {r['model']:22} iN={r['ratio_iN']:>6} "
              f"kW={r['power_kw']:>7} power_ok={r['power_ok']}")
    check("compare returns >=2 vendors", len(rows) >= 2, True)
    # multi_vendor wrapper is the dict-shaped sibling
    mv = engine.select_multi_vendor(kw=100, rpm=1500, gr="25:1", sf=1.0)
    check("select_multi_vendor keys", sorted(mv.keys()),
          sorted(["ratio_req", "pn", "sf", "vendors"]))
except Exception as e:
    fails.append(f"compare_vendors: {e}")
    print("   compare FAILED:", e)

print("\n7. weights / pricing path still intact")
try:
    rows = engine.weights_for("K3", "25", vendor_id=1)
    print("   K3-25 weight row:", rows[0] if rows else "none")
except Exception as e:
    fails.append(f"weights_for: {e}")

print("\n" + ("=" * 60))
print("PHASE 0 GATE: " + ("ALL PASS" if not fails else f"{len(fails)} FAILURES: {fails}"))
sys.exit(1 if fails else 0)