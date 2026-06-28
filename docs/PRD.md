# PRD — WoundBill Triage

**A decision-support tool that tells a medical biller which post-acute patients can be billed to Medicare Part B for wound care — and which ones carry audit risk.**

Built for the ABI Frameworks hackathon. All data is synthetic (no PHI).

---

## 1. Summary

A biller today manually opens each patient's chart, hunts for wound measurements buried in free-text notes, checks insurance, and decides whether a Medicare Part B wound-care claim is safe to submit. This is slow and error-prone.

WoundBill Triage automates the data collection and triage. A Python pipeline pulls patient data from a mock PointClickCare (PCC) API, extracts wound details from both structured assessments and messy free-text notes, and produces one decision row per patient. A web dashboard presents those decisions as a triage queue a non-technical biller can work through at a glance.

---

## 2. Problem & Context

Wound care billing under Medicare Part B requires three things to be true:

1. The patient has an **active wound** (pressure ulcer, diabetic foot ulcer, venous/arterial ulcer, etc.).
2. The patient has **active Medicare Part B coverage**.
3. The wound is **documented** with measurements (length, width, depth) and a drainage level.

The data needed to verify this is spread across five API endpoints, arrives in inconsistent formats, and the API intentionally fails ~30% of requests. The pipeline must stitch it together, handle failure gracefully, and never guess.

---

## 3. Primary User

A **non-technical medical biller** working a queue. They do not read raw data, JSON, or pipeline internals. Their job is to look at a list, see who is ready to bill, see who needs a human check, and understand _why_ in plain English. The product is optimized for fast, confident, case-by-case triage — not for analytics or dashboards full of charts.

---

## 4. Goals / Non-Goals

**Goals**

- Ingest all patients, diagnoses, coverage, notes, and assessments, surviving rate limits.
- Extract wound fields from structured _and_ free-text sources, with a confidence signal.
- Produce a per-patient eligibility decision **and** a separate audit-risk signal, each with a plain-English reason.
- Present results as a scannable triage queue with drill-down evidence.

**Non-Goals**

- Writing back to PCC or actually submitting claims (this is decision support, read-only).
- Inventing dollar/revenue figures the synthetic data doesn't support.
- Real PHI handling, de-identification, or SNOMED mapping (out of scope for this data).
- A production sync engine — incremental sync is a bonus, not a requirement.

---

## 5. Core Concept: Two Independent Decision Axes

This is the spine of the product. Every patient gets scored on **two separate questions**:

| Axis            | Question it answers                                   | Values                                               |
| --------------- | ----------------------------------------------------- | ---------------------------------------------------- |
| **Eligibility** | Can we bill this patient?                             | `auto_accept` / `flag_for_review` / `reject`         |
| **Audit risk**  | Even if billable, should someone scrutinize it first? | `none` / `low` / `medium` / `high` (+ list of flags) |

These are **orthogonal**. A patient can be `auto_accept` on eligibility _and_ high audit-risk (e.g. billed across six visits with no wound reduction). Collapsing them into one column would hide exactly the cases that matter most. The dashboard shows both, side by side.

This maps directly to the product pitch: _surface missed billables_ = the eligibility axis; _flag denial/audit risk before data leaves the pipeline_ = the audit-risk axis.

---

## 6. Functional Requirements

### 6.1 Data Ingestion (Python)

- Fetch all patients for facilities `101`, `102`, `103`.
- For each patient, fetch diagnoses + coverage (keyed by string `patient_id`, e.g. `FA-001`) and notes + assessments (keyed by integer `id`).
- **Handle the 30% HTTP 429 rate limit** with retry + backoff, honoring the `Retry-After` header. A failed call is _expected_, not exceptional.
- **Never treat a failed fetch as a clinical fact.** If a required endpoint fails after retries, store whatever succeeded, mark the patient `sync_complete = false`, and route to `flag_for_review` with reason "sync incomplete" — never `reject`.
- Persist raw records to Supabase Postgres.

### 6.2 Wound Extraction (Python)

From notes and assessments, extract: `wound_type`, `stage` (pressure ulcers), `location`, `length_cm`, `width_cm`, `depth_cm`, `drainage_amount` (`none` / `light` / `moderate` / `heavy`).

