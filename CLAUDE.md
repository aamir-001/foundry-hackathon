# CLAUDE.md

Project context for Claude Code. Full spec lives in [PRD.md](./PRD.md) — read it for decision logic and schema details. This file is the operational guide: structure, commands, conventions, and the domain rules that must never be broken.

## What this is

A decision-support pipeline + dashboard for the ABI Frameworks hackathon. A **Python pipeline** pulls synthetic patient data from a mock PointClickCare (PCC) API, extracts wound details, and decides which patients are billable to Medicare Part B for wound care. A **Next.js dashboard** presents the results as a biller's triage queue. Data is synthetic — no PHI.

## Architecture

```
Mock PCC API  →  Python pipeline (ingest → extract → decide)  →  Supabase Postgres  →  Next.js dashboard (Vercel)
```

Python and TypeScript meet only at the database. Don't try to share code across them, and don't put the Python pipeline on Vercel or in a Supabase Edge Function (Edge Functions are Deno/TS-only; the pipeline is a standalone batch script).

## Tech stack

- **Pipeline:** Python 3.11+ — `httpx`, `tenacity`, `pydantic`, `anthropic`, `supabase` (or `psycopg`/SQLAlchemy), `python-dotenv`.
- **Frontend:** Next.js (App Router) + TypeScript + Tailwind, deployed on Vercel. Reads Supabase via `@supabase/supabase-js`.
- **DB:** Supabase Postgres.

## Repo structure

```
/
├── pipeline/                 # Python — the data pipeline
│   ├── config.py             # env + base URL
│   ├── pcc_client.py         # httpx wrapper with 429 retry (tenacity)
│   ├── models.py             # pydantic models
│   ├── ingest.py             # fetch all endpoints → raw Supabase tables
│   ├── extract/
│   │   ├── format_detect.py  # detect format from BODY content, not note_type
│   │   ├── text_fields.py    # shared core: wound fields from any text blob (regex tiers)
│   │   ├── notes.py          # adapter: note_text → text_fields
│   │   ├── assessments.py    # adapter: dig narrative out of nested sections → text_fields
│   │   └── llm.py            # Anthropic fallback for Envive / low-confidence text
│   ├── decide/
│   │   ├── eligibility.py    # auto_accept / flag_for_review / reject
│   │   └── audit_risk.py     # independent risk flags
│   ├── store.py              # Supabase writes
│   └── run.py                # orchestrates the full run
├── web/                      # Next.js dashboard (Claude Design output) → Vercel
│   ├── app/page.tsx          # triage dashboard
│   ├── app/components/       # KpiCards, TriageTable, DecisionBadge, RiskBadge, FilterTabs, PatientModal
│   └── lib/supabase.ts
├── supabase/schema.sql
├── requirements.txt          # (or pyproject.toml)
├── .env.example
├── PRD.md
└── CLAUDE.md
```

## Commands

```bash
# Pipeline (Python)
uv venv && source .venv/bin/activate
uv pip install -r requirements.txt
python -m pipeline.ingest      # raw fetch → Supabase
python -m pipeline.run         # full: ingest → extract → decide → eligibility_results

# Frontend
cd web && npm install
npm run dev                    # local
npm run build                  # prod build (Vercel runs this)
```

## Environment variables (`.env.example`)

```
PCC_BASE_URL=https://hackathon.prod.pulsefoundry.ai
ANTHROPIC_API_KEY=
SUPABASE_URL=
SUPABASE_SERVICE_ROLE_KEY=          # pipeline writes (server-side only, never client)
NEXT_PUBLIC_SUPABASE_URL=
NEXT_PUBLIC_SUPABASE_ANON_KEY=      # frontend reads
```

## Domain rules — DO NOT BREAK

