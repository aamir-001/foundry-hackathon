# OuchLess — Wound-Care Billing Triage Pipeline

A walkthrough of how the system works, mapped to each requirement, the bonuses, and
the judging criteria. Everything below is implemented and reproducible from this repo.

---

## TL;DR — the data flow

```
                    ┌─────────────────────────── PHASE A: INGEST (live API) ──────────────────────────┐
  Mock PCC API ──▶  lib/pcc/client.ts            scripts/ingest.ts                    Supabase (Postgres)
  (30% 429s)        PccClient                     dual-key fan-out, partial sweep,     RAW mirror tables:
                    · Bottleneck conc 8            idempotent upserts, retry tally      patient(300) diagnosis(875)
                    · 429→Retry-After retry ≤8                                          coverage(300) note(474)
                    · 500 backoff, 422 surface                                          assessment(300) + pipeline_run
                    └───────────────────────────────────────────────────────────────────────────────┘

                    ┌────────────── PHASE B: EXTRACT + SCORE (offline, deterministic, 0 LLM) ─────────┐
  RAW / fixture ─▶  lib/extract/*                 lib/extract/recover.ts    lib/routing/*            triage
                    parse structured(219)/         per-field provenance      registry → score → route  (one row /
                    narrative(81)/3 note formats    + tiers + suggestions     reasons (plain English)   patient)
                    └───────────────────────────────────────────────────────────────────────────────┘

  Next.js dashboard (OuchLess) reads `triage`  ─▶  3 lanes · queue · drill-down · CSV · QA
       │
       ├─ Feedback loop:  biller supplies a value  → /api/feedback re-scores ONE patient (O(1))
       ├─ Narrative (opt): Haiku 4.5 "Summarize"   → /api/summarize  (0 LLM calls in the pipeline)
       └─ Incremental sync: `since` + watermark    → /api/sync re-runs Phase A on deltas only
```

**Two phases on purpose.** The rate-limited network pull (Phase A) is decoupled from the
CPU-bound, deterministic extraction/scoring (Phase B). Phase B reads the stored raw data (or the
offline fixture) and can be re-run infinitely without touching the API. This is the single most
important design decision: it makes extraction fast, testable, idempotent, and shardable.

---

## 1 · Data ingestion pipeline

**Goal:** fetch patients, diagnoses, coverage, notes, assessments; handle rate limiting; store somewhere queryable.

**Code:** `lib/pcc/client.ts` · `lib/pcc/ids.ts` · `scripts/ingest.ts` · schema in `supabase/migrations/0001_init.sql`
**Run:** `npm run ingest`

### How it works
- **`PccClient` (`lib/pcc/client.ts`)** wraps every call in a **Bottleneck** limiter (`maxConcurrent: 8`).
  Each request is retried with this policy:
  - **429 Too Many Requests** → sleep the `Retry-After` header value, retry (**≤ 8 attempts**).
  - **500** → exponential-ish backoff, retry.
  - **422** → surfaced as a `PccError` (never silently retried — it means a bad request).
  - Network error → backoff + retry.
  - It tallies `retries / rateLimited / serverErrors / calls` for the audit log.
- **Dual-key fan-out (`lib/pcc/ids.ts`) — a deliberate trap the API sets:**
  `/diagnoses` and `/coverage` are keyed by the **string** `patient_id` (e.g. `FA-001`);
  `/notes` and `/assessments` by the **integer** `id`. `stringKey()` / `intKey()` make the
  contract explicit, and `assertStringKeyMatch` / `assertIntKeyMatch` verify the rows that come
  back carry the key we queried with (catches a swapped-key bug immediately).
- **`scripts/ingest.ts`** fetches 3 facilities → 300 patients, then fans out **1,200 child
  fetches** (300 × diagnoses/coverage/notes/assessments) through the limiter. Failures are
  collected and **swept** once more (`partial` recovery). Writes are **idempotent chunked upserts**
  keyed on each row's `id`, and assessment `raw_json` (a JSON string) is parsed into a `jsonb`
  column. The run is logged to `pipeline_run` (phase, patients, retries, timestamps).

