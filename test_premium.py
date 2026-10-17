import sys
sys.path.insert(0, r'D:\gearbox-selector')

from app import engine
from app import est_weight


try:
    result = engine.select(kw=100, rpm=1500, gr='13', gear_type='bevel_helical', hb='YES', cooling='FAN', lubrication='SPLASH', sf=1.5, vendor_id=3)
    print('Success!')
    for c in result['candidates'][:3]:
        print(f"  {c['model']} - power={c['power_kw']} ok={c['power_ok']}")
except Exception as e:
    import traceback
    traceback.print_exc()
