# Aamir — Implementation Tracker

## Architecture

```
API -> retrying client -> SQLite raw store -> completeness check -> extraction (regex + structured parse; optional LLM) -> eligibility routing + compliance flags -> Streamlit dashboard
```

## What We Implemented

### 1. Retrying API Client (`pipeline/api_client.py`)
- Shared `get_with_retry()` function for all API calls
- Reads `Retry-After` header on 429s
- Exponential backoff with configurable max retries
- Returns structured result with status, data, and error

### 2. SQLite Database (`pipeline/database.py`)
- Raw storage tables: `raw_patients`, `raw_diagnoses`, `raw_coverage`, `raw_notes`, `raw_assessments`
- `api_fetch_status` table tracking per-patient, per-endpoint fetch results
- `wound_extractions` table for extracted wound fields
- `eligibility_decisions` table for final routing
- All inserts are upserts (idempotent — safe to re-run)

### 3. Data Ingestion (`pipeline/ingest.py`)
- Fetches all 300 patients across 3 facilities
- Per-patient fetches: coverage, diagnoses, notes, assessments
- Records fetch status for every call
- Stores raw API responses in SQLite

### 4. Wound Extraction (`pipeline/extract.py`)
- **Default = deterministic, no LLM.** All demo data was extracted with regex +
  structured assessment parsing. No external model was called.
- Regex extraction for free-text notes (SOAP, prose shorthand like `Meas 8.0x3.5x0.2cm`,
  `Measures X x Y cm`, Envive narrative)
- Parses nested Q&A JSON from `raw_assessments` directly (highest confidence source)
- Extracts: wound type, stage, location, length, width, depth, drainage
- **Optional LLM fallback** (`pipeline/extract.py:llm_extract`), OFF by default — only
  runs when `LLM_ENABLED=true`. When enabled it tries Claude (if `ANTHROPIC_API_KEY` is
  set) and otherwise falls back to a local Ollama/Mistral model. Used only for notes where
  regex leaves required fields empty. Not used in the current build (regex coverage was
  sufficient; flagged-low notes route to `flag_for_review` instead).

### 5. Eligibility & Routing (`pipeline/eligibility.py`)
- Checks Medicare Part B coverage (payer_code = MCB, no end date or future end date)
- Checks active wound diagnosis
- Completeness check before routing (did all endpoints succeed?)
- Routing: `auto_accept` / `flag_for_review` / `reject` with plain-English reason

### 6. Compliance / Denial-Risk Flags (`pipeline/eligibility.py`)

A **second layer** on top of the base eligibility decision that surfaces audit-risk and
denial-risk patterns. The base decision answers *"is this patient billable?"*; the flag
layer answers *"even if billable, is there a compliance risk a biller should see first?"*

**Architecture — two-stage decision flow:**

```
                 ┌──────────────────────────────┐
                 │   STAGE 1: Base Eligibility   │
                 │   make_decision()             │
                 │                               │
                 │   sync complete? ─────────────┼─► flag_for_review (incomplete data)
                 │   Medicare B? ────────────────┼─► reject (no MCB)
                 │   wound documented? ──────────┼─► reject (no wound)
                 │   measurements complete? ─────┼─► flag_for_review (missing fields)
                 │   confidence high/med? ───────┼─► auto_accept
                 └───────────────┬───────────────┘
                                 │  base decision + reason
                                 ▼
                 ┌──────────────────────────────┐
                 │   STAGE 2: Compliance Flags   │
                 │   get_compliance_flags()      │
                 │                               │
                 │   returns [{code, message,    │
                 │             severity}]        │
                 └───────────────┬───────────────┘
                                 │
                                 ▼
                 ┌──────────────────────────────┐
                 │   Flag application rule       │
                 │                               │
                 │   if base == auto_accept AND  │
                 │      any flag.severity=review │
                 │   → DOWNGRADE to              │
                 │     flag_for_review           │
                 │   else                        │
                 │   → keep decision, append     │
                 │     flag messages to reason   │
                 └───────────────┬───────────────┘
                                 │
                                 ▼
                 stored in eligibility_decisions:
                   decision, reason,
                   compliance_flags (JSON), flag_count
```

**Design rule:** flags are *soft* — they can only **downgrade** `auto_accept → flag_for_review`,
never upgrade a `reject`. A flag is an annotation for a human, not an override of clinical
eligibility. This keeps the audit trail clean: a downgraded patient shows both the original
billable status and why it was held back.

**Flags implemented:**

| Code | Trigger | Source data | Severity | Fires on |
|---|---|---|---|---|
| `NEW_ADMIT_ADVANCED_WOUND` | New admission + Stage 3/4/unstageable wound | `raw_patients.is_new_admission` + extracted stage | review | FA-001, FC-003 |
| `NO_WOUND_ICD10` | MCB + extracted wound but no active wound ICD-10 | `wound_extractions` + `raw_diagnoses` | review | 0 (see note) |

**`NEW_ADMIT_ADVANCED_WOUND`** — a Stage 3/4 pressure ulcer on a day-1 admission most
likely developed at a *prior* facility. Present-on-admission vs. facility-acquired must be
documented before billing (a known RAC/CMS audit trigger). FC-003 was a clean `auto_accept`
that this flag correctly downgraded to `flag_for_review`.