### Store: Supabase Postgres, raw mirror tables
`patient · diagnosis · coverage · note · assessment` mirror the API 1:1 (never lose source).
Verified counts: **patient 300 · diagnosis 875 · coverage 300 · note 474 · assessment 300** — and
these match the offline fixture exactly, confirming the pull is complete.

### Failure handling — evidence
A live run logged **~506–533 retries** (all 429s, `Retry-After` honored) with **0 patients dropped**,
and re-running ingest leaves row counts **identical** (idempotent). See it in the UI on the
**Pipeline** page (`/pipeline`), which reads `pipeline_run`.

---

## 2 · Wound data extraction

**Goal:** from each note + assessment, extract wound type, stage (pressure ulcers), location, L/W/D (cm), drainage (none/light/moderate/heavy).

**Code:** `lib/extract/{patterns,drainage,structured,narrative,reconcile,recover}.ts`
**Run / verify:** `npm run extract:check` · `npm test` (unit tests) · `npm run recover:check`

### The data is messy on purpose — two assessment sub-schemas + three note formats
- **Assessments:** 219 **structured** (labeled `sections[].questions[]`: Wound Type, Stage,
  Length/Width/Depth (cm), Drainage Present/Type/Amount, tissue %) + 81 **narrative** (one
  free-text answer, 2-D, no depth). `structured.ts` flattens and parses both.
- **Notes:** three free-text formats — **Envive** (`Measures 2.9 cm x 2.8 cm`), **prose-measures**
  (`measures aprx 5.9 x 4.5cm, depth 1.8cm`), **prose-Meas** (`Meas 8.0x3.5x0.2cm`). `note_type`
  does **not** indicate format, so `narrative.ts` parses all of them the same way.

### The parser must-haves (where naive extraction fails)
`patterns.ts` handles the cases that quietly break a regex:
- **`cm` between dimensions:** `2.9 cm x 2.8` and `4.3 cm x 1.8 cm x 0.3 cm` both parse.
- **Separate depth tokens:** `depth 1.8cm` and `0.9cm deep` are attached to the right measurement.
- **Location from narrative:** `…to Right hip` and `Pressure Ulcer Left buttock measures …`.
- **Cleanup:** strips `aprx`, dedupes `diabetic diabetic`.
- **Wound-type map** covers all 7 README types (pressure / diabetic foot / venous / arterial /
  surgical-site-infection incl. the abbreviation `SSI` / abscess / burn).
- **Drainage map** (`drainage.ts`) normalizes to `none/light/moderate/heavy`, including the literal
  `light` and shorthand (`min`, `slight`, `mod`, `copious`, …).

### Reconciliation + recovery (handling missing/conflicting data)
- `reconcile.ts` prefers the **structured assessment**, then fills gaps from the **primary note
  (latest by `effective_date`)**, then sibling notes. Depth, which is often missing from 2-D
  narratives, is recovered from a note's 3-D measurement.
- `recover.ts` (the recovery layer) tags **every required field** with a provenance tier:
  `present` (in primary source) · `recovered` (from another in-record source) · `suggested`
  (an inferred candidate, e.g. a derived L-code, that needs human confirm) · `unavailable`
  (request from provider). This is what powers the per-field display in the drill-down.

### Accuracy — verified coverage
`type + L + W = 300/300` · `drainage = 300/300` · `depth = 285/300` (the other 15 are genuine
gaps — no depth documented anywhere) · multi-wound detected = **64**, an exact match to the oracle
report's count. Unit tests pin the two hardest patients (FA-001 narrative depth-gap; FA-002
structured multi-wound, stage N/A).

---

## 3 · Eligibility output table

**Goal:** one row per patient — extracted fields + active Medicare Part B + routing decision + plain-English reason.

**Code:** `lib/routing/{registry,rules,reasons,triage}.ts` · table `triage` (`supabase/migrations/0001_init.sql`)
**Run:** `npm run extract` (writes all 300 rows) · view at `/eligibility` (filter + CSV export)

### Eligibility (the silent-bug trap)
Active Medicare Part B = `payer_code = 'MCB'` **AND** `effective_to IS NULL`. We never use
`payer_type`, which the API collapses to `"Medicare"` for MCB/MCA/MCD alike — using it would
mis-classify 92 patients. Result: **145 active-MCB**, **155 not**.

