# ABI Frameworks — Wound Care Billing Pipeline

## Overview

A resilient data pipeline that pulls patient data from PointClickCare (PCC), extracts wound details from clinical notes and assessments, and produces an eligibility triage dashboard for Medicare Part B wound care billing.

**Live dashboard:** `streamlit run dashboard.py`
**Run pipeline:** `python -m pipeline.main`

---

## Architecture

```
                        ┌─────────────────────────────────────────────────────────────┐
                        │                    PCC Mock API                              │
                        │         https://hackathon.prod.pulsefoundry.ai              │
                        │                                                             │
                        │  /patients  /diagnoses  /coverage  /notes  /assessments     │
                        └──────┬──────────┬──────────┬─────────┬──────────┬───────────┘
                               │          │          │         │          │
                               │    30% chance of HTTP 429 on each call  │
                               │          │          │         │          │
                        ┌──────▼──────────▼──────────▼─────────▼──────────▼───────────┐
                        │              Retrying API Client                             │
                        │           (pipeline/api_client.py)                           │
                        │                                                             │
                        │  • Reads Retry-After header on 429s                         │
                        │  • Exponential backoff, max 6 retries                       │
                        │  • Returns structured {status, data, error, attempts}       │
                        └──────────────────────┬──────────────────────────────────────┘
                                               │
                        ┌──────────────────────▼──────────────────────────────────────┐
                        │              Data Ingestion Layer                            │
                        │             (pipeline/ingest.py)                             │
                        │                                                             │
                        │  • Fetches 300 patients across 3 facilities (101/102/103)   │
                        │  • Per-patient: diagnoses, coverage, notes, assessments     │
                        │  • Records fetch status for every endpoint call             │
                        │  • ~1,200 API calls with retry handling                     │
                        └──────────────────────┬──────────────────────────────────────┘
                                               │
                        ┌──────────────────────▼──────────────────────────────────────┐
                        │              SQLite Raw Data Store                           │
                        │            (pipeline/database.py)                            │
                        │                                                             │
                        │  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐         │
                        │  │ raw_patients  │ │ raw_diagnoses│ │ raw_coverage │         │
                        │  └──────────────┘ └──────────────┘ └──────────────┘         │
                        │  ┌──────────────┐ ┌──────────────┐ ┌────────────────────┐   │
                        │  │  raw_notes   │ │raw_assessments│ │ api_fetch_status  │   │
                        │  └──────────────┘ └──────────────┘ └────────────────────┘   │
                        │                                                             │
                        │  • All inserts are upserts (idempotent, crash-safe)         │
                        │  • api_fetch_status tracks per-patient endpoint results     │
                        └──────────────────────┬──────────────────────────────────────┘
                                               │
                        ┌──────────────────────▼──────────────────────────────────────┐
                        │              Wound Extraction Engine                         │
                        │             (pipeline/extract.py)                            │
                        │                                                             │
                        │  ┌─────────────────┐    ┌──────────────────────┐            │
                        │  │  Structured      │    │  Free-Text Notes     │            │
                        │  │  Assessments     │    │                      │            │
                        │  │                  │    │  ┌───────┐  ┌─────┐ │            │
                        │  │  Parse nested    │    │  │ Regex │→│ LLM │ │            │
                        │  │  Q&A JSON        │    │  │ first │  │fallback│            │
                        │  │  sections        │    │  └───────┘  └─────┘ │            │
                        │  └────────┬─────────┘    └─────────┬───────────┘            │
                        │           │                        │                        │
                        │           ▼                        ▼                        │
                        │  ┌─────────────────────────────────────────────┐            │
                        │  │  wound_type, stage, location,               │            │
                        │  │  length_cm, width_cm, depth_cm, drainage   │            │
                        │  │  + confidence (high / medium / low)        │            │
                        │  └─────────────────────────────────────────────┘            │
                        └──────────────────────┬──────────────────────────────────────┘
                                               │
                        ┌──────────────────────▼──────────────────────────────────────┐
                        │              Eligibility & Routing Engine                    │
                        │           (pipeline/eligibility.py)                          │
                        │                                                             │
                        │  1. Completeness check — did all endpoints succeed?         │
                        │  2. Medicare Part B check — payer_code MCB, no end date     │
                        │  3. Active wound check — ICD-10 codes (L89, L97, E11.62…)  │
                        │  4. Measurement completeness — L × W × D + drainage        │
                        │  5. Confidence check — regex-only vs LLM-assisted           │
                        │                                                             │
                        │  ┌──────────────┐ ┌────────────────┐ ┌──────────┐          │
                        │  │ auto_accept  │ │ flag_for_review│ │  reject  │          │
                        │  │   (green)    │ │    (yellow)    │ │  (red)   │          │
                        │  └──────────────┘ └────────────────┘ └──────────┘          │
                        └──────────────────────┬──────────────────────────────────────┘
                                               │
                        ┌──────────────────────▼──────────────────────────────────────┐
                        │              Streamlit Dashboard                             │
                        │               (dashboard.py)                                │
                        │                                                             │
                        │  • Summary metrics (total, accepted, review, rejected)      │
                        │  • Filters: facility, decision, wound type                  │
                        │  • Decision breakdown charts by facility                    │
                        │  • Color-coded patient table with routing decisions          │
                        │  • Patient detail view: wound info, clinical notes,         │
                        │    assessments, extraction results                          │
                        │  • API sync health monitor                                  │
                        └─────────────────────────────────────────────────────────────┘
```

