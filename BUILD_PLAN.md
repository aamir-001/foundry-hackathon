# Wound-Care Billing Triage — Build Plan (PRD v6, build-ready)

**ABI Frameworks Hackathon** · Post-acute wound-care eligibility pipeline
**Stack:** Next.js 15 (App Router) · Supabase (Postgres) · Bottleneck · Anthropic Haiku 4.5 (optional narration only)
**Priorities:** fewest LLM calls (0 required in pipeline) · one flat queryable table · least path of resistance · a defensible deterministic score · **self-provide missing info before sending the biller to the provider** · scalable to millions of patients.

> Hand this document to Claude Code and build **phase by phase** (§16). Each phase has a verification gate that must pass before the next begins.

**Verified against the authoritative `all_patient_data.json` + `outliers_report.txt`** (300 patients, 885 flags, all 300 affected).

**Derived output:** `48 auto_accept · 92 flag_for_review · 160 reject`. Reject carries three reasons (§3): R1 no active wound (0) · R2 not Medicare Part B (155) · **R3 reliable extraction not possible (5)** — the README's literal reject. Every row carries a plain-English reason and, for flags, a per-field recovery status.

---

## 1. Requirements coverage (README + API)

| Required | Where |
|---|---|
| Ingestion + rate-limit handling + queryable store | §6 (Phase A) |
| Extraction: type, stage, location, L/W/D, drainage | §7 |
| Eligibility table: fields + active-MCB + decision + **reason (accept/flag/reject)** | §5, §9 |
| Non-technical presentation | §15 |
| Visual dashboard / worklist | §11 |
| Bonus: LLM narrative · incremental `since` sync | §9, §13 |

Plus, beyond the brief: a **missing-info recovery layer** (§8), a **config-driven field registry** for scale (§10), and a **biller feedback loop** (§12).

---

## 2. Data reality (VERIFIED)

- **`payer_type` is a trap** — collapses MCB/MCA/MCD to `"Medicare"` (237). Eligibility uses `payer_code='MCB'` + `effective_to IS NULL`, never `payer_type`.
- **Payer mix:** 145 MCB · 56 MCA · 36 MCD · 63 HMO. Coverage is simple (0 multi-coverage, 0 expiry).
- **Assessments, two sub-schemas (both nested `sections[].questions[]`):** 219 **structured** (labeled `Location, Laterality, Wound Type, Stage, Length/Width/Depth (cm), Drainage Present/Type/Amount, tissue %`) + 81 **narrative** (one free-text answer, 2-D, no depth). Documented flat schema is never used.
- **Notes:** 4 undocumented `note_type`s; format is NOT indicated by type. 174/300 have two notes — merge across them for depth.
- **71 patients have no L-code wound dx** (only E11.62x diabetes-with-ulcer / metabolic); 35 are MCB. E11.62x implies an ulcer but isn't a codeable wound dx → coding review.
- **Cross-source conflicts (233):** laterality (note "Right" vs assessment "Left" — claim-integrity) and drainage presence/type.
- **Data-quality + statistical outliers (266):** tissue % impossible, garbled/truncated note locations, Envive "present…none", large wounds (area>29.6cm², depth>2.5cm — internally consistent, i.e. real).
- **Multi-wound:** 64 patients, 2 measurement sets → primary ambiguous.
- **Two parser must-haves:** measurement regex must allow "cm" between dims (`2.9 cm x 2.8`); location must parse from narrative ("…to Right hip"). With both, missing-L/W and missing-location → ~0.

**Deterministic extraction is fully viable; 0/300 benefit from an LLM.**

---

## 3. Decision model (the three criteria → reject / flag / accept)

The three Medicare Part B wound-billing criteria:
1. **Active wound** documented (pressure/diabetic/venous/arterial/SSI/abscess/burn).
2. **Active Medicare Part B** coverage.
3. **Documented measurements (L/W/D) + drainage level.**

