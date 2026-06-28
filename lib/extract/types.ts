export type DrainageAmount = "none" | "light" | "moderate" | "heavy";
export type AssessmentFormat = "structured" | "narrative";

// Recovery provenance (BUILD_PLAN §8):
//   present     — found in the field's primary source
//   recovered   — filled from another in-record source (counts as documented)
//   suggested   — inferred candidate needing human confirm (does NOT lift score)
//   unavailable — not in any source → "request from provider"
export type RecoveryTier = "present" | "recovered" | "suggested" | "unavailable";

export interface FieldStatus {
  value: string | number | boolean | null;
  source: string;
  tier: RecoveryTier;
}

export interface RecoveryResult {
  extracted: Extracted;
  field_status: Record<string, FieldStatus>;
  has_wound_dx_code: boolean;
  suggested_dx_code: string | null;
  suggested_primary: string | null;
  laterality_conflict: boolean;
  drainage_presence_conflict: boolean;
}

/** One wound mentioned in a source (assessment answer or a note). */
export interface WoundMention {
  wound_type: string | null;
  location: string | null;
  laterality: string | null;
  stage: string | null;
  length_cm: number | null;
  width_cm: number | null;
  depth_cm: number | null;
}

/** Fields parsed from a single source (the assessment, or one note). */
export interface ParsedSource {
  wounds: WoundMention[]; // ≥1; >1 ⇒ multi-wound signal
  drainage_present: boolean | null;
  drainage_type: string | null;
  drainage_amount: DrainageAmount | null;
}

/** The reconciled, per-patient extraction (Phase 2 — pre-recovery-tiers). */
export interface Extracted {
  patient_id: string;
  wound_type: string | null;
  stage: string | null;
  location: string | null;
  laterality: string | null;
  length_cm: number | null;
  width_cm: number | null;
  depth_cm: number | null;
  drainage_present: boolean | null;
  drainage_type: string | null;
  drainage_amount: DrainageAmount | null;
  is_multi_wound: boolean;
  wounds: WoundMention[]; // all detected wounds, primary first
  assessment_format: AssessmentFormat;
}
