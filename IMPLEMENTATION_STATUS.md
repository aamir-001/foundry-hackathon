# Implementation Status

Phase-by-phase build of the wound-care billing triage pipeline (BUILD_PLAN.md §16).
Each phase must pass its **Verify** gate before the next begins.

| Phase | Status | Verify gate | Evidence |
|---|---|---|---|
| 0a Housekeeping | ✅ done | data/ + reference/ split; dedicated repo | committed |
| 0 Setup | 🟡 partial | `select 1` + all tables exist; fixtures load 300 | fixtures ✅ 300; DB ⏳ pending creds + migration |
| 1 Ingestion | ⬜ todo | patient=300, children non-empty, retries>0, idempotent | — |
| 2 Extraction core | ⬜ todo | type+L+W=300/300, drainage=300/300, depth≥250/300 | — |
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

### To finish Phase 0 (needs your input)
1. Fill `.env.local` with Supabase URL + service-role/anon keys (Anthropic optional).
2. Run `supabase/migrations/0001_init.sql` in the Supabase SQL editor.
3. `npm run db:check` → expect `select 1 ok` + all 8 tables.