```
REJECT — do not route to billing. Three reasons:
   R1  criterion 1 fails — no active wound documented anywhere                  (0)
   R2  criterion 2 fails — not active Medicare Part B                          (155)
   R3  reliable extraction is not possible — the wound cannot be characterized   (5)
        (no determinable wound type, or no length/width obtainable from any source)
   → reason names the reject reason.

FLAG   — eligible (criteria 1 & 2 met) AND the wound IS reliably extracted,
         but information is missing/ambiguous:
           a criterion-3 field missing (depth/drainage/...)  -> recoverable: §8
           OR secondary info missing (stage, codeable dx, primary wound) OR a conflict
         → the system attempts to self-provide each gap (§8); the biller reviews.

ACCEPT — all three criteria met, every required field present or recovered, no blocking conflict
         → reason explains why (templated; optional LLM narrative).
```

**Reject reconciles BOTH definitions.** The README defines reject as "reliable extraction is not possible"; you defined it as failing the eligibility criteria. Both are honored: R1/R2 are the eligibility gates (your definition), R3 is the README's literal definition. The line between R3 (reject) and flag is the key distinction: **flag = the wound is extracted, a detail is missing/obtainable; R3 = the wound itself can't be reliably extracted** (no type, no measurements) so there's nothing trustworthy to route. Criterion-3 *gaps* (e.g., missing depth on an otherwise-extracted wound) are flags-with-recovery, not R3, because the wound is characterized and the gap is obtainable.

---

## 4. Architecture (two-phase + recovery + feedback; scale-ready)

```
PHASE A — ingest (scripts/ingest.ts)
  Bottleneck (conc 8, retry 429 honoring Retry-After) -> upsert RAW tables; log retries
PHASE B — extract+score (scripts/extract.ts) [reads RAW, NO API, re-runnable]
  parse (structured 219 / narrative 81 / notes)
   -> RECOVERY LAYER (§8): fill gaps from other in-record sources; tag provenance+tier
   -> SCORE + ROUTE over the FIELD REGISTRY (§9,§10)
   -> reasons (accept/flag/reject) -> upsert TRIAGE (one row/patient)
  Next.js dashboard reads TRIAGE (lanes · worklist · drill-down w/ recovery candidates · QA)
   -> FEEDBACK LOOP (§12): biller enters a recovered value -> re-score that one patient
   -> optional Haiku narrative (on-demand or batch)
```

**Why this scales to millions (food-for-thought, addressed):**
- Two phases decouple the rate-limited pull from CPU-bound extraction; both shard horizontally by `facility_id` / id-range. Incremental `since` sync (§13) means steady-state only processes deltas.
- Extraction/scoring is **config-driven** (§10): new missing-field patterns at 3M scale = new registry rows, not new code.
- Recovery + feedback are per-patient and idempotent, so re-scoring one patient after the biller supplies a value is O(1), not a full re-run.
- TRIAGE is a single denormalized table → indexed queries stay flat as volume grows.

---

## 5. Supabase schema

Raw mirror: `patient, diagnosis, coverage, note, assessment(raw_json jsonb)` (mirror the API; never lose source).

```sql
create table triage (
  patient_id text primary key, first_name text, last_name text, facility_id int,
  -- extracted (final, post-recovery)
  wound_type text, stage text, location text, laterality text,
  length_cm numeric, width_cm numeric, depth_cm numeric,
  drainage_present bool, drainage_type text, drainage_amount text,
  is_multi_wound bool, suggested_primary text,
  -- eligibility (the 3 criteria)
  has_active_wound bool, has_active_mcb bool, has_required_measures bool, has_wound_dx_code bool,
  -- decision
  routing_decision text,            -- auto_accept | flag_for_review | reject
  score int,                        -- 100 − Σ hard deductions (eligible+extractable only)
  reason text,                      -- plain-English: accept / flag / reject rationale
  reject_reason text,               -- no_active_wound | not_medicare_b | extraction_unreliable (rejects only)
  flags text[],                     -- hard + soft signals
  -- per-field recovery + provenance (§8)
  field_status jsonb,               -- {depth:{value,source,tier}, stage:{...}, ...}
  -- trust + worklist + narration
  confidence numeric,               -- normalized score
  status text default 'pending',    -- pending | reviewed | submitted | dismissed
  biller_inputs jsonb,              -- values the biller supplied (feedback loop)
  narrative text                    -- optional LLM rationale (null until generated)
);
create table sync_state  (resource text primary key, watermark timestamptz);
create table pipeline_run(id uuid primary key default gen_random_uuid(),
  phase text, started_at timestamptz, finished_at timestamptz, patients int, retries int);
```

