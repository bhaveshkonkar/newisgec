--============================================================
-- gearbox-selector schema — Elecon EON-Series gearbox selection
--   S1..S4 helical, K2..K4 bevel-helical
-- Applied automatically on first Postgres init via
-- /docker-entrypoint-initdb.d (alphabetical order).
--============================================================

-- reference: series families in the catalog
CREATE TABLE IF NOT EXISTS gear_series (
    id            SERIAL PRIMARY KEY,
    series_code   TEXT NOT NULL,                   -- 'S1','S2','K3',...
    gear_type     TEXT NOT NULL CHECK (gear_type IN ('helical','bevel_helical')),
    description   TEXT,
    vendor_id     INT NOT NULL REFERENCES vendor(id),
    -- only unique WITHIN a vendor: two vendors may both publish 'S1'.
    -- Named explicitly because scripts/migrate_phase0.py looks this up by
    -- name; an inline UNIQUE would auto-generate a different name and the
    -- migration would then add a redundant second constraint.
    CONSTRAINT gear_series_vendor_series_code_key UNIQUE (vendor_id, series_code)
);

CREATE TABLE IF NOT EXISTS gear_size (
    id         SERIAL PRIMARY KEY,
    series_id  INT NOT NULL REFERENCES gear_series(id) ON DELETE CASCADE,
    size       TEXT NOT NULL,                      -- '11','13','15','26',...
    vendor_id  INT NOT NULL REFERENCES vendor(id),
    UNIQUE (series_id, size)
);

-- nominal ratio iN -> actual ratio, per gearbox size
CREATE TABLE IF NOT EXISTS actual_ratio (
    id            SERIAL PRIMARY KEY,
    gear_size_id  INT NOT NULL REFERENCES gear_size(id) ON DELETE CASCADE,
    ratio_in      TEXT NOT NULL,                   -- nominal class as printed
    actual_ratio  NUMERIC NOT NULL,
    source_page   INT NOT NULL,
    vendor_id     INT REFERENCES vendor(id),
    UNIQUE (gear_size_id, ratio_in)
);

-- the fat lookup table: nearest-greater-than-or-equal selection
CREATE TABLE IF NOT EXISTS power_rating (
    id                   SERIAL PRIMARY KEY,
    gear_size_id         INT NOT NULL REFERENCES gear_size(id) ON DELETE CASCADE,
    ratio_in             TEXT NOT NULL,
    n1_rpm               INT  NOT NULL CHECK (n1_rpm > 0),   -- 1500 / 1200 / 1000 / 750
    n2_rpm               NUMERIC NOT NULL,                   -- output speed
    power_kw             NUMERIC NOT NULL CHECK (power_kw >= 0),
    requires_forced_lube BOOLEAN NOT NULL DEFAULT FALSE,     -- '*' flag in catalog
    source_page          INT NOT NULL,
    vendor_id            INT NOT NULL REFERENCES vendor(id),
    UNIQUE (gear_size_id, ratio_in, n1_rpm, n2_rpm)
);

CREATE TABLE IF NOT EXISTS thermal_capacity (
    id            SERIAL PRIMARY KEY,
    gear_size_id  INT NOT NULL REFERENCES gear_size(id) ON DELETE CASCADE,
    ratio_in      TEXT NOT NULL,                   -- 'a..b' band or single ratio
    amb_temp_c    INT  NOT NULL DEFAULT 40,        -- ambient temp the table is for
    ed_pct        NUMERIC NOT NULL DEFAULT 100,    -- running duration %
    power_kw      NUMERIC NOT NULL,
    source_page   INT NOT NULL,
    cooling_type  TEXT NOT NULL DEFAULT 'none'
                  CONSTRAINT ck_cooling_type
                  CHECK (cooling_type IN ('none','fan','coil','fan_coil')),
    n1_rpm        INT  NOT NULL DEFAULT 1500
                  CONSTRAINT ck_thermal_n1 CHECK (n1_rpm IN (1500, 1200, 1000, 750)),
    vendor_id     INT NOT NULL REFERENCES vendor(id),
    -- rated thermal power differs per input speed, so n1_rpm is part of the key
    CONSTRAINT thermal_capacity_unique
        UNIQUE (gear_size_id, ratio_in, cooling_type, n1_rpm, amb_temp_c, ed_pct)
);

