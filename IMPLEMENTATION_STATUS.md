# Implementation Status

Phase-by-phase build of the wound-care billing triage pipeline (BUILD_PLAN.md §16).
Each phase must pass its **Verify** gate before the next begins.

| Phase | Status | Verify gate | Evidence |
|---|---|---|---|
| 0a Housekeeping | ✅ done | data/ + reference/ split; dedicated repo | committed |
| 0 Setup | ✅ done | `select 1` + all tables exist; fixtures load 300 | fixtures ✅ 300; `select 1` ✅; 8 tables ✅ |
| 1 Ingestion | ✅ done | patient=300, children non-empty, retries>0, idempotent | 300; 875/300/474/300; retries 506/533; idempotent ✓ |
| 2 Extraction core | ✅ done | type+L+W=300/300, drainage=300/300, depth≥250/300 | 300/300/300; depth 285; multi=64 (=oracle); 13 tests ✓ |
| 3 Recovery layer | ⬜ todo | every required field has a tier; no untiered null | — |
| 4 Registry + scoring | ⬜ todo | distribution = 48/92/160; reject = 155+5+0 | — |
| 5 Reasons (+narrative) | ⬜ todo | every row has reason; Summarize returns text | — |
| 6 Dashboard | ⬜ todo | lane counts match TRIAGE; drill-down renders | — |
| 7 Feedback loop | ⬜ todo | supply depth → field flips → row → auto_accept | — |
| 8 Bonuses | ⬜ todo | `since` sync fetches only changed patients | — |
| 9 Validation | ⬜ todo | oracle category recall printed; reconciles | — |

## Phase 0 — what's built

- **Next.js 15.5 (App Router) + TypeScript** scaffold; `next build` + `tsc --noEmit` both clean.
- **Repo layout** (BUILD_PLAN §17): `app/`, `lib/{pcc,supabase}`, `scripts/`, `supabase/migrations/`, `fixtures/`.
- **Supabase schema** — `supabase/migrations/0001_init.sql`: raw mirror tables (`patient`, `diagnosis`, `coverage`, `note`, `assessment`) + `triage` + `sync_state` + `pipeline_run`, with worklist index. Apply via the Supabase SQL editor.
- **Offline fixture loader** — `lib/fixtures.ts` + `scripts/check-fixtures.ts`. Verified: **300 bundles**, per-facility 120/90/90, payer mix MCB 145 / MCA 56 / MCD 36 / HMO 63 (matches PRD §2). Emits `fixtures/manifest.json` + `fixtures/samples/{FA-001,FA-002}.json`.
- **DB verify** — `scripts/db-check.ts` (`npm run db:check`) does `select 1` + asserts all 8 tables. Run after creds land in `.env.local` and the migration is applied.

### Phase 0 closed
Creds consolidated into `.env.local`; migration applied; `npm run db:check` green.

## Phase 1 — what's built

- **`lib/pcc/client.ts`** — `PccClient`: Bottleneck `maxConcurrent: 8`; 429 → sleep
  `Retry-After` + retry (≤8 attempts); 500/network → backoff + retry; 422 surfaced via
  `PccError`. Tracks `retries`/`rateLimited`/`serverErrors`/`calls` for `pipeline_run`.
- **`lib/pcc/ids.ts`** — the dual-key contract made explicit + assertable: `stringKey`
  (diagnoses/coverage) vs `intKey` (notes/assessments), plus key-match assertions on
  returned rows (catches a swapped-key bug).
- **`scripts/ingest.ts`** — fan out 4 child resources × 300 patients (1200 fetches),
  collect + `partial` sweep, idempotent chunked upserts (raw_json parsed to jsonb),
  `pipeline_run` start/finish with retry tally.
- **Live run evidence:** DB counts `patient 300 / diagnosis 875 / coverage 300 / note
  474 / assessment 300` — exactly the offline-fixture totals. 506 retries (all 429s,
  Retry-After honored), 0 unresolved. Second run: identical counts (idempotent).

> Note: `.env.local` gets re-touched by the IDE and sometimes drops `SUPABASE_URL` /
> `PCC_BASE_URL`; the code falls back to `NEXT_PUBLIC_SUPABASE_URL` and the default base
> URL, so this is non-blocking.

## Phase 2 — what's built (fully offline, no API/DB)

- **`lib/extract/`** — deterministic extraction over the two assessment sub-schemas
  + three note formats:
  - `structured.ts` — flatten `sections[].questions[]`; parse the 219 labeled
    assessments (13 fields) and detect the 81 narrative ones.
  - `narrative.ts` — free-text parser (narrative answer **and** notes): wound type,
    location, stage, laterality, drainage, multi-measurement.
  - `patterns.ts` — wound-type map (7 types incl. `SSI`), stage, laterality,
    measurement regex (**cm between dims**, separate `depth N cm`/`N cm deep`),
    location (`…to X`); strips `aprx`, dedupes `diabetic diabetic`.
  - `drainage.ts` — amount map incl. literal `light`/shorthand; type normalize.
  - `reconcile.ts` — per patient: prefer structured assessment, fill depth + gaps
    from the **primary note (latest by effective_date)** then siblings.
- **Verify (fixture):** type+L+W = **300/300**, drainage = **300/300**, depth =
  **285/300** (≥250; 15 true gaps like FA-001). Multi-wound = **64**, an exact match
  to the oracle (the oracle keys on the latest note only — replicated). 13 unit tests
  pass (`scripts/check-extract.ts`, `tests/extract.test.ts`).
