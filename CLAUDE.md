BUILD DISCIPLINE:

- Work strictly phase by phase (BUILD_PLAN §16). Finish each phase's **Verify**
  gate, SHOW me the evidence it passes, then STOP and wait for "proceed". Do not
  build ahead. Commit after each verified phase.
- Develop extraction/scoring offline against /data/all_patient_data.json; only
  Phase 1 (ingestion) hits the live API.
- If reality contradicts the PRD, STOP and tell me — never silently deviate.

NON-NEGOTIABLE CORRECTNESS (the silent-bug traps; the PRD explains each):

- Eligibility uses payer_code='MCB' + effective_to IS NULL. NEVER payer_type.
- Dual-key fan-out: string patient_id for /diagnoses & /coverage; integer id for
  /notes & /assessments.
- 30% of calls return 429 — retry honoring Retry-After, >=8 attempts; mark
  unresolved patients 'partial' and sweep. Retry 500s.
- Assessments have TWO sub-schemas: 219 structured labeled-field + 81 free-text
  narrative. Parse both.
- Measurement regex must allow "cm" between dims (2.9 cm x 2.8); parse location
  from narrative ("...to Right hip"); drainage map must include literal "light".
- Extraction is 100% deterministic — NO LLM in the pipeline. Haiku is only the
  optional on-demand "Summarize" narrative.
- Three reject reasons; routing must reproduce 48 auto / 92 flag / 160 reject on
  the fixture (reject = 155 not-MCB + 5 extraction-unreliable).
