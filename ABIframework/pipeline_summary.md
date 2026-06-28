# ABI Frameworks — Medicare Part B Wound Care Billing Pipeline
**Hackathon:** Pulse Foundry AI NYC x ABI Frameworks · June 28, 2026  
**Builder:** Richa Shiny

---

## Pipeline Design
*"Does it handle API failures gracefully? Is the data flow clear and maintainable?"*

- Built ATB congestion-aware retry (IEEE CCNC 2026) — 97.3% reduction in 429 errors vs plain exponential backoff
- Never treats a failed API call as ineligibility — fetch failures route to `flag_for_review`, not `reject`
- Payer-aware fast path — skips 310 unnecessary API calls for non-MCB patients
- 4 worker threads with jitter to avoid retry storms on shared quota
- Modular architecture: `api_client.py` → `ingest.py` → `extract.py` → `eligibility.py` → dashboard
- Incremental sync via `since` parameter — 99.5% fewer calls at 1M patient scale

---

## Extraction Accuracy
*"Are wound fields correctly pulled from both structured and free-text notes?"*

- Handles all 4 note formats: SOAP, Prose, Multi-wound, Envive
- Structured assessments parsed with dual-format handler — flat keys AND nested `sections → questions → answer`
- LLM fallback (Claude API) for Envive unstructured narratives where regex fails
- LLM used for multi-wound primary selection — picks most severe wound clinically
- Confidence scoring: structured=high, SOAP=high, Prose=medium, Envive+LLM=medium
- Extracts: `wound_type`, `stage`, `location`, `length_cm`, `width_cm`, `depth_cm`, `drainage`

---

## Schema & Data Modeling
*"Is the output well-structured and easy to query?"*

- One row per patient — 25 structured fields
- Aggregates 5 API endpoints into a single clean profile per patient
- Saved as both CSV and JSON for flexibility
- Fields include: wound data, coverage status, extraction metadata, trajectory metrics, compliance flags, routing decision
- `fetch_status` tracked per endpoint — full audit trail of what was fetched vs failed vs skipped

---

## Presentation
*"Can you explain your output to a non-technical audience? Is the routing logic easy to follow?"*

- Two dashboard views: Biller View (plain English work queue) and Technical View (charts, full table)
- Biller sees three buckets: **Submit Today** / **Review First** / **Do Not Bill** — no raw data needed
- Every routing decision has a plain-English reason a biller can act on immediately
- Compliance risk patients surfaced separately with specific action required
- Example reason: *"Wound is stalled across 5 visits with +2.3% area change. Medicare requires documented healing progress — review before billing."*

---

## Problem-Solving Approach
*"How did you handle ambiguous cases? What tradeoffs did you make?"*

- **Ambiguous API failures:** `flag_for_review` not `reject` — a rate-limited endpoint is a data availability problem, not proof of ineligibility
- **Envive notes:** LLM fallback only for Envive — not all notes, to avoid hallucination risk on structured data
- **2D measurements:** Real API returned length×width only, no depth. Removed depth from required fields rather than reject valid patients
- **Multi-wound notes:** LLM selects primary wound by clinical severity — not just first-mentioned
- **Both bonus features implemented:** LLM extraction AND incremental sync
- **9 compliance flags** from OIG enforcement actions, DOJ 2025 fraud takedown, RAC audit patterns — going beyond what was asked to protect the business

---

## Results

| Metric | Value |
|--------|-------|
| Total patients processed | 300 |
| Active Medicare Part B | 145 |
| Auto-accept (submit today) | 51 |
| Flag for review | 69 |
| Reject | 180 |
| Compliance risk flags | see dashboard |
| API calls made | 893 |
| API calls saved (optimization) | 310 |

---

## Compliance Flags — Beyond the Brief

9 audit risk patterns identified from OIG enforcement and DOJ 2025 healthcare fraud takedown:

1. No active Medicare Part B
2. API fetch failure on required endpoint
3. No wound type extractable
4. Envive format with missing fields
5. Missing required fields
6. No wound-related ICD-10 diagnosis — medical necessity unsupported
7. New admission with Stage 3/4 wound — facility-acquired pressure ulcer risk
8. Stalled or worsening wound across 3+ visits — Medicare requires healing progress
9. High visit frequency — 4+ assessments in 30 days (OIG fraud pattern)

> *"This patient has been billed for 6 consecutive visits with zero measurable wound reduction — that's an OIG audit waiting to happen. We flagged it before it became your problem."*

---

## API Optimization

| Strategy | How | Impact |
|----------|-----|--------|
| Payer-aware fast path | Skip notes/assessments for non-MCB patients | Saves 310 calls per run |
| ATB congestion-aware retry | Track consecutive 429s, scale wait + jitter | 97.3% fewer failed requests |
| Coverage/diagnoses cache | Store after first fetch, reuse for 7 days | Saves 600 calls per subsequent run |
| Incremental sync | `since` parameter — only fetch changed records | 99.5% reduction at scale |

---

## Architecture

```
PCC API (3 facilities, 300 patients)
         ↓
api_client.py   — ATB congestion-aware retry for HTTP 429
         ↓
ingest.py       — Parallel fetch, payer-aware fast path
         ↓
extract.py      — Regex + LLM extraction from all note formats
         ↓
eligibility.py  — 9-tier compliance flag system, routing decisions
         ↓
eligibility_output.csv  →  Streamlit dashboard
```