**`NO_WOUND_ICD10`** — we extract a billable wound from a note/assessment, but there is no
supporting active wound ICD-10 on file → medical necessity unsupported → claim denial risk.

**Burn ICD-10 bug found *by* flag 4 (the real value):** While building `NO_WOUND_ICD10`,
the flag surfaced 6 burn patients as "no wound diagnosis." Investigation showed they *did*
have valid burn codes (`T22.219A`) — our `WOUND_ICD10_PREFIXES` matcher was missing the
entire `T20–T28` burn-by-site range (it only had `T30`/`T31`, burns by extent). We fixed
the prefix list (`T20`–`T28`, `T30`–`T32`, plus `L98.4`); the flag now correctly shows zero
false billables. **The flag did its job as a QA tool during development — it caught a bug in
our own matcher, not a coding gap in the data.** It remains in place as a correct guardrail.

**Storage:** flags persisted as a JSON array in `eligibility_decisions.compliance_flags`,
with `flag_count` for fast filtering/metrics.

### 7. Streamlit Dashboard (`dashboard.py`)
- Visual overview of all patients with routing decisions
- Color-coded routing (green/yellow/red)
- Filterable by facility, decision, wound type
- **Compliance & Denial-Risk Flags section** — dedicated table of flagged patients,
  flag-type breakdown chart, and per-patient flag detail in the drill-down view
- Patient detail view with clinical notes and extraction results

## Tech Stack

| Component | Choice |
|---|---|
| Language | Python 3.10 |
| Database | SQLite |
| API client | requests + retry |
| Structured extraction | Regex |
| Structured assessments | Nested Q&A JSON parser |
| Optional LLM fallback (off by default) | Claude API → local Ollama/Mistral |
| Dashboard | Streamlit |

## Key Design Decisions

- **Store raw responses before extraction** — allows re-running extraction without re-fetching
- **Track fetch status separately** — distinguishes "no data exists" from "fetch failed"
- **Upserts everywhere** — pipeline is idempotent, safe to re-run after crashes
- **Deterministic by default** — regex + structured parsing handle the data with no LLM
  in the loop; the optional LLM is a documented fallback (off by default), so output is
  reproducible and free of model/network dependencies
- **Completeness check before routing** — incomplete data = flag_for_review, never auto_accept
- **Compliance flags layer** — audit-risk patterns can only downgrade auto_accept, never upgrade

## Secrets & Safety

- **No API key is committed.** The Claude key only ever lived in the shell environment
  (`ANTHROPIC_API_KEY`), never in a file. The README shows only a `sk-ant-...` placeholder.
- `.gitignore` excludes `.env`, `*.key`, `secrets.json`, and `hackathon.db` so neither
  secrets nor the generated database can be pushed.
- To use the optional LLM: `export ANTHROPIC_API_KEY=...` then `LLM_ENABLED=true python -m pipeline.extract`.

---

## Production Problem Analysis (Rate Limiting & Data Integrity)

### The Core Problem

In PCC-like EHR integrations, a single patient profile is assembled from multiple endpoints that use different identifiers, update at different times, and fail independently. If the system treats failed fetches as missing clinical facts, it makes wrong billing decisions.

### Two-ID System

```
patient_id = "FA-001"   → used for /diagnoses and /coverage
id = 1                  → used for /notes and /assessments
```

Wrong ID mapping = wrong wound data attached to wrong payer record.

### Seven Production Risks We Address

#### 1. Wrong Patient Joins
If ID mapping is wrong, you combine coverage from Patient A with notes from Patient B. Looks complete but is clinically wrong.

#### 2. Duplicate Patient Records
Same patient under multiple IDs or facilities → fragmented histories, missed eligibility, duplicate review tasks.

#### 3. Record Overlay
Two real patients merged into one record → false billing candidate. Worse than duplication.

#### 4. Incomplete Syncs Misread as Missing Facts
Coverage endpoint fails → system thinks "no Medicare B" instead of "couldn't check." Our `api_fetch_status` table prevents this.

#### 5. False Billing Decisions
- **False negative**: eligible patient missed because notes endpoint failed
- **False positive**: old wound note fetched, latest assessment missing, coverage appears active

#### 6. Stale Data
Pipeline uses cached data from hours ago. Patient's wound may have resolved or coverage changed since.

#### 7. Bad User Trust
Biller loses trust if dashboard says "no wound measurements" but PCC has them. Better: "assessment endpoint failed, measurements could not be verified."

### Our Three Safety Layers

1. **Identifier mapping** — store both `internal_id` and `pcc_patient_id` explicitly, never infer
2. **Fetch-status tracking** — per-patient, per-endpoint: `success` / `failed_after_retry` / `no_records_found`
3. **Decision safety** — only `auto_accept` or clean `reject` when required endpoints succeeded; otherwise `flag_for_review`

### Key Presentation Line

> "The main production risk is confusing infrastructure failure with clinical absence. Our pipeline separates 'data not found' from 'data not fetched,' so we do not make billing decisions from incomplete patient profiles."
