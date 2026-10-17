--============================================================
-- 00_vendor.sql — vendor table (was missing from init/, lived only in
--   scripts/migrate_add_vendor.py, so a fresh DB had vendor_id FKs
--   pointing at nothing and the engine crashed on a clean install).
--
-- Runs FIRST (alphabetical, before 01_schema.sql) because the gear
-- tables reference vendor(id).
--============================================================

CREATE TABLE IF NOT EXISTS vendor (
    id          SERIAL PRIMARY KEY,
    code        TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    description TEXT,
    is_active   BOOLEAN DEFAULT true,
    created_at  TIMESTAMP DEFAULT now()
);

-- Ids are pinned, not left to SERIAL. Every catalogue table references
-- vendor_id, and init/06_catalogue_seed.sql replays rows carrying the ids
-- they have in the live database. If these two vendors were free to land on
-- whatever the sequence hands out, a fresh build would put 'premium' on a
-- different id than the seed expects and the FK would reject the whole
-- catalogue. Keep these ids in step with init/06_catalogue_seed.sql.
INSERT INTO vendor (id, code, name, description) VALUES
    (1, 'elecon',  'Elecon',                    'Elecon EON-Series'),
    (3, 'premium', 'Premium Helical Gearboxes', 'Premium helical catalogue')
ON CONFLICT (code) DO NOTHING;

-- keep the sequence ahead of the pinned ids so a later insert without an
-- explicit id cannot collide with them
SELECT setval('vendor_id_seq',
              GREATEST((SELECT COALESCE(MAX(id), 0) FROM vendor), 1));

--============================================================
-- Series codes are only unique WITHIN a vendor. Two vendors may both
-- publish an 'S1' series, so the old global UNIQUE(series_code) has to
-- go. Applied to existing databases by scripts/migrate_phase0.py.
--============================================================
DO $$
BEGIN
    -- to_regclass() returns NULL instead of raising when the table is absent.
    -- On a genuinely fresh database gear_series does not exist yet (01_schema.sql
    -- has not run), so comparing against a bare 'gear_series'::regclass cast
    -- here would abort the whole init.
    IF to_regclass('gear_series') IS NOT NULL
       AND EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conrelid = to_regclass('gear_series')
                     AND conname = 'gear_series_series_code_key') THEN
        -- only safe to relax if no cross-vendor duplicates exist right now
        IF NOT EXISTS (SELECT 1 FROM gear_series
                       GROUP BY series_code HAVING count(*) > 1) THEN
            ALTER TABLE gear_series DROP CONSTRAINT gear_series_series_code_key;
        END IF;
    END IF;
END $$;

DO $$
BEGIN
    IF to_regclass('gear_series') IS NOT NULL
       AND NOT EXISTS (
           SELECT 1 FROM pg_constraint
           WHERE conrelid = to_regclass('gear_series')
             AND conname = 'gear_series_vendor_series_code_key') THEN
        ALTER TABLE gear_series
            ADD CONSTRAINT gear_series_vendor_series_code_key
            UNIQUE (vendor_id, series_code);
    END IF;
END $$;