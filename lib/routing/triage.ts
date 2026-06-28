import type { PatientBundle } from "@/lib/pcc/types";
import type { TriageRow } from "@/lib/supabase/types";
import { normalizeDrainageType } from "@/lib/extract/drainage";
import { flattenAssessment } from "@/lib/extract/structured";
import type { ScoreResult } from "@/lib/routing/rules";

// Map the scored result to a denormalized TRIAGE row (BUILD_PLAN §5). The
// `reason` here is a minimal placeholder; Phase 5 (reasons.ts) replaces it with
// the full deterministic templates.
export function buildTriageRow(bundle: PatientBundle, sr: ScoreResult, reason: string): TriageRow {
  const e = sr.extracted;
  const r = sr.recovery;
  const p = bundle.patient;
  const f = flattenAssessment(bundle.assessments[0]?.raw_json);

  const flags = [...sr.deductions.map((d) => d.code), ...sr.soft];

  return {
    patient_id: p.patient_id,
    first_name: p.first_name,
    last_name: p.last_name,
    facility_id: p.facility_id,
    wound_type: e.wound_type,
    stage: e.stage,
    location: e.location,
    laterality: e.laterality,
    length_cm: e.length_cm,
    width_cm: e.width_cm,
    depth_cm: e.depth_cm,
    drainage_present: e.drainage_present,
    drainage_type: e.drainage_type ?? normalizeDrainageType(f["Drainage Type"]),
    drainage_amount: e.drainage_amount,
    is_multi_wound: e.is_multi_wound,
    suggested_primary: r.suggested_primary,
    has_active_wound: sr.has_active_wound,
    has_active_mcb: sr.has_active_mcb,
    has_required_measures: sr.has_required_measures,
    has_wound_dx_code: sr.has_wound_dx_code,
    routing_decision: sr.routing_decision,
    score: sr.routing_decision === "reject" ? null : sr.score,
    reason,
    reject_reason: sr.reject_reason,
    flags,
    field_status: r.field_status,
    confidence: sr.routing_decision === "reject" ? null : sr.score / 100,
    status: "pending",
    biller_inputs: null,
    narrative: null,
  };
}
