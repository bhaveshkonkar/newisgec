--============================================================
-- 05_isgec.sql — ISGEC AI project workspace
--
-- Deliberately its own `isgec` schema. The existing `public` gear tables
-- are the deterministic selection engine's data and must not be touched
-- by the app's CRUD. Same database, hard boundary.
--
-- All six module types are created up front even though only `gearbox` is
-- functional, so adding Motor/Pump later is a feature, not a migration.
--
-- Idempotent: safe to re-run.
--============================================================

CREATE SCHEMA IF NOT EXISTS isgec;

--============================================================
-- profiles — the owner identity that created_by/org_id point at.
-- Phase 0 risk called out: a dangling created_by UUID would have forced
-- a migration at RLS time, so this exists from day one.
--============================================================
CREATE TABLE IF NOT EXISTS isgec.profiles (
    id          UUID PRIMARY KEY,               -- = auth.users.id once Supabase lands
    email       TEXT UNIQUE,
    full_name   TEXT NOT NULL,
    initials    TEXT,
    is_admin    BOOLEAN NOT NULL DEFAULT false,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

--============================================================
-- projects — the unit of isolation. Every other table in this schema
-- hangs off it with ON DELETE CASCADE, so deleting a project cannot
-- leave orphaned documents or chat history behind.
--============================================================
CREATE TABLE IF NOT EXISTS isgec.projects (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name         TEXT NOT NULL CHECK (length(btrim(name)) > 0),
    project_date DATE,
    description  TEXT,
    created_by   UUID NOT NULL REFERENCES isgec.profiles(id),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_projects_owner      ON isgec.projects (created_by);
-- "Recent" sort on the home page: newest activity first
CREATE INDEX IF NOT EXISTS idx_projects_owner_date ON isgec.projects (created_by, project_date DESC NULLS LAST, created_at DESC);

--============================================================
-- project_modules — one logical workspace per module per project.
-- UNIQUE(project_id, module_type) is what makes a module a singleton.
--============================================================
CREATE TABLE IF NOT EXISTS isgec.project_modules (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id  UUID NOT NULL REFERENCES isgec.projects(id) ON DELETE CASCADE,
    module_type TEXT NOT NULL CHECK (module_type IN (
                   'gearbox', 'motor', 'pump',
                   'mechanical_equipment', 'rfq_analysis', 'general_chat')),
    enabled     BOOLEAN NOT NULL DEFAULT false,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (project_id, module_type)
);

CREATE INDEX IF NOT EXISTS idx_modules_project ON isgec.project_modules (project_id);

--============================================================
-- documents — belong to a PROJECT, optionally scoped to one module.
-- project_id is the isolation boundary; module_id is an organisational
-- hint only and is never trusted on its own.
--============================================================
CREATE TABLE IF NOT EXISTS isgec.documents (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id     UUID NOT NULL REFERENCES isgec.projects(id) ON DELETE CASCADE,
    module_id      UUID REFERENCES isgec.project_modules(id) ON DELETE SET NULL,
    file_name      TEXT NOT NULL,
    storage_path   TEXT,                         -- relative key, resolved by lib/storage.ts
    file_size      BIGINT,
    mime_type      TEXT,
    status         TEXT NOT NULL DEFAULT 'uploaded'
                   CHECK (status IN ('uploaded','processing','parsed','failed')),
    extracted_text TEXT,
    metadata       JSONB,
    page_count     INT,
    parser_version TEXT,
    error_detail   TEXT,
    uploaded_by    UUID REFERENCES isgec.profiles(id),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_documents_project ON isgec.documents (project_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_documents_module  ON isgec.documents (module_id) WHERE module_id IS NOT NULL;
-- boot-time re-queue of jobs interrupted by a restart
CREATE INDEX IF NOT EXISTS idx_documents_pending ON isgec.documents (status) WHERE status = 'processing';

--============================================================
-- document_pages — one row per PDF page.
--
-- documents.extracted_text is a single blob, which is enough to ground an
-- answer but destroys the one thing needed to *show your work*: which page a
-- claim came from. A citation that says "Elecon G B_EON-Series.pdf" without a
-- page number is not checkable, and an engineer signing off a selection will
-- not accept it.
--
-- So page boundaries are stored rather than re-derived. Re-deriving them later
-- would mean re-running the extractor and hoping the two runs agree, and a
-- citation pointing at the wrong page is worse than no citation.
--
-- page_no is 1-based and matches what the reader sees in the PDF viewer, so
-- page 12 here is page 12 in the browser. It is deliberately NOT the
-- zero-based index any PDF library uses: every off-by-one in this feature
-- would point a user at the top of a document instead of the table they were
-- told to check.
--
-- Text that carries no real page boundary (docx, xlsx, csv) is stored as a
-- single page_no = 1 row rather than being faked into invented page numbers.
--============================================================
CREATE TABLE IF NOT EXISTS isgec.document_pages (
    document_id UUID NOT NULL REFERENCES isgec.documents(id) ON DELETE CASCADE,
    page_no     INT  NOT NULL CHECK (page_no >= 1),
    char_count  INT  NOT NULL DEFAULT 0,
    text        TEXT NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (document_id, page_no)
);

-- Retrieval reads every page of one document at a time; the PK leading column
-- already covers that, so this is for the "which documents still need pages"
-- repair check.
CREATE INDEX IF NOT EXISTS idx_pages_doc ON isgec.document_pages (document_id);

--============================================================
-- catalogue_page_index — which page of a vendor catalogue prints which section
-- for which series.
--
-- document_pages stores every page, but that is the raw material, not the
-- answer. A gearbox rating table extracts as bare integers under a heading, so
-- the model code a reader searched for is not a string the page contains at all
-- ("B3-315" never appears; the columns are "B3" and "315" in separate cells).
-- Ranking pages by term overlap therefore picks whichever table shares the most
-- common words, which produces confident citations to the wrong page.
--
-- So the catalogue's own printed headings are transcribed here. Attribution
-- then reads this table instead of guessing, and a question the catalogue does
-- not publish a page for gets no citation rather than a plausible one.
--
-- series is a catalogue type code (Elecon S1-S4/K2-K4, Premium H1-H4/B2-B4).
-- Pages the catalogue prints for every type (the generic selection procedure,
-- the all-series shaft table) are stored once per series rather than filed
-- under whichever type happened to be nearest, so a lookup for K3 still finds
-- them.
--
-- This table is populated by scripts/build_catalogue_index.py, not by the
-- extractor: it is a human transcription of a printed table of contents and
-- must be re-checked whenever a catalogue is reissued.
--============================================================
CREATE TABLE IF NOT EXISTS isgec.catalogue_page_index (
    document_id UUID NOT NULL REFERENCES isgec.documents(id) ON DELETE CASCADE,
    series      TEXT NOT NULL,
    subject     TEXT NOT NULL,
    page_no     INT  NOT NULL CHECK (page_no >= 1),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (document_id, series, subject, page_no)
);

-- Attribution resolves (document, series) then filters by subject, so the
-- document_id/series prefix does the work.
CREATE INDEX IF NOT EXISTS idx_catalogue_lookup
    ON isgec.catalogue_page_index (document_id, series);

--============================================================
-- chat_sessions — every conversation is (project, module) scoped.
--============================================================
CREATE TABLE IF NOT EXISTS isgec.chat_sessions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id  UUID NOT NULL REFERENCES isgec.projects(id) ON DELETE CASCADE,
    module_type TEXT NOT NULL CHECK (module_type IN (
                    'gearbox', 'motor', 'pump',
                    'mechanical_equipment', 'rfq_analysis', 'general_chat')),
    title       TEXT NOT NULL DEFAULT 'New conversation',
    created_by  UUID REFERENCES isgec.profiles(id),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sessions_scope ON isgec.chat_sessions (project_id, module_type, updated_at DESC);

--============================================================
-- chat_messages — a session id from the client is NEVER trusted: the
-- query must join back through chat_sessions and re-check project_id.
--============================================================
CREATE TABLE IF NOT EXISTS isgec.chat_messages (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES isgec.chat_sessions(id) ON DELETE CASCADE,
    role       TEXT NOT NULL CHECK (role IN ('user','assistant','system')),
    content    TEXT NOT NULL,
    metadata   JSONB,                            -- engine result, doc citations, tokens
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON isgec.chat_messages (session_id, created_at);

--============================================================
-- updated_at maintenance
--============================================================
CREATE OR REPLACE FUNCTION isgec.touch_updated_at() RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_projects_touch   ON isgec.projects;
CREATE TRIGGER trg_projects_touch BEFORE UPDATE ON isgec.projects
    FOR EACH ROW EXECUTE FUNCTION isgec.touch_updated_at();

DROP TRIGGER IF EXISTS trg_documents_touch   ON isgec.documents;
CREATE TRIGGER trg_documents_touch BEFORE UPDATE ON isgec.documents
    FOR EACH ROW EXECUTE FUNCTION isgec.touch_updated_at();

DROP TRIGGER IF EXISTS trg_sessions_touch    ON isgec.chat_sessions;
CREATE TRIGGER trg_sessions_touch BEFORE UPDATE ON isgec.chat_sessions
    FOR EACH ROW EXECUTE FUNCTION isgec.touch_updated_at();

DROP TRIGGER IF EXISTS trg_profiles_touch    ON isgec.profiles;
CREATE TRIGGER trg_profiles_touch BEFORE UPDATE ON isgec.profiles
    FOR EACH ROW EXECUTE FUNCTION isgec.touch_updated_at();

--============================================================
-- helper: every module type a project should start with
--============================================================
CREATE OR REPLACE FUNCTION isgec.default_module_types() RETURNS TEXT[] AS $$
    SELECT ARRAY['gearbox','motor','pump',
                 'mechanical_equipment','rfq_analysis','general_chat'];
$$ LANGUAGE sql IMMUTABLE;

--============================================================
-- Development identity.
--
-- DEV_USER_ID in .env.local points at this row, so without it a fresh
-- install boots to a shell whose every API route fails closed on
-- getCurrentUser(). Phase 14 replaces this with Supabase Auth and the
-- row becomes irrelevant -- keep the id, it is referenced by the env
-- file and by any projects already created against it.
--============================================================
INSERT INTO isgec.profiles (id, email, full_name, is_admin)
VALUES ('00000000-0000-4000-8000-000000000001',
        'bhavesh.konkar@adani.com', 'Bhavesh Konkar', TRUE)
ON CONFLICT (id) DO NOTHING;