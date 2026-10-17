--============================================================
-- gearbox-selector — price-list migration (04)
--   * raw quotation log ("Gearbox Price list (1).xlsx")
--   * aggregated per-model catalogue pricing for the chat results
-- Idempotent: safe to re-run.
--============================================================

-- raw quotation log rows (one per quotation / position)
CREATE TABLE IF NOT EXISTS price_quote (
    id               SERIAL PRIMARY KEY,
    sn               INT,
    project          TEXT,
    billing_code     TEXT,
    kw               NUMERIC,
    rpm              NUMERIC,
    gr               TEXT,
    gear_type        TEXT,
    hb               TEXT,
    cooling          TEXT,
    lubrication      TEXT,
    sf               NUMERIC,
    model_code       TEXT NOT NULL,
    weight_kg        NUMERIC,                 -- optional
    gearbox_price    NUMERIC,                 -- unit price (INR)
    source_file      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_price_quote_model ON price_quote (model_code);

-- aggregated model price card (latest/most-recent quote value)
CREATE TABLE IF NOT EXISTS model_price (
    model_code     TEXT PRIMARY KEY,
    unit_price_inr NUMERIC NOT NULL,
    n_quotes       INT NOT NULL DEFAULT 1,
    last_date      TIMESTAMPTZ
);