1. **Two patient identifiers.** String `patient_id` (`FA-001`) → diagnoses + coverage. Integer `id` (`1`) → notes + assessments. Both come from `/patients`. Mixing them up is the #1 bug — keep them distinctly named (`patient_id` vs `patient_internal_id`) everywhere.
2. **Every API call can 429** (~30% chance, `Retry-After` 1–5s). All fetches go through `pcc_client.py` with retry/backoff. Never call the API directly elsewhere.
3. **A failed fetch is never a clinical fact.** If a required endpoint fails after retries: store partial data, set `sync_complete = false`, route to `flag_for_review` ("sync incomplete"). **Never `reject` on a failed fetch** — the patient may well be eligible.
4. **Two independent decision axes.** `eligibility_decision` (auto_accept/flag_for_review/reject) and `audit_risk_level` (none/low/medium/high) are computed and stored separately. Never collapse them into one field — a patient can be auto-accept _and_ high-risk.
5. **Extraction confidence by source — REVISED after Phase 1 probe.** Assessment `raw_json` is NOT flat; it's nested `sections → questions → {question, answer}` with wound data as free text inside the answer. Both notes and assessments go through one shared text extractor (`text_fields.py`) via per-source adapters. **Detect format from the BODY, never from `note_type`** — a `"Wound (SPN)"` note was found wrapping an Envive body. Confidence tiers: templated `Label: value` narrative (slash/newline-delimited; common in assessments + SPN notes) = high via regex; prose shorthand (`Meas 4.2x3.1x1.5cm`) = medium; Envive narrative (signature `*Envive Care Conference Review`) = low unless the LLM returns all fields. Always store `extraction_confidence` and `source_format`.
6. **Audit-risk flags run on single-record data only.** Phase 1 confirmed 1 assessment + ≤2 notes per patient. The trajectory flags (`STALLED_WOUND`, `HIGH_VISIT_FREQUENCY`, `AREA_INCREASE`) are **cut** — do not build them. The active set is `NO_WOUND_ICD10`, `NEW_ADMISSION_HIGH_STAGE`, and `LOW_CONFIDENCE_DOCUMENTATION` (all single-record). `RECENT_COVERAGE_GAP` only if the 300-patient census surfaces multi-visit patients. See PRD §8.2.
7. **No fabricated numbers.** KPI cards show counts, not invented revenue/dollar figures.
8. **Dashboard is read-only.** No write-back to PCC, no claim submission. Any "mark reviewed" is local UI state only.

## Decision logic (summary — full version in PRD §8)

- `auto_accept`: sync complete + active MCB + wound found + length/width/depth/drainage present + not ambiguous.
- `flag_for_review`: sync incomplete, OR wound found but fields missing, OR ambiguous (low-confidence Envive / unclear primary wound), OR coverage unverifiable.
- `reject`: only when data WAS fetched and the patient is confirmed not-MCB or confirmed no wound.
- Active Medicare Part B = `payer_code = MCB` with `effective_to = null`.

## LLM extraction conventions (`extract/llm.py`)

- Used as the fallback for any low-confidence text the regex tiers can't cleanly parse — Envive narratives in notes _and_ assessment answers (and optionally multi-wound primary selection).
- Prompt must demand **JSON only**, fixed keys (`wound_type, stage, location, length_cm, width_cm, depth_cm, drainage_amount`), `null` for absent fields. Parse defensively (strip code fences, try/except).
- Bounded extraction: pull only the wound fields, nothing else. If the model returns incomplete/uncertain output, that lowers confidence and pushes toward `flag_for_review` — never silently trust it.
- Model string: `claude-sonnet-4-6` for extraction (fast/cheap, sufficient here).

## Frontend conventions (`web/`)

- Table-first triage, 5–7 columns. Two badges per row: eligibility + audit-risk. One-line reason.
- Color **and** icon for every decision (colorblind-safe). Default sort: audit-risk descending.
- Filter tabs with counts: All / Needs Review / Auto-Accept / Reject.
- Row click → modal: raw note excerpt with extracted fields highlighted + confidence + reasoning bullets. This is the highest-value component; prioritize it.

## Out of scope (mention in the deck, don't build)

- Supabase Queues (pgmq) — production answer to rate limiting; retry loop is enough at this scale.
- pg_cron scheduling — for incremental sync, just run the script with a stored last-sync timestamp.
- SNOMED mapping, PHI de-identification — not relevant to synthetic data.