### The decision model — three criteria, three buckets
1. Active wound documented · 2. Active Medicare Part B · 3. Measurements (L/W/D) + drainage.

```
reject gate (rules.ts):
  R1 no active wound documented        → reject_reason = no_active_wound        (0)
  R2 not active Medicare Part B        → reject_reason = not_medicare_b         (155)
  R3 wound not reliably extractable    → reject_reason = extraction_unreliable  (0 — see note)
  otherwise: score = 100 − Σ hard deductions over the field registry; route at 90:
    score ≥ 90 → auto_accept   ·   score < 90 → flag_for_review
```

- **Config-driven scoring (`registry.ts`)** — extraction, recovery, and scoring all iterate ONE
  `FieldDef[]` registry. Hard weights (each ≥ 12, so any single gap drops below the 90 cutoff):
  depth 25 · type/measures/no-dx-code/laterality-conflict 20 · drainage/drainage-presence-conflict
  18 · stage(pressure)/multi-wound 15 · location 12. `present`/`recovered` count as documented;
  `suggested`/`unavailable` keep the deduction. **Soft** signals (size/depth outliers, tissue %,
  drainage-type-only conflict) are advisory badges at **0 weight** — the data shows they're real or
  non-billable, so deducting would wrongly flag ~30 clean patients.
- **Plain-English reason (`reasons.ts`)** — deterministic templates, one per row, no LLM:
  - *accept:* "Accepted — all 3 criteria met: pressure ulcer (L89.143), Medicare Part B,
    measurements 2.9×2.8×1.8cm + heavy drainage; no conflicts. Score 100."
  - *flag:* "Eligible (active wound + Medicare Part B). Review: depth not in record — request from
    provider. Score 75."
  - *reject:* "Rejected — no active Medicare Part B coverage (criterion 2)."

### The output table
`triage` is **one denormalized row per patient**: the extracted fields, the three eligibility
booleans (`has_active_wound / has_active_mcb / has_required_measures / has_wound_dx_code`),
`routing_decision`, `score`, `reason`, `reject_reason`, a `field_status` JSONB with per-field
provenance, plus worklist state (`status`, `biller_inputs`, `narrative`). Indexed on
`(routing_decision, status, score)` so the biller query stays flat at scale.

**Distribution: 56 auto_accept · 89 flag_for_review · 155 reject (all 155 = not-MCB).**

> **Honest note on the target.** A pre-set target of 48/92/160 (with 5 "extraction-unreliable"
> rejects) is **not reproducible from this data**: every patient yields a parseable wound type +
> L/W (`type+L+W = 300/300`), so the unreliable bucket is genuinely **0, not 5**; and our note
> parser recovers more depths than the reference oracle's. We ship the **data-correct** numbers and
> surface the discrepancy (in the UI and here) rather than hard-code a target — the brief explicitly
> values reasoning over a perfect score.

---

## 4 · Presentation — for a non-technical biller

**Code:** `/presentation` page · `components/TriageDashboard.tsx`

A biller never reads raw clinical data. They see **three lanes**:

| Lane | Count | Means |
|---|---|---|
| **Act on** (auto_accept) | 56 | All 3 criteria met — submit the claim |
| **Review** (flag_for_review) | 89 | Eligible, one gap/conflict to confirm — sorted worst-first |
| **Skip** (reject) | 155 | Not billable — grouped by why (155 not Medicare Part B) |

Every row carries a **plain-English reason** and a confidence signal. The Review lane is sorted
worst-score-first, so the biller works top-down. Opening a patient shows the extracted fields with
their **recovery tier** (present / recovered-from-X / request-from-provider), the **assessment vs.
notes side by side** with the failed criterion highlighted, and three actions: **Accept & bill /
Mark reviewed / Dismiss**. When a value is missing, the biller types it in and the row **re-scores
instantly** — the "call the provider, get the number, decide" loop, closed in-app.

The `/presentation` page is a guided script: the 3 lanes, the 3 criteria, and five demo patients to
click through (clean accept · reject-not-MCB · depth-recovered · multi-wound · depth-missing →
supply it → jumps to accept).

---

## 5 · Visual output (dashboard)

**Code:** Next.js 15 App Router. `app/page.tsx` → `components/TriageDashboard.tsx`,
`PatientModal.tsx`, `AppShell.tsx`; pages `/eligibility /extraction /pipeline /presentation
/patient/[id]`.

