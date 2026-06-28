-- WoundBill Triage — Supabase Postgres schema
--
-- Runnable as-is in the Supabase SQL editor. Idempotent: uses
-- "create table if not exists" so re-running is safe.
--
-- Raw tables mirror the PCC API (PRD §7). The two patient identifiers are kept
-- distinct (CLAUDE.md hard rule 1):
--   - patients.patient_id (text, e.g. "FA-001")  -> diagnoses, coverage
--   - patients.id          (bigint, e.g. 1)       -> notes, assessments
--
-- assessments.raw_json is stored as jsonb, raw payload as-is. It is the nested
-- sections -> questions -> {question, answer} shape with wound data as free text
-- inside the answer; it is NOT flattened at ingestion.

-- ----------------------------------------------------------------------------
-- Raw tables
-- ----------------------------------------------------------------------------

create table if not exists patients (
    id                  bigint primary key,        -- internal id (notes/assessments key)
    facility_id         integer,
    patient_id          text unique,               -- PCC id (diagnoses/coverage key); unique so FKs can reference it
    first_name          text,
    last_name           text,
    birth_date          date,
    gender              text,
    primary_payer_code  text,
    last_modified_at    timestamptz,
    is_new_admission    boolean
);

create index if not exists patients_patient_id_idx on patients (patient_id);
create index if not exists patients_facility_id_idx on patients (facility_id);

create table if not exists diagnoses (
    id                  bigint primary key,
    patient_id          text references patients (patient_id),
    icd10_code          text,
    icd10_description   text,
    clinical_status     text,
    onset_date          date,
    last_modified_at    timestamptz
);

create index if not exists diagnoses_patient_id_idx on diagnoses (patient_id);

create table if not exists coverage (
    id                  bigint primary key,
    patient_id          text references patients (patient_id),
    payer_name          text,
    payer_code          text,
    payer_type          text,
    effective_from      timestamptz,
    effective_to        timestamptz,               -- null = currently active
    last_modified_at    timestamptz
);

create index if not exists coverage_patient_id_idx on coverage (patient_id);

create table if not exists notes (
    id                  bigint primary key,
    patient_id          bigint references patients (id),   -- integer internal id
    note_type           text,
    effective_date      timestamptz,
    note_text           text,
    created_by          text
);

create index if not exists notes_patient_id_idx on notes (patient_id);

create table if not exists assessments (
    id                  bigint primary key,
    patient_id          bigint references patients (id),   -- integer internal id
    assessment_type     text,
    status              text,
    assessment_date     date,
    raw_json            jsonb                       -- nested sections/questions, as-is
);

create index if not exists assessments_patient_id_idx on assessments (patient_id);

-- ----------------------------------------------------------------------------
-- Output table (read by the frontend; populated in the decide phase)
-- ----------------------------------------------------------------------------

create table if not exists eligibility_results (
    patient_internal_id   bigint primary key,       -- = patients.id
    patient_id            text,                      -- = patients.patient_id
    facility_id           integer,
    display_name          text,

    -- extracted wound fields
    wound_type            text,
    stage                 text,
    location              text,
    length_cm             numeric,
    width_cm              numeric,
    depth_cm              numeric,
    drainage_amount       text,                      -- none / light / moderate / heavy
    extraction_confidence text,                      -- high / medium / low
    source_format         text,

    -- coverage / sync
    has_active_mcb        boolean,
    sync_complete         boolean,

    -- eligibility axis
    eligibility_decision  text,                      -- auto_accept / flag_for_review / reject
    eligibility_reason    text,

    -- audit-risk axis (independent of eligibility)
    audit_risk_level      text,                      -- none / low / medium / high
    audit_risk_flags      jsonb,                     -- array of {code, reason}

    -- evidence / provenance
    evidence_note_excerpt text,
    source_note_id        bigint,
    source_assessment_id  bigint,

    processed_at          timestamptz default now()
);

create index if not exists eligibility_results_decision_idx
    on eligibility_results (eligibility_decision);
create index if not exists eligibility_results_risk_idx
    on eligibility_results (audit_risk_level);

-- ----------------------------------------------------------------------------
-- Sync state (incremental-sync bonus) — one row per endpoint
-- ----------------------------------------------------------------------------

create table if not exists sync_state (
    endpoint        text primary key,
    last_synced_at  timestamptz
);

-- ----------------------------------------------------------------------------
-- Ingest status — per-patient, per-endpoint fetch outcome.
-- sync_complete is derived from this later: a patient is sync-complete only when
-- every required endpoint has status = 'ok'. A failed fetch is recorded here,
-- never silently dropped (CLAUDE.md hard rule 3).
-- ----------------------------------------------------------------------------

create table if not exists ingest_status (
    patient_internal_id   bigint,
    patient_id            text,
    endpoint              text,        -- diagnoses / coverage / notes / assessments
    status                text,        -- ok / failed
    error                 text,
    attempts              integer,
    fetched_at            timestamptz default now(),
    primary key (patient_internal_id, endpoint)
);

create index if not exists ingest_status_status_idx on ingest_status (status);