**Both notes and assessments require text extraction** (revised after the Phase 1 probe — see note below). The clean design is one shared text-field extractor with thin per-source adapters:

- **Notes adapter** → `note_text` is already plain text, pass it straight through.
- **Assessments adapter** → `raw_json` is NOT flat. It's nested `sections → questions → {question, answer}`, with the wound details living as free text inside a "Wound narrative" answer. Dig that narrative string out, then feed it to the same extractor.

Confidence tiers are driven by the **format of the text body**, detected from content (NOT from `note_type`, which is unreliable):

1. **Templated `Label: value` narrative** — slash- or newline-delimited, e.g. `Pressure Ulcer to Right hip / Measures 2.9 cm x 2.8 cm / Stage: Stage 3 / Drainage: serosanguineous, heavy`. Common in assessment narratives and SPN-style notes. Regex-parsable → **high** confidence.
2. **Prose shorthand** — e.g. `Meas 4.2x3.1x1.5cm` embedded in a sentence. Regex with fallback → **medium**.
3. **Envive narrative** — everything packed into one prose paragraph (signature: `*Envive Care Conference Review`). Use the **Anthropic API** with a bounded clinical-extraction prompt returning JSON only → **low** confidence unless the LLM returns all fields cleanly.

Each extraction records an `extraction_confidence` tier and the `source_format` it came from. Low confidence feeds both `flag_for_review` (eligibility) and the `LOW_CONFIDENCE_DOCUMENTATION` audit-risk flag.

> **Phase 1 data note:** `note_type` does not indicate text format — a `"Wound (SPN)"` note was found to contain an Envive body. Always detect format from the body. And assessment `raw_json` does not match the flat schema shown in the API docs; it is the nested `sections/questions` shape above.

**Multi-wound notes:** when two wounds are described, select the clinically primary one (highest stage / largest area). If unclear, mark ambiguous → contributes to `flag_for_review`.

### 6.3 Eligibility Engine (Python)

Pure function over the assembled patient record. See §8 for full logic.

### 6.4 Audit-Risk Engine (Python)

Separate pure function producing a risk level + list of flags. See §8. **Note:** several flags (visit frequency, area jumps, stalled wounds) require multiple dated records per patient — guard against single-record patients so these never throw on absent data.

### 6.5 Triage Dashboard (Next.js → Vercel)

- **KPI cards** (counts only, no fabricated revenue): total reviewed, auto-accept, flag-for-review, reject.
- **Sortable/filterable table**, 5–7 columns, one row per patient: patient identifier, wound summary, **eligibility badge**, **audit-risk indicator**, one-line reason, last note/assessment date.
- **Filter tabs with counts:** All / Needs Review / Auto-Accept / Reject.
- **Color + icon** for each decision (never color alone — colorblind-safe).
- **Default sort: audit-risk descending**, so the most demo-worthy cases surface first and the biller sees the riskiest items first.
- **Click a row → modal**: raw note excerpt with extracted fields highlighted, full extracted detail, confidence + source format, and the reasoning bullets behind both decisions. This is the highest-value component — it's the literal answer to "explain your decision."
- Read-only. No write-back/billing buttons (or, if included, a local "mark reviewed" state only — never implied claim submission).

---

## 7. Data Model (Supabase Postgres)

**Raw tables** (mirror the API):

- `patients` — `id` (int, PK), `facility_id`, `patient_id` (string), name, `birth_date`, `gender`, `primary_payer_code`, `last_modified_at`, `is_new_admission`
- `diagnoses` — `id`, `patient_id` (string FK), `icd10_code`, `icd10_description`, `clinical_status`, `onset_date`
- `coverage` — `id`, `patient_id` (string FK), `payer_name`, `payer_code`, `payer_type`, `effective_from`, `effective_to`
- `notes` — `id`, `patient_id` (int FK), `note_type`, `effective_date`, `note_text`, `created_by`
- `assessments` — `id`, `patient_id` (int FK), `assessment_type`, `status`, `assessment_date`, `raw_json` — store the raw payload as-is (jsonb); it is nested `sections → questions → {question, answer}` with wound data as free text inside the answer, not the flat schema in the API docs

**Output table** (what the frontend reads):

