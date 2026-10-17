#!/usr/bin/env python3
"""Parse Premium helical gearboxes catalogue - fixed with 1500 rpm buffering."""
import re
import pdfplumber
import psycopg

DB = 'postgresql://gearbox:gearbox@localhost:5433/gearbox'

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

def get_vendor_id(conn):
    row = conn.execute("SELECT id FROM vendor WHERE code = %s", (VENDOR_CODE,)).fetchone()
    return row[0] if row else conn.execute(
        "INSERT INTO vendor (code, name, description) VALUES (%s, %s, %s) RETURNING id",
        (VENDOR_CODE, 'Premium Helical Gearboxes', 'Premium helical gearboxes catalogue')
    ).fetchone()[0]

def get_or_create_series(conn, vendor_id, series_code, gear_type):
    row = conn.execute(
        "SELECT id FROM gear_series WHERE vendor_id = %s AND series_code = %s",
        (vendor_id, series_code)
    ).fetchone()
    if row:
        return row[0]
    return conn.execute(
        "INSERT INTO gear_series (vendor_id, series_code, gear_type, description) VALUES (%s, %s, %s, %s) RETURNING id",
        (vendor_id, series_code, gear_type, f'Premium {series_code} series')
    ).fetchone()[0]

def get_or_create_size(conn, vendor_id, series_id, size):
    row = conn.execute(
        "SELECT id FROM gear_size WHERE vendor_id = %s AND series_id = %s AND size = %s",
        (vendor_id, series_id, size)
    ).fetchone()
    if row:
        return row[0]
    return conn.execute(
        "INSERT INTO gear_size (vendor_id, series_id, size) VALUES (%s, %s, %s) RETURNING id",
        (vendor_id, series_id, size)
    ).fetchone()[0]

def parse_page_type(text):
    for line in text.split('\n')[:5]:
        line = line.strip().upper()
        if line.startswith('TYPE '):
            match = re.search(r'TYPE\s+([HB]\d+)', line)
            if match:
                return match.group(1)
    return None

def extract_sizes(text):
    for line in text.split('\n'):
        if 'rpm' in line.lower() and 'Speed' in line:
            parts = line.split()
            sizes = []
            for p in parts[2:]:
                if p.isdigit():
                    sizes.append(int(p))
            if sizes:
                return sizes
    return []

def parse_ratings(text, sizes):
    lines = text.split('\n')
    results = {'mech': [], 'therm': []}
    in_mech = False
    in_therm = False
    current_ratio = None
    current_cooling = None
    pending_1500 = None  # Buffer for 1500 rpm row that belongs to NEXT ratio
    
    def make_mech_row(ratio, n1, n2, pw, forced, size):
        return {'ratio': ratio, 'n1': n1, 'n2': n2, 'size': size, 'power': pw, 'forced': forced}
    
    def make_therm_row(ratio, n1, pw, size, cooling):
        return {'ratio': ratio, 'n1': n1, 'size': size, 'power': pw, 'cooling': cooling}
    
    def assign_powers(ratio, n1, n2, powers, section, cooling):
        for idx, (pw, forced) in enumerate(powers):
            if idx >= len(sizes):
                break
            size = sizes[idx]
            if section == 'mech':
                results['mech'].append(make_mech_row(ratio, n1, n2, pw, forced, size))
            elif section == 'therm' and cooling:
                results['therm'].append(make_therm_row(ratio, n1, pw, size, cooling))
    
    for line in lines:
        line_stripped = line.strip()
        if not line_stripped:
            continue
        upper = line_stripped.upper()
        
        if 'MECHANICAL CAPACITIES' in upper or 'MECHANICALCAPACITIES' in upper:
            in_mech = True
            in_therm = False
            current_ratio = None
            current_cooling = None
            pending_1500 = None
            continue
        if 'THERMAL CAPACITIES' in upper or 'THERMALCAPACITIES' in upper:
            in_mech = False
            in_therm = True
            current_ratio = None
            current_cooling = None
            pending_1500 = None
            continue
        if 'FULL LOAD EFFICIENCY' in upper or 'BASED ON COOLING' in upper:
            in_therm = False
            continue
        if 'UNITS WITHOUT FAN' in upper:
            current_cooling = 'none'
            continue
        if 'UNITS WITH FAN' in upper or 'UNITS WITH COOLING' in upper:
            current_cooling = 'fan'
            continue
        if any(kw in upper for kw in ['NOMINAL RATIOS', 'INTERPOLATE', 'FOR HIGHER', 'REFER', 'PREMIUM']):
            continue
        
        if not in_mech and not in_therm:
            continue
            
        parts = line_stripped.split()
        if len(parts) < 3:
            continue
            
        first = parts[0]
        try:
            val = float(first)
        except ValueError:
            continue
        
        is_1500 = (val == 1500 and len(parts) > 2 and 
                   parts[1].replace('.', '', 1).replace('-', '', 1).isdigit())
        is_750 = (val == 750 and len(parts) > 2 and 
                  parts[1].replace('.', '', 1).replace('-', '', 1).isdigit())
        is_1000 = (val == 1000 and len(parts) > 2 and 
                   parts[1].replace('.', '', 1).replace('-', '', 1).isdigit())
        
        # 1500 rpm row: belongs to NEXT ratio, buffer it
        if is_1500:
            try:
                n2 = float(parts[1])
            except ValueError:
                continue
            powers = []
            for tok in parts[2:]:
                tok = tok.strip()
                if not tok or tok == '-':
                    continue
                forced = tok.endswith('*')
                tok_clean = tok.rstrip('*')
                try:
                    pw = float(tok_clean)
                    powers.append((pw, forced))
                except ValueError:
                    pass
            if powers:
                pending_1500 = {
                    'n1': 1500, 'n2': n2, 'powers': powers,
                    'section': 'mech' if in_mech else 'therm',
                    'cooling': current_cooling
                }
            continue
        
        # Ratio row: first assign any pending 1500 to THIS ratio
        if not (is_750 or is_1000):
            ratio = val
            if len(parts) < 3:
                continue
            try:
                n1 = int(parts[1])
                n2 = float(parts[2])
            except (ValueError, IndexError):
                continue
            powers = []
            for tok in parts[3:]:
                tok = tok.strip()
                if not tok or tok == '-':
                    continue
                forced = tok.endswith('*')
                tok_clean = tok.rstrip('*')
                try:
                    pw = float(tok_clean)
                    powers.append((pw, forced))
                except ValueError:
                    pass
            
            if not powers:
                continue
            
            # Assign buffered 1500 rpm row to this new ratio
            if pending_1500:
                p = pending_1500
                assign_powers(ratio, p['n1'], p['n2'], p['powers'], p['section'], p['cooling'])
                pending_1500 = None
            
            # Assign 1000 rpm data from ratio row
            assign_powers(ratio, n1, n2, powers, 'mech' if in_mech else 'therm', current_cooling)
            current_ratio = ratio
            continue
        
        # 750 rpm row (and any standalone 1000): assign to current_ratio
        if is_750 or is_1000:
            if current_ratio is None:
                continue
            try:
                n2 = float(parts[1])
            except ValueError:
                continue
            powers = []
            for tok in parts[2:]:
                tok = tok.strip()
                if not tok or tok == '-':
                    continue
                forced = tok.endswith('*')
                tok_clean = tok.rstrip('*')
                try:
                    pw = float(tok_clean)
                    powers.append((pw, forced))
                except ValueError:
                    pass
            if powers:
                assign_powers(current_ratio, int(val), n2, powers, 'mech' if in_mech else 'therm', current_cooling)
            continue

    return results

