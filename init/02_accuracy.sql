--============================================================
-- gearbox-selector — accuracy-layer seed data (02)
--
--   * ambient / duty / application anchor factors for the Elecon catalogue
--   * catalog_page mapping for the dual-series power sheets
--
-- The TABLES themselves (ambient_factor, altitude_factor, application,
-- duty_factor, extraction_audit, and the vendor-scoped unique keys) are
-- declared in 01_schema.sql. They used to be created here, but 01 has
-- since grown vendor_id onto every factor table while this file still
-- declared them globally unique -- so on a fresh database the CREATE
-- below either duplicated the table or aborted on the constraint.
--
-- Historical note: these statements also served as the migration for
-- pre-vendor databases. scripts/migrate_phase0.py supersedes that and
-- is the supported path for existing installs.
--
-- Idempotent: safe to re-run.
--============================================================

-- Resolve the Elecon vendor id from the seed in 00_vendor.sql rather than
-- hard-coding an id, since the SERIAL value depends on insert history.
DO $$
DECLARE
    v_elecon INT;
BEGIN
    SELECT id INTO v_elecon FROM vendor WHERE code = 'elecon';
    IF v_elecon IS NULL THEN
        RAISE EXCEPTION 'vendor seed missing: run 00_vendor.sql first';
    END IF;

    -- ambient derating anchors: worked-example values (fan 0.80, none 0.75 at 40C)
    INSERT INTO ambient_factor (vendor_id, cooling_type, amb_temp_c, fw) VALUES
        (v_elecon, 'none', 20, 1.00),
        (v_elecon, 'none', 40, 0.75),
        (v_elecon, 'fan',  20, 1.00),
        (v_elecon, 'fan',  40, 0.80)
    ON CONFLICT (vendor_id, cooling_type, amb_temp_c) DO NOTHING;

    -- f1 application load factors
    INSERT INTO application (vendor_id, code, description, f1) VALUES
        (v_elecon, 'uniform',  'uniform load, steady duty',               1.00),
        (v_elecon, 'moderate', 'moderate shock, occasional overload',     1.25),
        (v_elecon, 'heavy',    'heavy shock (e.g. rubber-belt conveyor)', 1.50)
    ON CONFLICT (vendor_id, code) DO NOTHING;

    -- service_factor mirror of the same three classes
    INSERT INTO service_factor (vendor_id, load_class, description, f1) VALUES
        (v_elecon, 'uniform',  'uniform load, steady duty',               1.00),
        (v_elecon, 'moderate', 'moderate shock, occasional overload',     1.25),
        (v_elecon, 'heavy',    'heavy shock (e.g. rubber-belt conveyor)', 1.50)
    ON CONFLICT (vendor_id, load_class) DO NOTHING;

    -- f2 daily operating-hours factor
    INSERT INTO duty_factor (vendor_id, hours_per_day, f2) VALUES
        (v_elecon, 8,  1.00),
        (v_elecon, 16, 1.25),
        (v_elecon, 24, 1.50)
    ON CONFLICT (vendor_id, hours_per_day) DO NOTHING;

    -- power sheets: pages 8..15, where 10..15 each carry TWO series codes
    INSERT INTO catalog_page (vendor_id, page_number, section, series_code)
    SELECT v_elecon, p, 'power', s
    FROM (VALUES
        (8,  'S1'), (9,  'S1'),
        (10, 'S2'), (11, 'S2'), (10, 'S3'), (11, 'S3'),
        (12, 'S4'), (13, 'S4'), (12, 'K2'), (13, 'K2'),
        (14, 'K3'), (15, 'K3'), (14, 'K4'), (15, 'K4')
    ) AS v(p, s)
    ON CONFLICT (page_number, section, series_code) DO NOTHING;
END $$;