--============================================================
-- Selection support tables.
--
-- All four factor tables are keyed WITHIN a vendor. Two vendors publish
-- their own derating curves, so a global UNIQUE(cooling_type, amb_temp_c)
-- would silently drop every second vendor's data. vendor_id is nullable
-- so a pre-vendor row can still be backfilled by the migration.
--============================================================

-- f1: application / shock load class
CREATE TABLE IF NOT EXISTS service_factor (
    id           SERIAL PRIMARY KEY,
    load_class   TEXT NOT NULL,                     -- 'uniform','moderate','heavy'
    description  TEXT,
    f1           NUMERIC NOT NULL CHECK (f1 >= 1),
    vendor_id    INT REFERENCES vendor(id),
    CONSTRAINT service_factor_vendor_key UNIQUE (vendor_id, load_class)
);

-- ambient-temperature derating of rated (=20C) thermal capacity.
-- Seeded with the worked-example anchors; canonical curves live in the
-- catalogue tables which are absent from the source PDF.
CREATE TABLE IF NOT EXISTS ambient_factor (
    id           SERIAL PRIMARY KEY,
    cooling_type TEXT NOT NULL CHECK (cooling_type IN ('none','fan','coil','fan_coil')),
    amb_temp_c   NUMERIC NOT NULL,
    fw           NUMERIC NOT NULL CHECK (fw > 0),
    vendor_id    INT NOT NULL CONSTRAINT fk_ambient_factor_vendor REFERENCES vendor(id),
    CONSTRAINT ambient_factor_vendor_key UNIQUE (vendor_id, cooling_type, amb_temp_c)
);

-- altitude derating (populated from the selection manual when sourced)
CREATE TABLE IF NOT EXISTS altitude_factor (
    id           SERIAL PRIMARY KEY,
    altitude_m   NUMERIC NOT NULL,
    fa           NUMERIC NOT NULL CHECK (fa > 0),
    vendor_id    INT REFERENCES vendor(id),
    CONSTRAINT altitude_factor_vendor_key UNIQUE (vendor_id, altitude_m)
);

-- f1 factor table used by the selector (supersedes service_factor naming)
CREATE TABLE IF NOT EXISTS application (
    id           SERIAL PRIMARY KEY,
    code         TEXT NOT NULL,                     -- 'uniform','moderate','heavy'
    description  TEXT,
    f1           NUMERIC NOT NULL CHECK (f1 >= 1),
    vendor_id    INT REFERENCES vendor(id),
    CONSTRAINT application_vendor_key UNIQUE (vendor_id, code)
);

-- f2: added factor for daily operating hours
CREATE TABLE IF NOT EXISTS duty_factor (
    id               SERIAL PRIMARY KEY,
    hours_per_day    INT NOT NULL,                  -- 8 / 16 / 24
    f2               NUMERIC NOT NULL,
    vendor_id        INT REFERENCES vendor(id),
    CONSTRAINT duty_factor_vendor_key UNIQUE (vendor_id, hours_per_day)
);

-- EAV-style so variable dimension columns per series stay flexible
CREATE TABLE IF NOT EXISTS dimension (
    id              SERIAL PRIMARY KEY,
    gear_size_id    INT NOT NULL REFERENCES gear_size(id) ON DELETE CASCADE,
    dim_name        TEXT NOT NULL,                 -- 'a','aw','net_weight_kg',...
    value_mm        NUMERIC,
    weight_kg       NUMERIC,
    source_page     INT NOT NULL,
    vendor_id       INT REFERENCES vendor(id)
);

