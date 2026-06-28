// Database row types. The raw tables mirror the API; `triage` is the single
// denormalized output table the dashboard reads (BUILD_PLAN §5). Expanded as
// later phases add columns; kept hand-written (no generated types) for clarity.

export type RoutingDecision = "auto_accept" | "flag_for_review" | "reject";
export type RejectReason =
  | "no_active_wound"
  | "not_medicare_b"
  | "extraction_unreliable";
export type RecoveryTier = "present" | "recovered" | "suggested" | "unavailable";
export type TriageStatus = "pending" | "reviewed" | "submitted" | "dismissed";

export interface FieldStatusEntry {
  value: string | number | boolean | null;
  source: string;
  tier: RecoveryTier;
}

export interface TriageRow {
  patient_id: string;
  first_name: string | null;
  last_name: string | null;
  facility_id: number | null;
  // extracted (final, post-recovery)
  wound_type: string | null;
  stage: string | null;
  location: string | null;
  laterality: string | null;
  length_cm: number | null;
  width_cm: number | null;
  depth_cm: number | null;
  drainage_present: boolean | null;
  drainage_type: string | null;
  drainage_amount: string | null;
  is_multi_wound: boolean | null;
  suggested_primary: string | null;
  // eligibility (the 3 criteria)
  has_active_wound: boolean | null;
  has_active_mcb: boolean | null;
  has_required_measures: boolean | null;
  has_wound_dx_code: boolean | null;
  // decision
  routing_decision: RoutingDecision | null;
  score: number | null;
  reason: string | null;
  reject_reason: RejectReason | null;
  flags: string[] | null;
  // per-field recovery + provenance (§8)
  field_status: Record<string, FieldStatusEntry> | null;
  // trust + worklist + narration
  confidence: number | null;
  status: TriageStatus;
  biller_inputs: Record<string, unknown> | null;
  narrative: string | null;
}
