--============================================================
-- gearbox-selector — thermal-speed + catalog mapping fix (03)
--
-- This file used to ALTER thermal_capacity and catalog_page:
--
--   ALTER TABLE thermal_capacity ... UNIQUE (gear_size_id, ratio_iN, ...)
--   CREATE INDEX idx_thermal ON thermal_capacity (gear_size_id, ratio_iN, ...)
--
-- `ratio_iN` was renamed to `ratio_in` in 01_schema.sql, so on any fresh
-- database this file aborted with "column ratio_iN does not exist" and
-- took 04/05 down with it. The column, its CHECK and both keys are now
-- declared inline in 01_schema.sql, which is why this file only has to
-- backfill rows imported before the rename.
--
-- Idempotent: safe to re-run.
--============================================================

-- 1. per-speed thermal ratings.
--    n1_rpm is already NOT NULL in 01, but a database imported by an older
--    parser may hold NULLs, so repair rather than assume.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'thermal_capacity'
          AND column_name = 'n1_rpm'
    ) THEN
        -- thermal sheets are generated at 1500 rpm, so that is the backfill value
        UPDATE thermal_capacity SET n1_rpm = 1500 WHERE n1_rpm IS NULL;

        -- replace the historical constraint name if 01 only created the
        -- inline (auto-named) CHECK
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conrelid = to_regclass('thermal_capacity')
              AND conname = 'ck_thermal_n1'
        ) THEN
            ALTER TABLE thermal_capacity DROP CONSTRAINT IF EXISTS thermal_capacity_n1_rpm_check;
            ALTER TABLE thermal_capacity
                ADD CONSTRAINT ck_thermal_n1 CHECK (n1_rpm IN (1500, 1200, 1000, 750));
        END IF;
    END IF;
END $$;

-- 2. catalog_page: dual-series pages (10..15) hold two series codes per page.
--    UNIQUE(page_number) silently dropped the second one; 01 now declares
--    UNIQUE (page_number, section, series_code), so only the legacy
--    single-column constraint needs removing.
DO $$
BEGIN
    IF to_regclass('catalog_page') IS NOT NULL THEN
        ALTER TABLE catalog_page DROP CONSTRAINT IF EXISTS catalog_page_page_number_key;
    END IF;
END $$;

-- 3. series_mounting: backfill from the catalogue's own weight tables.
--
-- The importer records a torque-arm build of a size as a distinct
-- net-weight figure, so the set of dim_names present for a series is exactly
-- the set of mountings that series is offered in. Deriving the backfill from
-- dimension rather than hard-coding series codes means a re-import that adds
-- or removes a torque-arm table updates the mounting data with it.
--
-- 'foot' is the base/foot build, published under the plain net_weight_kg key,
-- so it is present for every series that carries weights at all.
DO $$
BEGIN
    IF to_regclass('series_mounting') IS NOT NULL THEN
        INSERT INTO series_mounting (series_id, mounting_type)
        SELECT DISTINCT gz.series_id, 'foot'
          FROM dimension d
          JOIN gear_size gz ON gz.id = d.gear_size_id
         WHERE d.dim_name = 'net_weight_kg'
        ON CONFLICT DO NOTHING;

        INSERT INTO series_mounting (series_id, mounting_type)
        SELECT DISTINCT gz.series_id, 'torque_arm'
          FROM dimension d
          JOIN gear_size gz ON gz.id = d.gear_size_id
         WHERE d.dim_name = 'net_weight_kg_torque_arm'
        ON CONFLICT DO NOTHING;
    END IF;
END $$;