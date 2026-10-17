#!/usr/bin/env python3
"""Parse Premium helical gearboxes catalogue and insert into DB."""
import re
import pdfplumber
import psycopg
from typing import List, Dict, Tuple

DB = 'postgresql://gearbox:gearbox@localhost:5433/gearbox'

# Premium catalogue type mapping
TYPE_INFO = {
    'H1': {'series': 'H1', 'reduction': 'single', 'shaft': 'parallel', 'gear_type': 'helical'},
    'H2': {'series': 'H2', 'reduction': 'double', 'shaft': 'parallel', 'gear_type': 'helical'},
    'H3': {'series': 'H3', 'reduction': 'triple', 'shaft': 'parallel', 'gear_type': 'helical'},
    'H4': {'series': 'H4', 'reduction': 'quadruple', 'shaft': 'parallel', 'gear_type': 'helical'},
    'B2': {'series': 'B2', 'reduction': 'double', 'shaft': 'right_angle', 'gear_type': 'bevel_helical'},
    'B3': {'series': 'B3', 'reduction': 'triple', 'shaft': 'right_angle', 'gear_type': 'bevel_helical'},
    'B4': {'series': 'B4', 'reduction': 'quadruple', 'shaft': 'right_angle', 'gear_type': 'bevel_helical'},
}

CATALOG_SPEEDS = (1500, 1000, 750)
VENDOR_CODE = 'premium'
VENDOR_NAME = 'Premium Helical Gearboxes'

def get_vendor_id(conn):
    row = conn.execute("SELECT id FROM vendor WHERE code = %s", (VENDOR_CODE,)).fetchone()
    if row:
        return row[0]
    row = conn.execute(
        "INSERT INTO vendor (code, name, description) VALUES (%s, %s, %s) RETURNING id",
        (VENDOR_CODE, VENDOR_NAME, 'Premium helical gearboxes catalogue')
    ).fetchone()
    return row[0]

def get_or_create_series(conn, vendor_id, series_code, gear_type, description):
    row = conn.execute(
        "SELECT id FROM gear_series WHERE vendor_id = %s AND series_code = %s",
        (vendor_id, series_code)
    ).fetchone()
    if row:
        return row[0]
    row = conn.execute(
        "INSERT INTO gear_series (vendor_id, series_code, gear_type, description) VALUES (%s, %s, %s, %s) RETURNING id",
        (vendor_id, series_code, gear_type, description)
    ).fetchone()
    return row[0]

def get_or_create_size(conn, vendor_id, series_id, size):
    row = conn.execute(
        "SELECT id FROM gear_size WHERE vendor_id = %s AND series_id = %s AND size = %s",
        (vendor_id, series_id, size)
    ).fetchone()
    if row:
        return row[0]
    row = conn.execute(
        "INSERT INTO gear_size (vendor_id, series_id, size) VALUES (%s, %s, %s) RETURNING id",
        (vendor_id, series_id, size)
    ).fetchone()
    return row[0]

def parse_mechanical_table(text: str) -> List[Dict]:
    """Parse mechanical capacities table from page text."""
    results = []
    
    # Normalize text
    text = text.replace('MECHANICALCAPACITIES', 'MECHANICAL CAPACITIES')
    text = text.replace('THERMALCAPACITIES', 'THERMAL CAPACITIES')
    text = text.replace('UnitSize', 'Unit Size')
    text = text.replace('NominalRatiosareshown', 'Nominal Ratios are shown')
    text = text.replace('ForHigherSizeUnits', 'For Higher Size Units')
    
    lines = text.split('\n')
    
    in_mechanical = False
    header_sizes = []
    header_found = False
    
    for line in lines:
        line = line.strip()
        
        # Detect start of mechanical table
        if 'MECHANICAL CAPACITIES' in line.upper():
            in_mechanical = True
            continue
            
        # Detect header row with sizes (line like "rpm Speed 140 160 180 ...")
        if in_mechanical and 'rpm' in line.lower() and 'Speed' in line:
            parts = line.split()
            for p in parts:
                if p.isdigit():
                    header_sizes.append(int(p))
            header_found = True
            continue
            
        # Skip the "rpm" line after sizes
        if in_mechanical and header_found and line.lower() == 'rpm':
            continue
            
        # Detect end of mechanical table
        if in_mechanical and 'THERMAL CAPACITIES' in line.upper():
            break
            
        if in_mechanical and line and header_sizes:
            parts = line.split()
            if len(parts) >= 4:
                try:
                    # Data format: ratio input_speed output_speed power1 power2 ...
                    # First column is ratio (e.g., 1.22), then 1500/1000/750, then output_speed, then powers
                    first = parts[0]
                    if first.replace('.','').isdigit():
                        ratio = float(parts[0])
                        input_speed = int(parts[1])
                        output_speed = int(parts[2])
                        power_vals = []
                        for v in parts[3:]:
                            v_clean = v.rstrip('*')
                            if v_clean.replace('.','').isdigit():
                                power_vals.append((float(v_clean), v.endswith('*')))
                        
                        if len(power_vals) == len(header_sizes):
                            for size, (pw, forced) in zip(header_sizes, power_vals):
                                results.append({
                                    'ratio': ratio,
                                    'n1_rpm': input_speed,
                                    'n2_rpm': output_speed,
                                    'size': size,
                                    'power_kw': pw,
                                    'forced_lube': forced
                                })
                except (ValueError, IndexError):
                    pass
    
    return results