- `eligibility_results` — one row per patient:
  - identity: `patient_internal_id` (int), `patient_id` (string), `facility_id`, display name
  - extracted: `wound_type`, `stage`, `location`, `length_cm`, `width_cm`, `depth_cm`, `drainage_amount`, `extraction_confidence`, `source_format`
  - coverage: `has_active_mcb` (bool), `sync_complete` (bool)
  - eligibility: `eligibility_decision`, `eligibility_reason`
  - audit risk: `audit_risk_level`, `audit_risk_flags` (jsonb array of `{code, reason}`)
  - evidence: `evidence_note_excerpt`, `source_note_id` / `source_assessment_id`
  - `processed_at`

**Sync state** (incremental-sync bonus):

- `sync_state` — `endpoint`, `last_synced_at`

---

## 8. Decision Logic

### 8.1 Eligibility

Inputs per patient: `sync_complete`, `has_active_mcb`, `wound_found`, `wound_fields_complete` (length+width+depth+drainage present), `diagnosis_supports_wound`, `ambiguous` (multi-wound unresolved or low-confidence Envive).

```
auto_accept:
    sync_complete AND has_active_mcb AND wound_found
    AND wound_fields_complete AND NOT ambiguous

flag_for_review:
    NOT sync_complete                              # "Could not verify all data; do not route yet"
    OR (wound_found AND NOT wound_fields_complete) # measurements/drainage missing
    OR ambiguous                                   # Envive low-confidence or primary wound unclear
    OR (has_active_mcb unknown due to coverage fetch failure)

reject:
    sync_complete AND (
        NOT has_active_mcb                         # confirmed not Part B
        OR (NOT wound_found                        # no wound after notes+assessments+diagnoses all fetched
            AND notes/assessments/diagnoses successfully fetched)
    )
```

Golden rule: **a failed API call routes to `flag_for_review`, never `reject`.** Missing data ≠ ineligible patient.

### 8.2 Audit-Risk Flags

Computed independently of eligibility. Each flag carries a plain-English reason. **All active flags run on single-record data** (confirmed by the Phase 1 probe — see warning below).

| Flag code                      | Trigger                                                                                                | Status                                                                          |
| ------------------------------ | ------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------- |
| `NO_WOUND_ICD10`               | Routing toward billing but no active wound-related ICD-10 (`L89`, `L97`, `L98`, `E11.6`, `I83`, `T79`) | **Active**                                                                      |
| `NEW_ADMISSION_HIGH_STAGE`     | `is_new_admission` AND stage in {3, 4, unstageable} — facility-acquired liability question             | **Active**                                                                      |
| `LOW_CONFIDENCE_DOCUMENTATION` | Wound fields came from a low-confidence Envive/LLM parse — billing on shaky documentation              | **Active**                                                                      |
| `RECENT_COVERAGE_GAP`          | MCB effective < 30 days but prior wound history exists                                                 | Conditional — only if the census finds any multi-visit patients; weak otherwise |
| `STALLED_WOUND`                | 3+ visits, no measurable size reduction                                                                | **Deferred** — data is single-record                                            |
| `HIGH_VISIT_FREQUENCY`         | 4+ assessments within 30 days                                                                          | **Deferred** — data is single-record                                            |
| `AREA_INCREASE`                | Wound area up >50% between consecutive visits                                                          | **Deferred** — data is single-record                                            |

Risk level: derive from count + severity (e.g. any active flag ⇒ at least `low`; `LOW_CONFIDENCE_DOCUMENTATION` + `NO_WOUND_ICD10` together ⇒ `high`).

**Phase 1 finding (confirmed):** the probe found 1 assessment per patient and ≤2 notes (0/9 multi-visit). The three deferred flags need 3+ dated records and cannot fire on this data. Step 0 of Phase 2 is a 300-patient census (counts only) to confirm the negative across the full set. Treat trajectory analysis as a _scoping decision to explain to judges_ ("we checked all 300; the data doesn't support it"), not a feature to build.

---

## 9. Architecture & Tech Stack