A biller sees decisions **at a glance**: color-coded lanes (green/amber/red), KPI cards (in-queue,
auto-accept, flag, reject, revenue-at-stake), a triage funnel, "why cases get flagged", and a
by-facility mix — then a **sortable, filterable queue** (search, wound type, facility, confidence)
with per-row and **bulk** status actions, a click-through **patient modal**, dark-mode and
colorblind-safe palette toggles, and **CSV export**. Every page reads live from the `triage` table.

---

## Bonus

- **LLM narrative (optional, on-demand):** `lib/llm/summarize.ts` calls **Anthropic Haiku 4.5**
  to turn the deterministic `reason` into a natural sentence; `/api/summarize` persists it; the
  drill-down "Summarize" button triggers it; `npm run narrate` batches it. **The pipeline itself
  makes 0 LLM calls** — extraction/scoring/reasons are fully deterministic and auditable.
- **Incremental sync (`since`):** `lib/pipeline/sync.ts` · `scripts/sync.ts` · `/api/sync` + a
  dashboard **Sync** button. Per-resource watermarks live in `sync_state`. A sync pulls only
  patients changed since the watermark, re-ingests + re-scores **just those**, and bumps the
  watermark. Verified: `since = 2026-05-17T16:50` fetched **7 of 300** (293 untouched); a sync with
  a more-recent `since` fetched **0** and updated none.

---

## Judging criteria — how each is addressed

| Area | Where it shows up |
|---|---|
| **Pipeline design / failure handling** | Two-phase decoupling; 429 `Retry-After` retry ≤8, 500 backoff, 422 surfaced; `partial` sweep; idempotent chunked upserts; `pipeline_run` audit (506 retries, 0 dropped, idempotent re-run). Clear data flow: `client → ingest → raw tables → extract/recover/score → triage → UI`. |
| **Extraction accuracy** | Both structured **and** free-text: 2 assessment sub-schemas + 3 note formats, with the parser must-haves (cm between dims, separate depth, location-from-narrative). Cross-source recovery fills depth from a sibling note. `type+L+W = 300/300`; multi-wound 64 = oracle. Unit tests on the two hardest patients. |
| **Schema & data modeling** | Raw mirror tables preserve source; one **denormalized `triage`** table is the queryable output, indexed on `(routing_decision, status, score)`; `field_status` JSONB carries per-field provenance; config-driven `FieldDef` registry so new fields = a row, not code. |
| **Presentation** | 3 lanes + counts a non-technical biller reads instantly; a plain-English reason on **every** row; the routing logic is 3 criteria → reject-gate → score-at-90, explained on `/presentation`. |
| **Problem-solving / tradeoffs** | The `payer_type` trap (use `payer_code='MCB'` + `effective_to IS NULL`); the dual-key fan-out; multi-wound detected from the **latest note only** (matches the oracle's 64); soft signals kept advisory (0 weight) because the data shows they're real; **recover-before-escalate** (fill a gap from another in-record source before sending the biller to the provider); and the **data-correct 56/89/155 vs. the 48/92/160 target — surfaced, not faked.** |

---

## Run it yourself

```bash
# 0. env: put Supabase + (optional) Anthropic keys in .env.local; apply supabase/migrations/0001_init.sql
npm install

# 1. ingest (the only step that hits the live API; ~5 min with 429 backoffs)
npm run ingest

# 2. extract → score → route → write the triage table (offline, deterministic, re-runnable)
npm run extract

# 3. dashboard
npm run dev          # → http://localhost:3000

# checks / bonuses
npm run extract:check   # extraction coverage (type+L+W 300/300, drainage 300/300, depth 285/300)
npm run recover:check   # every field tiered; depth recovered/unavailable split
npm test                # unit tests (FA-001, FA-002, parser must-haves)
npm run sync -- --since=2026-05-17T16:50:00   # incremental sync (fetches the delta only)
npm run narrate -- --limit=5                  # batch Haiku narratives
```

*Phase B is developed entirely offline against `data/all_patient_data.json` (the 300-patient
fixture) and validated against `data/outliers_report.txt` (a near-ground-truth oracle of the data's
known issues).*