---

## How It Works

### 1. Data Ingestion

The pipeline fetches data from 5 PCC API endpoints for 300 patients across 3 facilities. Every request has a 30% chance of HTTP 429 — the retrying client reads the `Retry-After` header and backs off automatically.

Two patient identifiers are used:
- `patient_id` (string like `FA-001`) — for `/diagnoses` and `/coverage`
- `id` (integer like `1`) — for `/notes` and `/assessments`

Both are stored explicitly. The pipeline never infers one from the other.

### 2. Wound Extraction

**Structured assessments** — parsed directly from nested Q&A JSON format with sections for wound info, location, drainage.

**Clinical notes** — a two-pass approach:
1. **Regex first** (fast, deterministic) — handles SOAP notes, `Measures X x Y cm` patterns, `Meas XxYxZcm` shorthand, and labeled fields
2. **LLM fallback** (Claude API or Ollama/Mistral) — for Envive narrative format and prose notes where regex can't extract all fields

Each extraction is tagged with a confidence level:
- `high` — regex captured all fields, or structured assessment data
- `medium` — LLM assisted extraction
- `low` — regex only, incomplete fields

### 3. Eligibility Routing

Before making any decision, the pipeline checks **sync completeness** — did all 4 endpoints (coverage, diagnoses, notes, assessments) succeed for this patient?

| Decision | Criteria |
|---|---|
| `auto_accept` | Medicare B active + wound documented + all measurements present + high/medium confidence |
| `flag_for_review` | Medicare B active but missing measurements, low confidence extraction, or incomplete sync |
| `reject` | No Medicare B coverage, or no wound documentation found |

Every decision includes a **plain-English reason** explaining why.

### 4. Safety Layers

The pipeline separates **"data not found"** from **"data not fetched"**:

1. **Identifier mapping** — both `internal_id` and `pcc_patient_id` stored explicitly
2. **Fetch-status tracking** — `api_fetch_status` table records success/failure per patient per endpoint
3. **Decision safety** — `auto_accept` only when all required data was successfully fetched

> "The main production risk is confusing infrastructure failure with clinical absence. Our pipeline separates 'data not found' from 'data not fetched,' so we do not make billing decisions from incomplete patient profiles."

---

## Quick Start

```bash
# 1. Install dependencies
pip install requests streamlit anthropic

# 2. Set API key for LLM extraction (optional)
export ANTHROPIC_API_KEY=sk-ant-...

# 3. Run the full pipeline
python -m pipeline.main

# 4. Launch the dashboard
streamlit run dashboard.py
```

To enable LLM-assisted extraction (for messy Envive notes):
```bash
LLM_ENABLED=true python -m pipeline.extract
```

---

## Tech Stack

| Component | Choice |
|---|---|
| Language | Python 3.10 |
| Database | SQLite (zero-setup, single file) |
| API client | `requests` + retry with `Retry-After` |
| Structured extraction | Regex (deterministic, fast) |
| Unstructured extraction | Claude API / Ollama Mistral (LLM fallback) |
| Dashboard | Streamlit |

---

## Project Structure

```
├── pipeline/
│   ├── api_client.py      # Retrying HTTP client
│   ├── database.py        # SQLite schema + upsert operations
│   ├── ingest.py          # Data ingestion from PCC API
│   ├── extract.py         # Wound extraction (regex + LLM)
│   ├── eligibility.py     # Routing decisions + completeness checks
│   └── main.py            # Pipeline orchestrator
├── dashboard.py           # Streamlit visual dashboard
├── hackathon.db           # SQLite database (generated)
├── API.md                 # API reference documentation
└── aamir-implementations.md  # Implementation tracker
```

---

## Results

| Metric | Count |
|---|---|
| Total patients | 300 |
| Total wound extractions | 547 |
| High confidence extractions | 435 |
| Structured (assessments) | 250 |
| Regex (notes) | 297 |
| **auto_accept** | **85** |
| **flag_for_review** | **35** |
| **reject** | **180** |

---

## Key Design Decisions

- **Raw responses stored before extraction** — re-run extraction without re-fetching from API
- **Fetch status tracked separately** — distinguishes "no data exists" from "fetch failed"
- **Upserts everywhere** — pipeline is idempotent, safe to re-run after crashes
- **Regex first, LLM second** — fast + deterministic for structured notes, LLM only for messy ones
- **Completeness check before routing** — incomplete data = flag_for_review, never auto_accept
