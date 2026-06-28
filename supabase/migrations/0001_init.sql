-- Wound-Care Billing Triage — schema (BUILD_PLAN §5)
-- Run this in the Supabase SQL editor (or via the Supabase CLI) once per project.
-- Raw tables mirror the PCC API exactly (never lose source); `triage` is the
-- single denormalized output table the dashboard reads.

-- ───────────────────────── RAW MIRROR TABLES ─────────────────────────

create table if not exists patient (
  id                  int  primary key,            -- internal integer id (notes/assessments key)
  patient_id          text unique not null,        -- PCC string id (diagnoses/coverage key)
  facility_id         int,
  first_name          text,
  last_name           text,
  birth_date          date,
  gender              text,
  primary_payer_code  text,
  last_modified_at    timestamptz,
  is_new_admission    boolean
);

create table if not exists diagnosis (
  id                int  primary key,
  patient_id        text not null references patient(patient_id),
  icd10_code        text,
  icd10_description text,
  clinical_status   text,                            -- active | resolved | inactive
  onset_date        date,
  last_modified_at  timestamptz
);
create index if not exists diagnosis_patient_idx on diagnosis(patient_id);

create table if not exists coverage (
  id               int  primary key,
  patient_id       text not null references patient(patient_id),
  payer_name       text,
  payer_code       text,                             -- MCB | MCA | MCD | HMO (eligibility keys on this)
  payer_type       text,                             -- TRAP: collapses Medicare variants; never use
  effective_from   timestamptz,
  effective_to     timestamptz,                      -- null => currently active
  last_modified_at timestamptz
);
create index if not exists coverage_patient_idx on coverage(patient_id);

create table if not exists note (
  id             int  primary key,
  patient_id     int  not null references patient(id),
  org_id         text,
  pcc_note_id    bigint,
  note_type      text,
  effective_date timestamptz,
  note_text      text,
  created_by     text,
  note_label     text,
  sync_version   int,
  is_current     boolean
);
create index if not exists note_patient_idx on note(patient_id);

create table if not exists assessment (
  id                          int  primary key,
  patient_id                  int  not null references patient(id),
  org_id                      text,
  pcc_assessment_id           bigint,
  assessment_type             text,
  status                      text,
  assessment_date             date,
  completion_date             date,
  template_id                 int,
  assessment_type_description text,
  raw_json                    jsonb,                 -- structured OR narrative sub-schema
  sync_version                int,
  is_current                  boolean
);
create index if not exists assessment_patient_idx on assessment(patient_id);

-- ───────────────────────── OUTPUT TABLE ─────────────────────────

create table if not exists triage (
  patient_id text primary key,
  first_name text,
  last_name  text,
  facility_id int,
  -- extracted (final, post-recovery)
  wound_type text,
  stage text,
  location text,
  laterality text,
  length_cm numeric,
  width_cm numeric,
  depth_cm numeric,
  drainage_present boolean,
  drainage_type text,
  drainage_amount text,
  is_multi_wound boolean,
  suggested_primary text,
  -- eligibility (the 3 criteria)
  has_active_wound boolean,
  has_active_mcb boolean,
  has_required_measures boolean,
  has_wound_dx_code boolean,
  -- decision
  routing_decision text,        -- auto_accept | flag_for_review | reject
  score int,                    -- 100 - Σ hard deductions (eligible + extractable only)
  reason text,                  -- plain-English rationale
  reject_reason text,           -- no_active_wound | not_medicare_b | extraction_unreliable
  flags text[],                 -- hard + soft signals
  -- per-field recovery + provenance (§8)
  field_status jsonb,           -- {depth:{value,source,tier}, stage:{...}, ...}
  -- trust + worklist + narration
  confidence numeric,
  status text default 'pending',-- pending | reviewed | submitted | dismissed
  biller_inputs jsonb,
  narrative text
);
-- Biller worklist query: flagged + pending, worst score first.
create index if not exists triage_worklist_idx on triage(routing_decision, status, score);

-- ───────────────────────── PIPELINE STATE ─────────────────────────

create table if not exists sync_state (
  resource  text primary key,
  watermark timestamptz
);

create table if not exists pipeline_run (
  id          uuid primary key default gen_random_uuid(),
  phase       text,
  started_at  timestamptz,
  finished_at timestamptz,
  patients    int,
  retries     int
);
