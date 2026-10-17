import sys
sys.path.insert(0, r'D:\gearbox-selector')
from app import engine

# Trace through select for bevel_helical
from app.engine import _num, _get_vendor_series

vendor_id = 3
vendor_series = _get_vendor_series(vendor_id)
print("Vendor series:", vendor_series)

power = engine._power_by_series(1500, vendor_id)

for code in ['B2', 'B3', 'B4']:
    if code not in power:
        continue
    ratios = [r for r in power[code]]
    ratios.sort(key=_num)
    print(f"\n{code}: ratios = {ratios}")
    
    # Find best ratio for gr=13
    ratio_req = 13.0
    best_ratio = min(ratios, key=lambda r: abs(_num(r) - ratio_req))
    print(f"  best_ratio = {best_ratio} (diff = {abs(_num(best_ratio) - ratio_req)})")
    
    sz_vals = power[code][best_ratio]
    sizes = sorted(sz_vals, key=lambda s: int(s))
    print(f"  sizes = {sizes}")
    print(f"  sz_vals = {sz_vals}")