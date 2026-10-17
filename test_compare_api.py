import sys
sys.path.insert(0, r'D:\gearbox-selector')
from app import engine

vals = {'kw': 100, 'rpm': 1500, 'gr': '13:1', 'gear_type': 'bevel_helical',
        'hb': 'YES', 'cooling': 'FAN', 'lubrication': 'SPLASH', 'sf': 1.5,
        'vendor_id': 3}

rows = engine.compare_vendors(**vals)
print(f"{len(rows)} rows")
for r in rows:
    print(f"  {r['vendor_name']:<22} {r['model']:<20} ratio={r['ratio_iN']:<6} "
          f"pw={r['power_kw']:<6} pn={r['required_pn']} n1={r['n1_rpm']} "
          f"n2={r['n2_actual']} pw_ok={r['power_ok']} th={r['thermal_kw_effective']}")