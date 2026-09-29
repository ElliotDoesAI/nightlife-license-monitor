-- Idempotent schema. Applied at the start of every run.

CREATE TABLE IF NOT EXISTS runs (
    id            BIGSERIAL PRIMARY KEY,
    started_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at   TIMESTAMPTZ,
    trigger       TEXT NOT NULL DEFAULT 'manual',   -- schedule | manual | test
    status        TEXT NOT NULL DEFAULT 'running',  -- running | success | partial | failed
    git_sha       TEXT
);

CREATE TABLE IF NOT EXISTS raw_snapshots (
    id            BIGSERIAL PRIMARY KEY,
    source        TEXT NOT NULL,
    url           TEXT NOT NULL,
    fetched_at    TIMESTAMPTZ NOT NULL,       -- first time these exact bytes were fetched
    last_fetched_at TIMESTAMPTZ NOT NULL,     -- most recent fetch of the same bytes
    content_type  TEXT,
    sha256        TEXT NOT NULL,
    byte_size     BIGINT NOT NULL,
    body_gz       BYTEA,           -- NULL once pruned by retention
    pruned_at     TIMESTAMPTZ,
    UNIQUE (source, sha256)
);

CREATE TABLE IF NOT EXISTS source_runs (
    id              BIGSERIAL PRIMARY KEY,
    run_id          BIGINT NOT NULL REFERENCES runs(id),
    source          TEXT NOT NULL,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ,
    status          TEXT NOT NULL DEFAULT 'running',  -- running | success | failed
    is_baseline     BOOLEAN NOT NULL DEFAULT false,
    snapshot_ids    BIGINT[] NOT NULL DEFAULT '{}',
    records_fetched INTEGER,
    records_new     INTEGER,
    records_changed INTEGER,
    records_removed INTEGER,
    records_qualified_queued INTEGER,
    error_type      TEXT,
    error_detail    TEXT          -- full traceback; private DB only, never logged
);
CREATE INDEX IF NOT EXISTS source_runs_source_idx ON source_runs (source, started_at DESC);

CREATE TABLE IF NOT EXISTS records (
    id                  BIGSERIAL PRIMARY KEY,
    source              TEXT NOT NULL,
    source_record_id    TEXT NOT NULL,
    source_url          TEXT NOT NULL,
    legal_name          TEXT,
    dba                 TEXT,
    license_type        TEXT,
    license_description TEXT,
    application_type    TEXT,
    status              TEXT,
    application_date    DATE,
    address             TEXT,
    city                TEXT,
    state               TEXT,
    zip                 TEXT,
    county              TEXT,
    metro               TEXT,
    venue_key           TEXT NOT NULL,     -- groups applications for one premises
    category            TEXT NOT NULL,
    material_hash       TEXT NOT NULL,
    raw                 JSONB NOT NULL,
    first_seen_at       TIMESTAMPTZ NOT NULL,
    last_seen_at        TIMESTAMPTZ NOT NULL,
    last_changed_at     TIMESTAMPTZ NOT NULL,
    removed_at          TIMESTAMPTZ,       -- left an official pending list
    first_snapshot_id   BIGINT REFERENCES raw_snapshots(id),
    last_snapshot_id    BIGINT REFERENCES raw_snapshots(id),
    qualified           BOOLEAN NOT NULL DEFAULT false,
    score               INTEGER NOT NULL DEFAULT 0,
    tier                TEXT,
    qualify_reason      TEXT,
    review_status       TEXT NOT NULL DEFAULT 'new',  -- new | approved | rejected | contacted | snoozed
    review_notes        TEXT,
    reviewed_at         TIMESTAMPTZ,
    UNIQUE (source, source_record_id)
);
CREATE INDEX IF NOT EXISTS records_queue_idx ON records (qualified, review_status, metro);
CREATE INDEX IF NOT EXISTS records_venue_idx ON records (venue_key);

CREATE TABLE IF NOT EXISTS record_events (
    id              BIGSERIAL PRIMARY KEY,
    record_id       BIGINT NOT NULL REFERENCES records(id),
    source_run_id   BIGINT NOT NULL REFERENCES source_runs(id),
    event_type      TEXT NOT NULL,   -- new | changed | removed | baseline
    observed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    changes         JSONB,           -- {field: [old, new]} for 'changed'
    queued          BOOLEAN NOT NULL DEFAULT false  -- included in the daily review queue
);
CREATE INDEX IF NOT EXISTS record_events_day_idx ON record_events (observed_at);
CREATE INDEX IF NOT EXISTS record_events_record_idx ON record_events (record_id);

-- Daily review queue: qualified records that were new or materially changed.
CREATE OR REPLACE VIEW review_queue AS
SELECT
    (e.observed_at AT TIME ZONE 'UTC')::date AS queue_date,
    e.event_type,
    e.changes,
    r.id AS record_id,
    r.tier,
    r.score,
    r.legal_name,
    r.dba,
    r.source_record_id,
    r.license_type,
    r.license_description,
    r.application_type,
    r.status,
    r.application_date,
    r.address,
    r.city,
    r.state,
    r.zip,
    r.county,
    r.metro,
    r.venue_key,
    r.source,
    r.source_url,
    r.first_seen_at,
    r.qualify_reason,
    r.review_status,
    r.review_notes
FROM record_events e
JOIN records r ON r.id = e.record_id
WHERE e.queued;

-- One row per premises per day: several applications for the same venue
-- (e.g. TX mixed-beverage + food-and-beverage + late-hours) become one lead.
CREATE OR REPLACE VIEW daily_leads AS
SELECT
    queue_date,
    min(tier) AS tier,
    max(score) AS score,
    (array_agg(legal_name ORDER BY score DESC, record_id))[1] AS legal_name,
    (array_agg(dba ORDER BY score DESC, record_id))[1] AS dba,
    string_agg(DISTINCT event_type, ', ') AS event_types,
    string_agg(DISTINCT source_record_id, ', ') AS source_record_ids,
    string_agg(DISTINCT license_type, ', ') AS license_types,
    string_agg(DISTINCT license_description, '; ') AS license_descriptions,
    string_agg(DISTINCT application_type, ', ') AS application_types,
    string_agg(DISTINCT status, ', ') AS statuses,
    min(application_date) AS application_date,
    (array_agg(address ORDER BY score DESC, record_id))[1] AS address,
    (array_agg(city ORDER BY score DESC, record_id))[1] AS city,
    (array_agg(state ORDER BY score DESC, record_id))[1] AS state,
    (array_agg(zip ORDER BY score DESC, record_id))[1] AS zip,
    (array_agg(county ORDER BY score DESC, record_id))[1] AS county,
    (array_agg(metro ORDER BY score DESC, record_id))[1] AS metro,
    string_agg(DISTINCT source, ', ') AS source,
    (array_agg(source_url ORDER BY score DESC, record_id))[1] AS source_url,
    min(first_seen_at) AS first_seen_at,
    (array_agg(qualify_reason ORDER BY score DESC, record_id))[1] AS qualify_reason,
    CASE WHEN count(DISTINCT review_status) = 1 THEN min(review_status)
         ELSE 'mixed' END AS review_status,
    string_agg(DISTINCT review_notes, ' | ') AS review_notes,
    string_agg(DISTINCT record_id::text, ' ') AS record_ids,
    venue_key
FROM review_queue
GROUP BY queue_date, venue_key;
