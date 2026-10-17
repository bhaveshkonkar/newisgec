import sys
sys.path.insert(0, r'D:\gearbox-selector')
from app import engine

result = engine.select(kw=100, rpm=1500, gr='13', gear_type='bevel_helical', hb='YES', cooling='FAN', lubrication='SPLASH', sf=1.5, vendor_id=3)
for c in result['candidates'][:5]:
    print(f"  {c['model']} - power={c['power_kw']} ok={c['power_ok']} thermal={c['thermal_kw_effective']} ratio={c['ratio_iN']} dev={c['ratio_dev']}")