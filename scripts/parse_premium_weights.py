#!/usr/bin/env python3
"""Parse weight tables from Premium PDF and insert into dimension table."""
import pdfplumber
import psycopg

DB = 'postgresql://gearbox:gearbox@localhost:5433/gearbox'

SERIES_MAP = {
    'H1': 'H1',
    'H2': 'H2', 'H2SF': 'H2',
    'H3': 'H3', 'H3SF': 'H3',
    'H4': 'H4', 'H4SF': 'H4',
    'B2': 'B2', 'B2SF': 'B2',
    'B3': 'B3', 'B3SF': 'B3',
    'B4': 'B4', 'B4SF': 'B4',
}

VENDOR_CODE = 'premium'

def get_vendor_id(conn):
    row = conn.execute("SELECT id FROM vendor WHERE code = %s", (VENDOR_CODE,)).fetchone()
    return row[0] if row else None

def get_series_id(conn, vendor_id, series_code):
    row = conn.execute(
        "SELECT id FROM gear_series WHERE vendor_id = %s AND series_code = %s",
        (vendor_id, series_code)
    ).fetchone()
    return row[0] if row else None

def get_size_id(conn, vendor_id, series_id, size):
    row = conn.execute(
        "SELECT id FROM gear_size WHERE vendor_id = %s AND series_id = %s AND size = %s",
        (vendor_id, series_id, size)
    ).fetchone()
    return row[0] if row else None

def parse_horizontal_weights(text):
    lines = text.split('\n')
    weights = []
    in_table = False
    sizes = []
    
    for line in lines:
        line_stripped = line.strip()
        if 'NetWeightsforHorizontalUnits' in line_stripped.replace(' ', ''):
            in_table = True
            continue
        if in_table and 'UnitType' in line_stripped and '140' in line_stripped:
            parts = line_stripped.split()
            for p in parts:
                if p.isdigit():
                    sizes.append(int(p))
            continue
        if in_table and line_stripped:
            parts = line_stripped.split()
            if parts and parts[0] in SERIES_MAP:
                unit_type = parts[0]
                for idx, size in enumerate(sizes):
                    if idx + 1 < len(parts):
                        w = parts[idx + 1]
                        if w != '*' and w != '-':
                            try:
                                weights.append((unit_type, size, float(w)))
                            except ValueError:
                                pass
        if in_table and ('Referto' in line_stripped or 'Asimprovements' in line_stripped):
            break
    return weights

def main():
    pdf_path = r'C:\Users\konka\Downloads\ilovepdf_split-range\Premium helical gearboxes catalogue-48-95.pdf'
    
    with pdfplumber.open(pdf_path) as pdf, psycopg.connect(DB) as conn:
        vendor_id = get_vendor_id(conn)
        if not vendor_id:
            print("Vendor not found")
            return
        
        p = pdf.pages[25]
        text = p.extract_text()
        
        weights = parse_horizontal_weights(text)
        print(f"Parsed {len(weights)} weight entries")
        for w in weights[:5]:
            print(f"  {w}")
        
        inserted = 0
        for unit_type, size, weight in weights:
            series_code = SERIES_MAP[unit_type]
            series_id = get_series_id(conn, vendor_id, series_code)
            if not series_id:
                continue
            size_id = get_size_id(conn, vendor_id, series_id, str(size))
            if not size_id:
                continue
            
            conn.execute('''
                INSERT INTO dimension (vendor_id, gear_size_id, dim_name, weight_kg, source_page)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
            ''', (vendor_id, size_id, 'net_weight', weight, 73))
            inserted += 1
        
        conn.commit()
        print(f"Inserted {inserted} weight records")

if __name__ == '__main__':
    main()