```
   ┌─────────────────────────┐
   │   Mock PCC API           │  (30% 429, two patient IDs)
   └───────────┬─────────────┘
               │  httpx + tenacity retry
               ▼
   ┌─────────────────────────┐
   │  Python pipeline         │  ingest → extract → decide
   │  (standalone script)     │  Anthropic API for Envive notes
   └───────────┬─────────────┘
               │  supabase-py / psycopg
               ▼
   ┌─────────────────────────┐
   │  Supabase Postgres       │  raw tables + eligibility_results
   └───────────┬─────────────┘
               │  @supabase/supabase-js (read)
               ▼
   ┌─────────────────────────┐
   │  Next.js dashboard       │  triage queue  →  Vercel
   └─────────────────────────┘
```

**Pipeline (Python 3.11+):** `httpx` (HTTP), `tenacity` (429 retry/backoff), `pydantic` (models/validation), `anthropic` (Envive extraction), `supabase` or `psycopg`/SQLAlchemy (DB writes), `python-dotenv`. Runs locally or via a scheduled GitHub Action.

**Frontend:** Next.js (App Router) + TypeScript + Tailwind, generated via Claude Design, deployed on Vercel. Reads Supabase with `@supabase/supabase-js`.

**Database:** Supabase Postgres.

**Why this split:** Python is the better tool for clinical-text extraction and data work; the dashboard is naturally React/Vercel. They meet only at Postgres, so neither side compromises. Supabase Edge Functions are Deno/TS-only and can't host the Python pipeline — so the pipeline stays a standalone script, which is also the right shape for a multi-minute batch job.

**Deliberately deferred (mention, don't build):**

- _Supabase Queues (pgmq)_ — the production answer to rate limits: each fetch becomes a durable message, a 429 makes it reappear for exactly-once retry. Overkill at 300 patients; a retry loop is enough. Great talking point.
- _pg_cron_ — would schedule incremental `since` re-syncs. For the demo, run the script with a stored last-sync timestamp instead.

---

## 10. API Reference (condensed)

Base URL: `https://hackathon.prod.pulsefoundry.ai`

| Endpoint                               | Key                 | Returns                       |
| -------------------------------------- | ------------------- | ----------------------------- |
| `GET /pcc/patients?facility_id=101`    | —                   | patients (both IDs live here) |
| `GET /pcc/diagnoses?patient_id=FA-001` | string `patient_id` | ICD-10 diagnoses              |
| `GET /pcc/coverage?patient_id=FA-001`  | string `patient_id` | insurance coverage            |
| `GET /pcc/notes?patient_id=1`          | **integer** `id`    | free-text notes               |
| `GET /pcc/assessments?patient_id=1`    | **integer** `id`    | structured assessments        |

- **Two identifiers:** string `patient_id` (`FA-001`) for diagnoses/coverage; integer `id` (`1`) for notes/assessments. Both come from `/patients`. This is the #1 source of bugs.
- **Rate limit:** 30% chance of `429` per request; `Retry-After` is 1–5s. Retry every call.
- **`since`** param enables incremental fetch on patients (`last_modified_at`), notes (`effective_date`), assessments (`assessment_date`).
- Active Medicare Part B = `payer_code = MCB` (or `payer_type = "Medicare B"`) with `effective_to = null`.

---

## 11. Demo & Success Criteria

A 10-minute presentation: pipeline architecture walkthrough, a live demo of the triage table, and 3–4 example patients showing decisions.

Judged on: graceful API-failure handling, extraction accuracy across formats, clean/queryable schema, a presentation a non-technical biller could follow, and clear reasoning on ambiguous cases.

**The money demo moments:**

1. Expand an **Envive** patient → show the messy paragraph next to the four fields the LLM pulled out.
2. Show an **`auto_accept` + high audit-risk** patient (e.g. billable, but the wound is `NO_WOUND_ICD10` or the data is `LOW_CONFIDENCE_DOCUMENTATION`) → proves the two-axis design earns its keep.
3. Show a **sync-incomplete** patient routed to review, not rejected → proves you never treat a failed fetch as a clinical fact.

---

## 12. Build Order (suggested)

1. PCC client with retry → confirm you can pull one patient end-to-end (and **verify multi-visit data exists**).
2. Supabase schema + raw ingestion of all three facilities.
3. Structured + regex extraction; LLM extraction for Envive.
4. Eligibility engine, then audit-risk engine.
5. `eligibility_results` materialization.
6. Frontend: KPI cards → table → filters → modal.
7. Bonus: incremental `since` sync; polish.
