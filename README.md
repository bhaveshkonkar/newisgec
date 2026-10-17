# gearbox-selector

Elecon EON-Series geared motor / gearbox selection tool.

Stack: PostgreSQL 16 (Docker, port **5433**) + Python (FastAPI) selection engine
+ optional Groq LLM reasoning layer.

## Postgres

```bash
docker compose up -d
docker compose ps              # gearbox-db healthy
docker compose exec db psql -U gearbox -d gearbox -c "\dt"
```

- Host port **5433** (avoid clash with other local Postgres on 5432).
- Schema auto-applied on first init from `init/01_schema.sql` into DB `gearbox`.
- Data volume: `gearbox-db`.

## Layout

```
init/01_schema.sql   # full normalized schema (tables, indexes, view)
app/                 # FastAPI selection engine (Phase 4-5)
parsers/             # pdfplumber table parsers (Phase 3)
scripts/             # import + verify scripts (Phase 3)
data/catalog/        # source catalog + extracted CSVs
```

## Planned flow

1. Parse catalog tables (power rating, thermal, actual ratio, dimensions) into the DB.
2. Deterministic selection: `required_PN = Pe * f1 * f2` -> nearest `>=` lookup
   -> starting-torque / thermal validation -> step up size on failure.
3. Groq LLM: natural-language param extraction (function calling) + explanation
   of results. Numbers always come from the DB, never from the LLM.

Requires `GROQ_API_KEY` in `.env` for the LLM layer.