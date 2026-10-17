#!/usr/bin/env python3
"""Parse Premium helical gearboxes catalogue and insert into DB - complete version."""
import re
import pdfplumber
import psycopg
from typing import List, Dict

DB = 'postgresql://gearbox:gearbox@localhost:5433/gearbox'

# Map PDF type names to our series codes
TYPE_MAPPING = {
    'H1': 'H1',
    'H2': 'H2', 'H2SF': 'H2', 'VH2': 'H2', 'VH2 SA': 'H2', 'VH2 CT': 'H2',
    'H3': 'H3', 'H3SF': 'H3', 'VH3': 'H3', 'VH3 SA': 'H3', 'VH3 CT': 'H3',
    'H4': 'H4', 'H4SF': 'H4',
    'B2': 'B2', 'B2SF': 'B2', 'VB2': 'B2', 'VB2 SA': 'B2', 'VB2 CT': 'B2',
    'B3': 'B3', 'B3SF': 'B3', 'VB3': 'B3', 'VB3 SA': 'B3', 'VB3 CT': 'B3',
    'B4': 'B4', 'B4SF': 'B4',
}

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

def get_or_create_series(conn, vendor_id, series_code, gear_type):
    row = conn.execute(
        "SELECT id FROM gear_series WHERE vendor_id = %s AND series_code = %s",
        (vendor_id, series_code)
    ).fetchone()
    if row:
        return row[0]
    row = conn.execute(
        "INSERT INTO gear_series (vendor_id, series_code, gear_type, description) VALUES (%s, %s, %s, %s) RETURNING id",
        (vendor_id, series_code, gear_type, f'Premium {series_code} series')
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

def normalize_text(text: str) -> str:
    return (text
        .replace('MECHANICALCAPACITIES', 'MECHANICAL CAPACITIES')
        .replace('MECHANICALANDTHERMALCAPACITIES', 'MECHANICAL AND THERMAL CAPACITIES')
        .replace('THERMALCAPACITIES', 'THERMAL CAPACITIES')
        .replace('UnitSize', 'Unit Size')
        .replace('NominalInput', 'Nominal Input')
        .replace('NominalRatiosareshown', 'Nominal Ratios are shown')
        .replace('ForHigherSizeUnits', 'For Higher Size Units')
        .replace('Unitswithoutfan', 'Units without fan')
        .replace('UnitswithFanCooling', 'Units with Fan Cooling')
        .replace('UnitswithCoolingCoils', 'Units with Cooling Coils')
        .replace('UnitswithFanandCoolingCoils', 'Units with Fan and Cooling Coils')
        .replace('FullLoadEfficiency', 'Full Load Efficiency')
        .replace('Basedoncoolingwater', 'Based on cooling water')
        .replace('Forcapacitieshigherthanabove', 'For capacities higher than above')
        .replace('Nominalratiosareshown', 'Nominal ratios are shown')
        .replace('Interpolateforotherin', 'Interpolate for other in')
    )

def parse_page_type(text: str) -> str:
    """Extract type code from page header like 'Type H1' or 'Type H2-H2SF-VH2...'."""
    for line in text.split('\n')[:5]:
        line = line.strip()
        if line.upper().startswith('TYPE '):
            # Extract first type code (e.g., 'H1' from 'Type H1' or 'H2' from 'Type H2-H2SF...')
            match = re.search(r'TYPE\s+([HB]\d+)', line.upper())
            if match:
                return match.group(1)
    return None

def parse_mechanical(text: str, sizes: List[int]) -> List[Dict]:
    """Parse mechanical capacities table."""
    results = []
    text = normalize_text(text)
    lines = text.split('\n')
    
    in_mech = False
    header_found = False
    prev_ratio = None
    
    for line in lines:
        line = line.strip()
        
        if 'MECHANICAL CAPACITIES' in line.upper():
            in_mech = True
            continue
            
        if in_mech and 'rpm' in line.lower() and 'Speed' in line and not header_found:
            # Extract sizes
            parts = line.split()
            sizes.clear()
            for p in parts:
                if p.isdigit():
                    sizes.append(int(p))
            header_found = True
            continue
            
        if in_mech and header_found and line.lower() == 'rpm':
            continue
            
        if in_mech and 'THERMAL CAPACITIES' in line.upper():
            break
            
        if in_mech and line and header_found and sizes:
            # Skip separator lines
            if line == '-' or line.startswith('REFER') or line.startswith('PREMIUM') \
               or line.startswith('NOMINAL') or line.startswith('INTERPOLATE') \
               or line.startswith('FOR HIGHER') or line.startswith('A CASE'):
                continue
                
            parts = line.split()
            if len(parts) >= 4:
                try:
                    first = parts[0]
                    if first.replace('.','').isdigit():
                        val = float(first)
                        if val in (1500, 1000, 750):
                            # Speed row without ratio - use previous ratio
                            ratio = prev_ratio
                            input_speed = int(first)
                            output_speed = int(parts[1])
                            power_vals = parts[2:]
                        else:
                            ratio = val
                            input_speed = int(parts[1])
                            output_speed = int(parts[2])
                            power_vals = parts[3:]
                            prev_ratio = ratio
                        
                        pws = []
                        for v in power_vals:
                            v_clean = v.rstrip('*')
                            if v_clean.replace('.','').isdigit():
                                pws.append((float(v_clean), v.endswith('*')))
                        
                        # Handle partial rows (fewer power values than sizes)
                        # Only add entries for sizes that have power values
                        for idx, (pw, forced) in enumerate(pws):
                            if idx < len(sizes):
                                results.append({
                                    'ratio': ratio,
                                    'n1_rpm': input_speed,
                                    'n2_rpm': output_speed,
                                    'size': sizes[idx],
                                    'power_kw': pw,
                                    'forced_lube': forced
                                })
                except (ValueError, IndexError):
                    pass
    
    return results

def parse_thermal(text: str, sizes: List[int]) -> List[Dict]:
    """Parse thermal capacities table. Uses sizes from mechanical table."""
    results = []
    text = normalize_text(text)
    lines = text.split('\n')
    
    in_thermal = False
    cooling_mode = None
    prev_ratio = None
    
    for line in lines:
        line = line.strip()
        
        if 'THERMAL CAPACITIES' in line.upper():
            in_thermal = True
            continue
            
        if in_thermal:
            if 'UNITS WITHOUT FAN' in line.upper():
                cooling_mode = 'without_fan'
                continue
            if 'UNITS WITH FAN' in line.upper() or 'UNITS WITH FAN COOLING' in line.upper() \
               or 'UNITS WITH COOLING COILS' in line.upper() or 'UNITS WITH FAN AND COOLING COILS' in line.upper():
                cooling_mode = 'with_fan'
                continue
            if 'FULL LOAD EFFICIENCY' in line.upper() or 'BASED ON COOLING' in line.upper():
                break
                
            if in_thermal and cooling_mode and sizes and line:
                parts = line.split()
                if len(parts) >= 3:
                    try:
                        first = parts[0]
                        
                        if first == 'To':
                            ratio = prev_ratio
                            input_speed = 1000
                            thermal_vals = parts[1:]
                        else:
                            ratio = float(parts[0])
                            input_speed = int(parts[1])
                            thermal_vals = parts[2:]
                            prev_ratio = ratio
                        
                        thermal_values = []
                        for v in thermal_vals:
                            if v.replace('.','').isdigit():
                                thermal_values.append(float(v))
                        
                        # Handle partial rows
                        for idx, pw in enumerate(thermal_values):
                            if idx < len(sizes):
                                results.append({
                                    'ratio': ratio,
                                    'n1_rpm': input_speed,
                                    'size': sizes[idx],
                                    'thermal_kw': pw,
                                    'cooling_type': 'fan' if cooling_mode == 'with_fan' else 'none'
                                })
                    except (ValueError, IndexError):
                        pass
    
    return results

def process_all_pages():
    """Process both PDFs and insert into DB."""
    pdf1 = r'C:\Users\konka\Downloads\ilovepdf_split-range\Premium helical gearboxes catalogue-1-47.pdf'
    pdf2 = r'C:\Users\konka\Downloads\ilovepdf_split-range\Premium helical gearboxes catalogue-48-95.pdf'
    
    with psycopg.connect(DB) as conn:
        vendor_id = get_vendor_id(conn)
        print(f"Vendor ID: {vendor_id}")
        
        # Process PDF 1 (ratings pages 13-26 = indices 12-25)
        with pdfplumber.open(pdf1) as pdf:
            for page_idx in range(12, 26):
                page = pdf.pages[page_idx]
                text = page.extract_text()
                if not text:
                    continue
                    
                type_code = parse_page_type(text)
                if not type_code:
                    continue
                
                series_code = TYPE_MAPPING.get(type_code)
                if not series_code:
                    print(f"  Page {page_idx+1}: Unknown type {type_code}")
                    continue
                
                gear_type = 'helical' if series_code.startswith('H') else 'bevel_helical'
                series_id = get_or_create_series(conn, vendor_id, series_code, gear_type)
                
                # Parse mechanical and thermal
                sizes = []
                print(f"  Page {page_idx+1} sizes id: {id(sizes)}")
                mech = parse_mechanical(text, sizes)
                therm = parse_thermal(text, sizes)
                
                print(f"Page {page_idx+1} ({type_code} -> {series_code}): mech={len(mech)}, therm={len(therm)}, sizes={sizes}")
                
                # Insert mechanical
                for row in mech:
                    size_id = get_or_create_size(conn, vendor_id, series_id, str(row['size']))
                    conn.execute('''
                        INSERT INTO power_rating (vendor_id, gear_size_id, ratio_in, n1_rpm, n2_rpm, power_kw, requires_forced_lube, source_page)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT DO NOTHING
                    ''', (vendor_id, size_id, str(row['ratio']), row['n1_rpm'], row['n2_rpm'], 
                          row['power_kw'], row['forced_lube'], page_idx+1))
                
                # Insert thermal (amb_temp_c=20, ed_pct=100 for standard)
                for row in therm:
                    size_id = get_or_create_size(conn, vendor_id, series_id, str(row['size']))
                    conn.execute('''
                        INSERT INTO thermal_capacity (vendor_id, gear_size_id, cooling_type, ratio_in, amb_temp_c, ed_pct, power_kw, source_page, n1_rpm)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT DO NOTHING
                    ''', (vendor_id, size_id, row['cooling_type'], str(row['ratio']), 20, 100,
                          row['thermal_kw'], page_idx+1, row['n1_rpm']))

if __name__ == '__main__':
    process_all_pages()
    print("Done!")