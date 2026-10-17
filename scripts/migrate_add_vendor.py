#!/usr/bin/env python3
"""Migration: Add multi-vendor support to database."""
import psycopg

DB = 'postgresql://gearbox:gearbox@localhost:5433/gearbox'

def migrate():
    conn = psycopg.connect(DB, autocommit=True)

    # 1. Create vendor table
    conn.execute('''
        CREATE TABLE IF NOT EXISTS vendor (
            id SERIAL PRIMARY KEY,
            code TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            description TEXT,
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT NOW()
        )
    ''')
    print("Created vendor table")

    # Insert Elecon as default vendor
    conn.execute('''
        INSERT INTO vendor (code, name, description)
        VALUES ('elecon', 'Elecon', 'Elecon Engineering EON/EOS Series')
        ON CONFLICT (code) DO NOTHING
    ''')
    print("Inserted default vendor: elecon")

    # Get elecon vendor_id
    elecon_id = conn.execute("SELECT id FROM vendor WHERE code = 'elecon'").fetchone()[0]
    print(f"Elecon vendor_id: {elecon_id}")

    # 2. Add vendor_id to gear_series
    conn.execute('ALTER TABLE gear_series ADD COLUMN IF NOT EXISTS vendor_id INTEGER')
    conn.execute(f'UPDATE gear_series SET vendor_id = {elecon_id} WHERE vendor_id IS NULL')
    conn.execute(f'ALTER TABLE gear_series ALTER COLUMN vendor_id SET NOT NULL')
    conn.execute(f'ALTER TABLE gear_series ADD CONSTRAINT fk_gear_series_vendor FOREIGN KEY (vendor_id) REFERENCES vendor(id)')
    print("Added vendor_id to gear_series")

    # 3. Add vendor_id to gear_size (via gear_series FK, but add direct for convenience)
    conn.execute('ALTER TABLE gear_size ADD COLUMN IF NOT EXISTS vendor_id INTEGER')
    conn.execute(f'''
        UPDATE gear_size gs
        SET vendor_id = gs2.vendor_id
        FROM gear_series gs2
        WHERE gs.series_id = gs2.id AND gs.vendor_id IS NULL
    ''')
    conn.execute(f'ALTER TABLE gear_size ALTER COLUMN vendor_id SET NOT NULL')
    conn.execute(f'ALTER TABLE gear_size ADD CONSTRAINT fk_gear_size_vendor FOREIGN KEY (vendor_id) REFERENCES vendor(id)')
    print("Added vendor_id to gear_size")

    # 4. Add vendor_id to power_rating
    conn.execute('ALTER TABLE power_rating ADD COLUMN IF NOT EXISTS vendor_id INTEGER')
    conn.execute(f'''
        UPDATE power_rating pr
        SET vendor_id = gs.vendor_id
        FROM gear_size gs
        WHERE pr.gear_size_id = gs.id AND pr.vendor_id IS NULL
    ''')
    conn.execute(f'ALTER TABLE power_rating ALTER COLUMN vendor_id SET NOT NULL')
    conn.execute(f'ALTER TABLE power_rating ADD CONSTRAINT fk_power_rating_vendor FOREIGN KEY (vendor_id) REFERENCES vendor(id)')
    print("Added vendor_id to power_rating")

    # 5. Add vendor_id to thermal_capacity
    conn.execute('ALTER TABLE thermal_capacity ADD COLUMN IF NOT EXISTS vendor_id INTEGER')
    conn.execute(f'''
        UPDATE thermal_capacity tc
        SET vendor_id = gs.vendor_id
        FROM gear_size gs
        WHERE tc.gear_size_id = gs.id AND tc.vendor_id IS NULL
    ''')
    conn.execute(f'ALTER TABLE thermal_capacity ALTER COLUMN vendor_id SET NOT NULL')
    conn.execute(f'ALTER TABLE thermal_capacity ADD CONSTRAINT fk_thermal_capacity_vendor FOREIGN KEY (vendor_id) REFERENCES vendor(id)')
    print("Added vendor_id to thermal_capacity")

    # 6. Create supplementary_model table if not exists, then add vendor_id
    conn.execute('''
        CREATE TABLE IF NOT EXISTS supplementary_model (
            id SERIAL PRIMARY KEY,
            vendor_id INTEGER NOT NULL,
            model_code TEXT NOT NULL,
            series TEXT,
            size TEXT,
            cooling_type TEXT,
            forced_lube BOOLEAN DEFAULT FALSE,
            special_suffix TEXT,
            source TEXT DEFAULT 'excel_price_list',
            notes TEXT,
            created_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(vendor_id, model_code)
        )
    ''')
    conn.execute(f'ALTER TABLE supplementary_model ADD CONSTRAINT fk_supplementary_model_vendor FOREIGN KEY (vendor_id) REFERENCES vendor(id)')
    print("Created/updated supplementary_model with vendor_id")

    # 7. Add vendor_id to ambient_factor
    conn.execute('ALTER TABLE ambient_factor ADD COLUMN IF NOT EXISTS vendor_id INTEGER')
    conn.execute(f'UPDATE ambient_factor SET vendor_id = {elecon_id} WHERE vendor_id IS NULL')
    conn.execute(f'ALTER TABLE ambient_factor ALTER COLUMN vendor_id SET NOT NULL')
    conn.execute(f'ALTER TABLE ambient_factor ADD CONSTRAINT fk_ambient_factor_vendor FOREIGN KEY (vendor_id) REFERENCES vendor(id)')
    print("Added vendor_id to ambient_factor")

    # 8. Add vendor_id to catalog_page
    conn.execute('ALTER TABLE catalog_page ADD COLUMN IF NOT EXISTS vendor_id INTEGER')
    conn.execute(f'UPDATE catalog_page SET vendor_id = {elecon_id} WHERE vendor_id IS NULL')
    conn.execute(f'ALTER TABLE catalog_page ALTER COLUMN vendor_id SET NOT NULL')
    conn.execute(f'ALTER TABLE catalog_page ADD CONSTRAINT fk_catalog_page_vendor FOREIGN KEY (vendor_id) REFERENCES vendor(id)')
    print("Added vendor_id to catalog_page")

    # 9. Add vendor_id to import_log
    conn.execute('ALTER TABLE import_log ADD COLUMN IF NOT EXISTS vendor_id INTEGER')
    conn.execute(f'UPDATE import_log SET vendor_id = {elecon_id} WHERE vendor_id IS NULL')
    conn.execute(f'ALTER TABLE import_log ADD CONSTRAINT fk_import_log_vendor FOREIGN KEY (vendor_id) REFERENCES vendor(id)')
    print("Added vendor_id to import_log")

    # 10. Add vendor_id to extraction_audit
    conn.execute('ALTER TABLE extraction_audit ADD COLUMN IF NOT EXISTS vendor_id INTEGER')
    conn.execute(f'UPDATE extraction_audit SET vendor_id = {elecon_id} WHERE vendor_id IS NULL')
    conn.execute(f'ALTER TABLE extraction_audit ADD CONSTRAINT fk_extraction_audit_vendor FOREIGN KEY (vendor_id) REFERENCES vendor(id)')
    print("Added vendor_id to extraction_audit")

    # 11. Add vendor_id to altitude_factor, duty_factor, service_factor, application
    for tbl in ['altitude_factor', 'duty_factor', 'service_factor', 'application']:
        conn.execute(f'ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS vendor_id INTEGER')
        conn.execute(f'UPDATE {tbl} SET vendor_id = {elecon_id} WHERE vendor_id IS NULL')
        conn.execute(f'ALTER TABLE {tbl} ADD CONSTRAINT fk_{tbl}_vendor FOREIGN KEY (vendor_id) REFERENCES vendor(id)')
        print(f"Added vendor_id to {tbl}")

    # 12. Add vendor_id to dimension
    conn.execute('ALTER TABLE dimension ADD COLUMN IF NOT EXISTS vendor_id INTEGER')
    conn.execute(f'''
        UPDATE dimension d
        SET vendor_id = gs.vendor_id
        FROM gear_size gs
        WHERE d.gear_size_id = gs.id AND d.vendor_id IS NULL
    ''')
    conn.execute(f'ALTER TABLE dimension ADD CONSTRAINT fk_dimension_vendor FOREIGN KEY (vendor_id) REFERENCES vendor(id)')
    print("Added vendor_id to dimension")

    # 13. Add vendor_id to actual_ratio
    conn.execute('ALTER TABLE actual_ratio ADD COLUMN IF NOT EXISTS vendor_id INTEGER')
    conn.execute(f'''
        UPDATE actual_ratio ar
        SET vendor_id = gs.vendor_id
        FROM gear_size gs
        WHERE ar.gear_size_id = gs.id AND ar.vendor_id IS NULL
    ''')
    conn.execute(f'ALTER TABLE actual_ratio ADD CONSTRAINT fk_actual_ratio_vendor FOREIGN KEY (vendor_id) REFERENCES vendor(id)')
    print("Added vendor_id to actual_ratio")

    # 14. Create indexes for vendor_id on main tables
    for tbl in ['gear_series', 'gear_size', 'power_rating', 'thermal_capacity', 'supplementary_model']:
        conn.execute(f'CREATE INDEX IF NOT EXISTS idx_{tbl}_vendor_id ON {tbl}(vendor_id)')
    print("Created vendor_id indexes")

    print("\nMigration complete!")

if __name__ == '__main__':
    migrate()