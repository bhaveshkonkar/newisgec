import sys
sys.path.insert(0, r'D:\gearbox-selector')
from app import engine

def kwargs_to_str(kw, rpm, gr, gt, vid):
    return f"{kw}kW {rpm}rpm gr={gr} {gt} v{vid}"

cases = [
    (400, 1480, '17:1', 'any', 1),
    (45, 1480, '24:1', 'any', 1),
    (260, 1480, '13:1', 'any', 1),
    (100, 1500, '13', 'bevel_helical', 3),
    (100, 1500, '10:1', 'bevel_helical', 3),
    (250, 1500, '9.3', 'bevel_helical', 3),
    (500, 1470, '15:1', 'helical', 3),
]
for kw, rpm, gr, gt, vid in cases:
    r = engine.select(kw=kw, rpm=rpm, gr=gr, gear_type=gt, hb='YES',
                      cooling='FAN', lubrication='SPLASH', sf=1.25, vendor_id=vid)
    top = r['candidates'][0]
    print(f"{kwargs_to_str(kw,rpm,gr,gt,vid)} -> {top['model']} "
          f"pw={top['power_kw']} pn={top['required_pn']} pw_ok={top['power_ok']}")