def parse_thermal_table(text: str) -> List[Dict]:
    """Parse thermal capacities table from page text."""
    results = []
    
    # Normalize
    text = text.replace('MECHANICALCAPACITIES', 'MECHANICAL CAPACITIES')
    text = text.replace('THERMALCAPACITIES', 'THERMAL CAPACITIES')
    text = text.replace('UnitSize', 'Unit Size')
    text = text.replace('NominalRatiosareshown', 'Nominal Ratios are shown')
    text = text.replace('ForHigherSizeUnits', 'For Higher Size Units')
    text = text.replace('Unitswithoutfan', 'Units without fan')
    text = text.replace('UnitswithFanCooling', 'Units with Fan Cooling')
    text = text.replace('FullLoadEfficiency', 'Full Load Efficiency')
    
    lines = text.split('\n')
    
    in_thermal = False
    header_sizes = []
    cooling_mode = None  # 'without_fan' or 'with_fan'
    header_found = False
    
    for line in lines:
        line = line.strip()
        
        if 'THERMAL CAPACITIES' in line.upper():
            in_thermal = True
            continue
            
        if in_thermal:
            # Detect cooling mode sections
            if 'UNITS WITHOUT FAN' in line.upper():
                cooling_mode = 'without_fan'
                continue
            if 'UNITS WITH FAN' in line.upper() or 'UNITS WITH FAN COOLING' in line.upper():
                cooling_mode = 'with_fan'
                continue
            if 'FULL LOAD EFFICIENCY' in line.upper():
                break
                
            # Detect header row with sizes
            if in_thermal and 'rpm' in line.lower() and 'Speed' not in line and header_sizes == []:
                parts = line.split()
                for p in parts:
                    if p.isdigit():
                        header_sizes.append(int(p))
                header_found = True
                continue
                
            if in_thermal and cooling_mode and header_found and header_sizes and line:
                parts = line.split()
                if len(parts) >= 3:
                    try:
                        # Thermal format: ratio input_speed thermal1 thermal2 ... (no output_speed)
                        # Some rows start with "To" for 1000 rpm continuation
                        first = parts[0]
                        
                        if first == 'To':
                            # Continuation row for 1000 rpm
                            ratio = prev_ratio
                            input_speed = 1000
                            thermal_vals = parts[1:]
                        else:
                            ratio = float(parts[0])
                            input_speed = int(parts[1])
                            thermal_vals = parts[2:]
                            prev_ratio = ratio
                            prev_input_speed = input_speed
                        
                        thermal_values = []
                        for v in thermal_vals:
                            if v.replace('.','').isdigit():
                                thermal_values.append(float(v))
                        
                        if len(thermal_values) == len(header_sizes):
                            for size, pw in zip(header_sizes, thermal_values):
                                results.append({
                                    'ratio': ratio,
                                    'n1_rpm': input_speed,
                                    'size': size,
                                    'thermal_kw': pw,
                                    'cooling_type': 'FAN' if cooling_mode == 'with_fan' else 'NONE'
                                })
                    except (ValueError, IndexError):
                        pass
    
    return results

def process_pdf(pdf_path: str, vendor_id: int):
    """Process the Premium catalogue PDF."""
    all_mechanical = []
    all_thermal = []
    
    with pdfplumber.open(pdf_path) as pdf:
        print(f"Processing {len(pdf.pages)} pages...")
        
        for i, page in enumerate(pdf.pages):
            text = page.extract_text()
            if not text:
                continue
                
            # Check if this is an actual ratings page (has RATINGS header and Type H1/H2/H3/H4/B2/B3/B4)
            if 'RATINGS' in text.upper() and ('TYPE H1' in text.upper() or 'TYPE H2' in text.upper() 
                or 'TYPE H3' in text.upper() or 'TYPE H4' in text.upper()
                or 'TYPE B2' in text.upper() or 'TYPE B3' in text.upper() or 'TYPE B4' in text.upper()):
                print(f"  Page {i+1}: Found ratings table")
                mech = parse_mechanical_table(text)
                therm = parse_thermal_table(text)
                print(f"    Mechanical rows: {len(mech)}, Thermal rows: {len(therm)}")
                all_mechanical.extend(mech)
                all_thermal.extend(therm)
    
    print(f"Total mechanical: {len(all_mechanical)}, thermal: {len(all_thermal)}")
    return all_mechanical, all_thermal

def insert_data(mechanical: List[Dict], thermal: List[Dict], vendor_id: int):
    """Insert parsed data into database."""
    with psycopg.connect(DB) as conn:
        with conn.transaction():
            # Determine series from data
            series_codes = set()
            for row in mechanical + thermal:
                # We need to infer series from ratio/size/type
                pass
            
            # Group by type/series
            # For now, create all known series
            for type_code, info in TYPE_INFO.items():
                series_id = get_or_create_series(conn, vendor_id, info['series'], info['gear_type'], 
                    f"{info['reduction'].title()} reduction {info['shaft']}")
                
                # Get sizes for this type from mechanical data
                sizes = set()
                ratios = set()
                for row in mechanical:
                    # We need to know which type this row belongs to
                    pass
            
            # Since the PDF doesn't clearly separate by type in each row,
            # we need a different approach - parse by page sections
            
    print("Data insertion logic needs refinement - see page structure")

def main():
    pdf1 = r'C:\Users\konka\Downloads\ilovepdf_split-range\Premium helical gearboxes catalogue-1-47.pdf'
    pdf2 = r'C:\Users\konka\Downloads\ilovepdf_split-range\Premium helical gearboxes catalogue-48-95.pdf'
    
    with psycopg.connect(DB) as conn:
        vendor_id = get_vendor_id(conn)
        print(f"Vendor ID: {vendor_id}")
    
    # Process first PDF (ratings)
    mech, therm = process_pdf(pdf1, vendor_id)
    
    # Show sample data
    print("\nSample mechanical:")
    for r in mech[:5]:
        print(f"  {r}")
    print("\nSample thermal:")
    for r in therm[:5]:
        print(f"  {r}")

if __name__ == '__main__':
    main()