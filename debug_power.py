import sys
sys.path.insert(0, r'D:\gearbox-selector')
from app import engine

# Debug the power dict
power = engine._power_by_series(1500, 3)
print("Power dict keys:", list(power.keys()))
for code in ['B2', 'B3', 'B4']:
    if code in power:
        print(f"  {code}: ratios = {list(power[code].keys())}")
    else:
        print(f"  {code}: NOT IN POWER")