Biller query: `select * from triage where routing_decision='flag_for_review' and status='pending' order by score asc;`

---

## 6. Phase A — Ingestion + rate limiting

- Bottleneck `maxConcurrent: 8`; on 429 sleep `Retry-After`, retry ≤8 attempts, else mark `partial` + final sweep. (Default-low retry counts silently drop ~3 patients.) Retry 500s; surface 422s.
- Dual-key fan-out: `id` for notes/assessments, `patient_id` for diagnoses/coverage. Assert it.
- Idempotent upserts; tally `pipeline_run.retries`.

---

## 7. Phase B — Extraction (deterministic, source-aware)

Per patient, build the field set, preferring **structured assessment**, then reconciling with narrative + notes:
- **Structured (219):** read labeled answers directly. **Narrative (81) + notes:** regex (`LxWxD`, `LxW` with optional `cm` between dims, `N cm deep`, `Stage [1-4]/unstageable`, drainage amount, "…to <location>").
- **Wound type** keyword map covers all 7 README types: pressure ulcer · diabetic foot ulcer · venous (stasis) ulcer · arterial ulcer · **surgical site infection (also matches the abbreviation "SSI")** · abscess · burn.
- Strip `aprx`, dedupe `"diabetic diabetic"`.
- **Drainage amount** map (incl. literal `light`): none/no-drainage→none · light/min/minimal/slight/scant/small/trace→light · mod/moderate→moderate · heavy/large/copious→heavy.

---

## 8. Missing-info RECOVERY layer (self-provide before escalating)

For every field that's missing/ambiguous in its primary source, attempt to source it deterministically from elsewhere **in the record**, record provenance, and tag a tier:

| Tier | Meaning | Effect on score |
|---|---|---|
| `present` | found in primary source | counts as documented |
| `recovered` | filled from another in-record source (sibling note, structured assessment) | counts as documented (deduction removed) |
| `suggested` | inferred candidate needing human confirm (e.g., dx code from wound type+location; primary wound from dx match) | does NOT lift score; speeds review |
| `unavailable` | not in any source → "request from provider" | deduction stays → flag |

Recovery rules (priority order per field):
- **depth** → primary note 3-D → sibling note → structured `Depth` → else `unavailable`.
- **location** → structured `Location` → narrative "…to X" → note (de-garbled) → else `unavailable`.
- **stage** (pressure) → structured `Stage` (≠N/A) → note → else `unavailable`.
- **laterality** → on conflict, prefer structured + present both for confirm (`suggested`).
- **drainage amount** → note → structured `Drainage Amount` → else `unavailable`.
- **wound dx code** → if only E11.62x, derive a **candidate** L-code from documented type+location+stage → `suggested` (coder confirms; never auto-applied).
- **multi-wound primary** → pick by diagnosis match → `suggested_primary` (`suggested`).

`field_status` JSONB stores `{field:{value, source, tier}}` for every required+secondary field — this is what the drill-down renders ("depth 1.8cm — recovered from Weekly Assessment" / "depth — not in record, request from provider").

---

## 9. Scoring + routing engine