-- Which mounting arrangements a series is actually offered in.
--
-- This is multi-valued on purpose: K3, for example, is published both on a
-- foot base and with a torque arm. A column on gear_series could only hold
-- one of the two and would be wrong for half the catalogue.
--
-- Source of truth is the catalogue itself, where the two variants are
-- distinguished by carrying separate net-weight figures under
-- dimension.dim_name = 'net_weight_kg' and 'net_weight_kg_torque_arm'.
-- Backfilled from that, see init/03_thermal_speed.sql.
--
-- A series absent from this table has UNKNOWN mounting, not "no mounting".
-- The engine must treat that as unverifiable and say so rather than
-- silently dropping the series from results.
CREATE TABLE IF NOT EXISTS series_mounting (
    series_id      INT NOT NULL REFERENCES gear_series(id) ON DELETE CASCADE,
    mounting_type  TEXT NOT NULL,
    PRIMARY KEY (series_id, mounting_type),
    CONSTRAINT series_mounting_type_check
        CHECK (mounting_type IN ('foot', 'torque_arm'))
);

-- models that exist only in the price list, with no catalogue rating row
CREATE TABLE IF NOT EXISTS supplementary_model (
    id             SERIAL PRIMARY KEY,
    vendor_id      INT NOT NULL REFERENCES vendor(id),
    model_code     TEXT NOT NULL,
    series         TEXT,
    size           TEXT,
    cooling_type   TEXT,
    forced_lube    BOOLEAN NOT NULL DEFAULT FALSE,
    special_suffix TEXT,
    source         TEXT DEFAULT 'excel_price_list',
    notes          TEXT,
    created_at     TIMESTAMP DEFAULT NOW(),
    UNIQUE (vendor_id, model_code)
);

--============================================================
-- Extraction bookkeeping / provenance.
--
-- catalog_page: pages 10..15 each carry TWO series codes, so
-- UNIQUE(page_number) silently discarded the second one. The key is
-- (page_number, section, series_code).
--============================================================
CREATE TABLE IF NOT EXISTS catalog_page (
    id             SERIAL PRIMARY KEY,
    page_number    INT NOT NULL,
    section        TEXT NOT NULL,                  -- 'power','thermal','ratio','dimension','info'
    series_code    TEXT,
    vendor_id      INT NOT NULL REFERENCES vendor(id),
    CONSTRAINT catalog_page_unique UNIQUE (page_number, section, series_code)
);

CREATE TABLE IF NOT EXISTS extraction_audit (
    id           SERIAL PRIMARY KEY,
    series_code  TEXT NOT NULL,
    source_page  INT NOT NULL,
    section      TEXT NOT NULL,                    -- 'power','thermal'
    rows_seen    INT NOT NULL,
    rows_stored  INT NOT NULL,
    validated    BOOLEAN NOT NULL DEFAULT FALSE,
    notes        TEXT,
    vendor_id    INT REFERENCES vendor(id),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS import_log (
    id              SERIAL PRIMARY KEY,
    run_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    source_file     TEXT NOT NULL,
    rows_imported   INT NOT NULL,
    status          TEXT NOT NULL,
    vendor_id       INT REFERENCES vendor(id)
);

--============================================================
-- Indexes — the "nearest >= required_PN" query in one indexed seek
--============================================================
CREATE INDEX IF NOT EXISTS idx_power_select ON power_rating (gear_size_id, ratio_in, n1_rpm, power_kw DESC);
CREATE INDEX IF NOT EXISTS idx_power_lube   ON power_rating (gear_size_id, requires_forced_lube);
CREATE INDEX IF NOT EXISTS idx_thermal      ON thermal_capacity (gear_size_id, ratio_in, n1_rpm, amb_temp_c, ed_pct);
CREATE INDEX IF NOT EXISTS idx_dimension    ON dimension (gear_size_id);
CREATE INDEX IF NOT EXISTS idx_dimension_nm  ON dimension (dim_name) WHERE dim_name IS NOT NULL;

--============================================================
-- Engine convenience view
--============================================================
CREATE OR REPLACE VIEW v_power_rating AS
SELECT gs.series_code, gs.gear_type, sz.size, pr.ratio_in, pr.n1_rpm,
       pr.n2_rpm, pr.power_kw, pr.requires_forced_lube, pr.source_page
FROM power_rating pr
JOIN gear_size sz ON sz.id = pr.gear_size_id
JOIN gear_series gs ON gs.id = sz.series_id;