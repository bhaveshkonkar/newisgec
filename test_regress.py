import sys
sys.path.insert(0, r'D:\gearbox-selector')
from app import engine

# Elecon regression tests (vendor_id=1)
tests = [
    (400, 1480, '17:1', 'any', 'NO', 'Natural', 'SPLASH', 1.5),
    (45, 1480, '24:1', 'any', 'NO', 'Natural', 'SPLASH', 1.7),
    (260, 1480, '13:1', 'any', 'YES', 'FAN', 'SPLASH', 1.4),
]
for t in tests:
    r = engine.select(kw=t[0], rpm=t[1], gr=t[2], gear_type=t[3], hb=t[4],
                      cooling=t[5], lubrication=t[6], sf=t[7], vendor_id=1)
    top = r['candidates'][0]
    print(f"{t} -> {top['model']} power={top['power_kw']} pw_ok={top['power_ok']} th={top['thermal_kw_effective']}")

# multi-vendor comparison
print("\n=== compare_vendors ===")
res = engine.compare_vendors(kw=100, rpm=1500, gr='13:1', gear_type='bevel_helical',
                             hb='YES', cooling='FAN', lubrication='SPLASH', sf=1.5)
print(res)