**Step 1 — reject gate (runs after extraction + recovery, §8):**
1. not criterion 1 (no active wound anywhere) → reject `reject_reason='no_active_wound'` (R1).
2. not criterion 2 (not active MCB) → reject `reject_reason='not_medicare_b'` (R2).
3. **wound not reliably extractable** — no determinable wound type, OR no length/width from any source after recovery → reject `reject_reason='extraction_unreliable'` (R3, the README's literal reject). This is the floor: below it there's nothing trustworthy to route. A merely-missing *detail* (depth/stage/drainage) on an otherwise-extracted wound is NOT R3 — it's a flag.

**Step 2 — score eligible patients:** `score = 100 − Σ(hard deductions)` over the registry (§10), counting `present`/`recovered` fields as documented; `suggested`/`unavailable` keep their deduction. Hard weights (each ≥12 → any one flags):

| 25 depth · 20 type/LW/no-dx-code/laterality-conflict · 18 drainage/drainage-presence-conflict · 15 stage(pressure)/multi-wound · 12 location |

Soft signals (size/depth outliers, drainage type-only conflict, garbled-recovered, tissue %) are **advisory badges, 0 weight** — the data shows they're real/non-billable/recovered, so deducting would wrongly flag ~30 clean patients.

**Step 3 — route:** `score ≥ 90 → auto_accept` (≡ zero hard issues) · `< 90 → flag_for_review`. The 90 cutoff is the encoding of "all required fields documented" (README), not a tuned dial; the score also orders the flag queue (worst first).

**Reasons (every row, deterministic templates — 0 LLM):**
- **reject:** names the reason — *"Rejected — no active Medicare Part B coverage (criterion 2)."* · *"Rejected — no active wound on record (criterion 1)."* · *"Rejected — reliable extraction not possible: wound type/measurements could not be determined from any source."*
- **flag:** `"Eligible (active wound + Medicare Part B). Review: {gap → recovery status}; ... Score {s}."` e.g. *"...depth recovered from Weekly Assessment (1.8cm); stage not in record — request from provider; multi-wound — suggested primary: sacral ulcer. Score 70."*
- **accept:** `"Accepted — all 3 criteria met: {wound_type} ({dx_code}), Medicare Part B, measurements {L×W×D} + {drainage} drainage; no conflicts. Score 100."`

**Optional LLM narrative (the accept-reason idea):** a Haiku pass turns the structured reason + score into a natural sentence and writes `narrative`. Two modes: on-demand "Summarize" button (default, ~0 calls) or `extract --narratives` batch (~300 cheap Haiku calls) if you want every row pre-narrated. Deterministic `reason` always exists regardless.

---

## 10. Field registry (config-driven — the scalability lever)

Extraction, recovery, and scoring all iterate ONE registry, so new missing-field patterns at scale need a row, not a rewrite:

```ts
type FieldDef = {
  field: string; criterion: 1|2|3|null; required: boolean; weight: number;
  sources: string[];          // ordered recovery sources
  obtainable: boolean;        // can a provider supply it? -> 'unavailable' vs hard-block
  soft?: boolean;             // advisory only (weight ignored)
};
// e.g. { field:'depth_cm', criterion:3, required:true, weight:25,
//        sources:['note.3d','sibling_note','assessment.depth'], obtainable:true }
```

Adding "exudate odor" or a new conflict type for 3M patients = append a `FieldDef`. The score, recovery, reasons, and QA panel all pick it up automatically.

---

## 11. Dashboard (reads `triage`)

- **Three lanes + counts:** Act on (48) · Review (92) · Skip (160). Reject rows group by reason (not-MCB / no-wound / extraction-unreliable).
- **Worklist:** `status` per row (pending→reviewed→submitted/dismissed); review lane sorted by **score ascending**.
- **Drill-down:** extracted fields beside BOTH sources, conflicts highlighted; **per-field recovery status** from `field_status` (present / recovered-from-X / suggested / request-from-provider); the score breakdown; advisory badges. **Reject rows show the failed criterion.**
- **Feedback:** inline inputs for `unavailable` fields → §12.
- **QA panel:** extraction coverage, structured/narrative mix (219/81), conflict + recovery counts, decision distribution, oracle recall (§14).
- **Summarize button:** Haiku narrative on demand.

---

## 12. Feedback loop (biller supplies missing info → re-score)

A flagged row exposes inputs for each `unavailable`/`suggested` field. On submit:
1. Write the value into `biller_inputs`.
2. Re-run §8–§9 **for that one patient** (deterministic, instant).
3. The field flips to `present`, score recomputes, and the row may move to `auto_accept` (or the biller dismisses/submits). All idempotent.

This is the "biller calls the provider, gets the value, decides" workflow — closed in-app, and O(1) per patient at any scale.

---

## 13. Bonuses

- **Incremental sync:** per-endpoint watermarks (patients=`last_modified_at`, notes=`effective_date`, assessments=`assessment_date`) in `sync_state`; `since` + idempotent upserts; "Sync" re-runs Phase A on deltas, Phase B on changed patients only.
- **LLM narrative:** §9 (on-demand or batch).

---

## 14. Validation

- Use `outliers_report.txt` as a near-ground-truth **oracle**: reproduce its category counts (no-dx 71, multi-wound 64, conflicts 233, etc.); report per-category recall.
- Range/plausibility sanity; % fields with provenance. Feeds the QA panel.

---

## 15. Presentation (10 min)

1. Architecture — "deterministic, auditable, 0 required LLM calls; recovery layer self-provides missing data."
2. Rate limiting — `pipeline_run.retries` ("~430 retries, 0 failures"); don't run full ingest live.
3. Worklist — "act on 48, review 92, skip 160"; review lane by score; reject lane grouped by reason.
4. Six patients, reading the reason aloud: clean accept (100) · reject-R2 (not Medicare Part B) · reject-R3 (wound not extractable) · depth **recovered** from assessment · multi-wound (suggested primary) · depth **unavailable → request from provider**. Then demo the feedback loop: type the depth → row jumps to accept. Click Summarize.
5. QA panel + "validated category recall against the outliers oracle." Mention 3M-scale design.

---

## 16. PHASED BUILD PLAN (each phase ends with a verification gate)

> Build in order. Do not start a phase until the previous phase's **Verify** box is checked.

### Phase 0 — Setup
- [ ] Next.js 15 app + Supabase project + env (Supabase URL/key, ANTHROPIC_API_KEY).
- [ ] Run schema migrations (§5).
- [ ] Parse `all_patient_data.json` → `/fixtures` for offline tests.
- **Verify:** `select 1` over Supabase succeeds; all tables exist; fixtures load 300 records.

### Phase 1 — Ingestion (Phase A)
- [ ] `lib/pcc/client.ts`: fetch + Bottleneck retry honoring `Retry-After` (≤8), 500-retry, 422-surface.
- [ ] `scripts/ingest.ts`: dual-key fan-out → upsert raw tables; `partial` sweep; log retries.
- **Verify:** `patient`=300, and diagnoses/coverage/notes/assessments non-empty for all; `pipeline_run.retries>0`; re-running ingest changes no row counts (idempotent).

### Phase 2 — Extraction core (Phase B, no recovery yet)
- [ ] `lib/extract/*`: structured-assessment field parse + narrative/note regex (with the two parser must-haves).
- **Verify (against fixture):** type+L+W = 300/300; drainage = 300/300; depth ≥ 250/300; unit-tests pass for FA-001 (narrative, true depth gap) and FA-002 (structured, multi-wound, stage N/A).

### Phase 3 — Recovery layer (§8)
- [ ] `lib/extract/recover.ts`: per-field source cascade; write `field_status{value,source,tier}`.
- [ ] Suggested dx-code + suggested primary-wound generators.
- **Verify:** every required field has a tier; depth `recovered` count + `unavailable` count sum correctly; no field is silently null without a tier.

### Phase 4 — Field registry + scoring + routing (§9,§10)
- [ ] `lib/routing/registry.ts` + `rules.ts`: criteria gate, score over registry, route at 90.
- **Verify:** distribution = **48 / 92 / 160**; reject breakdown = 155 not-MCB + 5 extraction-unreliable + 0 no-wound; every reject has a `reject_reason`; every flag score <90; every accept score =100; re-run is identical (deterministic).

### Phase 5 — Reasons (+ optional narrative)
- [ ] Deterministic `reason` for accept / flag / reject (§9), including per-field recovery status in flag reasons.
- [ ] `/api/summarize` (Haiku) for on-demand `narrative`; optional `--narratives` batch flag.
- **Verify:** every TRIAGE row has a non-null `reason`; reject reasons name the criterion; accept reasons list the 3 criteria; Summarize returns text for a sample row.

### Phase 6 — Dashboard
- [ ] Three lanes + counts; filterable table; score-sorted review lane.
- [ ] Drill-down: dual-source view, conflicts, `field_status` recovery rendering, reject criterion.
- [ ] QA panel.
- **Verify:** lane counts match TRIAGE; opening any patient shows fields + sources + recovery tiers + reason; QA numbers match SQL aggregates.

### Phase 7 — Feedback loop (§12)
- [ ] Inputs for `unavailable`/`suggested` fields → `/api/feedback` → write `biller_inputs` → re-score that patient.
- [ ] `status` transitions (pending→reviewed→submitted/dismissed).
- **Verify:** supplying a missing depth flips the field to `present`, recomputes score, and moves the row to `auto_accept`; refresh persists the change.

### Phase 8 — Bonuses
- [ ] Incremental sync (`since` + watermarks); "Sync" button.
- [ ] Batch narratives (if enabled).
- **Verify:** a second sync with a recent `since` fetches only changed patients and updates no others.

### Phase 9 — Validation + polish
- [ ] Oracle recall report vs `outliers_report.txt`; sample audit of ~20 across formats.
- **Verify:** category recall printed; numbers reconcile with §2/§9; 10-min walkthrough rehearsed end-to-end.

---

## 17. Repo structure

```
/app            Next.js dashboard + /api/{ingest,extract,summarize,feedback,status,sync}
/lib/pcc        client.ts (Bottleneck), ids.ts
/lib/extract    structured.ts, narrative.ts, drainage.ts, reconcile.ts, recover.ts
/lib/routing    registry.ts, rules.ts, reasons.ts
/lib/supabase   client.ts, types.ts
/scripts        ingest.ts, extract.ts
/supabase/migrations, /fixtures, /tests
```

## 18. Scope cuts / interpretations (for judges)

- **0 required LLM calls** — extraction/scoring/reasons are deterministic; LLM narration is optional.
- **Reject carries three reasons, reconciling both definitions:** R1 no active wound + R2 not Medicare Part B (eligibility gates) + R3 "reliable extraction not possible" (the README's literal reject — wound uncharacterizable). Criterion-3 *gaps* (missing depth/stage/drainage on an extracted wound) are flag-with-recovery, not reject, because the wound is characterized and the value is obtainable.
- **E11.62x alone = no codeable wound dx → suggested L-code for coder review**, not auto-bill.
- Soft signals advisory (data-justified); `payer_type` ignored; no dual-coverage/expiry logic (data has none).

## 19. Scalability to ~3M patients (food-for-thought, addressed)

- Config-driven field registry (§10) absorbs new missing-field varieties without code changes.
- Recovery tiers + feedback loop generalize: any field, any source, any provider-obtainable gap.
- Two-phase + incremental `since` + horizontal sharding by facility/id-range keep steady-state cost on deltas only.
- Single denormalized TRIAGE table with indexes on `(routing_decision,status,score)` keeps biller queries flat.
- Per-patient re-scoring is O(1), so feedback at scale never triggers full recomputation.

## 20. Inngest alternative

Swap `scripts/ingest.ts` for an Inngest `patient/process` function (`retries:8`, `RetryAfterError`, conc 8) only if you want a live visual run timeline for the demo. Same logic, more wiring.