def process_pdf(pdf_path, page_start, page_end):
    with pdfplumber.open(pdf_path) as pdf, psycopg.connect(DB) as conn:
        vendor_id = get_vendor_id(conn)
        
        for page_idx in range(page_start, page_end):
            if page_idx >= len(pdf.pages):
                break
            page = pdf.pages[page_idx]
            text = page.extract_text()
            if not text:
                continue
                
            type_code = parse_page_type(text)
            if not type_code:
                continue
                
            series_code = TYPE_MAPPING.get(type_code)
            if not series_code:
                continue
                
            gear_type = 'helical' if series_code.startswith('H') else 'bevel_helical'
            series_id = get_or_create_series(conn, vendor_id, series_code, gear_type)
            
            sizes = extract_sizes(text)
            if not sizes:
                continue
                
            results = parse_ratings(text, sizes)
            
            print(f"Page {page_idx+1} ({type_code}->{series_code}): {len(results['mech'])} mech, {len(results['therm'])} therm")
            
            for row in results['mech']:
                size_id = get_or_create_size(conn, vendor_id, series_id, str(row['size']))
                conn.execute('''
                    INSERT INTO power_rating (vendor_id, gear_size_id, ratio_iN, n1_rpm, n2_rpm, power_kw, requires_forced_lube, source_page)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                ''', (vendor_id, size_id, str(row['ratio']), row['n1'], row['n2'],
                      row['power'], row['forced'], page_idx+1))
            
            for row in results['therm']:
                size_id = get_or_create_size(conn, vendor_id, series_id, str(row['size']))
                conn.execute('''
                    INSERT INTO thermal_capacity (vendor_id, gear_size_id, cooling_type, ratio_in, amb_temp_c, ed_pct, power_kw, source_page, n1_rpm)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                ''', (vendor_id, size_id, row['cooling'], str(row['ratio']), 20, 100,
                      row['power'], page_idx+1, row['n1']))

if __name__ == '__main__':
    pdf1 = r'C:\Users\konka\Downloads\ilovepdf_split-range\Premium helical gearboxes catalogue-1-47.pdf'
    pdf2 = r'C:\Users\konka\Downloads\ilovepdf_split-range\Premium helical gearboxes catalogue-48-95.pdf'
    
    with psycopg.connect(DB) as conn:
        conn.execute('DELETE FROM thermal_capacity WHERE vendor_id = 3')
        conn.execute('DELETE FROM power_rating WHERE vendor_id = 3')
        conn.execute('DELETE FROM gear_size WHERE vendor_id = 3')
        conn.execute('DELETE FROM gear_series WHERE vendor_id = 3')
        conn.commit()
    print("Cleared old data")
    
    process_pdf(pdf1, 12, 26)
    process_pdf(pdf2, 0, 48)
    print("Done!")