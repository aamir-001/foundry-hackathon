import { getSupabaseAdmin } from "@/lib/supabase/client";
import type { TriageRow } from "@/lib/supabase/types";

export const FACILITY_NAME: Record<number, string> = {
  101: "Facility A",
  102: "Facility B",
  103: "Facility C",
};

export interface RawNoteRow {
  id: number;
  note_type: string | null;
  effective_date: string | null;
  note_text: string | null;
  created_by: string | null;
}
export interface RawAssessmentRow {
  id: number;
  assessment_type: string | null;
  assessment_date: string | null;
  raw_json: unknown;
}
export interface RawDiagnosisRow {
  icd10_code: string | null;
  icd10_description: string | null;
  clinical_status: string | null;
}
export interface RawCoverageRow {
  payer_code: string | null;
  payer_name: string | null;
  payer_type: string | null;
  effective_to: string | null;
}

/** All triage rows (score ascending → worst first for the review lane). */
export async function getAllTriage(): Promise<TriageRow[]> {
  const sb = getSupabaseAdmin();
  const { data, error } = await sb
    .from("triage")
    .select("*")
    .order("score", { ascending: true, nullsFirst: false });
  if (error) throw new Error(error.message);
  return (data ?? []) as TriageRow[];
}

export interface PatientDetail {
  triage: TriageRow | null;
  internalId: number | null;
  notes: RawNoteRow[];
  assessments: RawAssessmentRow[];
  diagnoses: RawDiagnosisRow[];
  coverage: RawCoverageRow[];
}

/** Triage row + the raw source records for the dual-source drill-down. */
export async function getPatientDetail(patientId: string): Promise<PatientDetail> {
  const sb = getSupabaseAdmin();
  const [triageRes, patientRes] = await Promise.all([
    sb.from("triage").select("*").eq("patient_id", patientId).maybeSingle(),
    sb.from("patient").select("id").eq("patient_id", patientId).maybeSingle(),
  ]);
  const internalId = (patientRes.data?.id as number | undefined) ?? null;

  const [notesRes, assessRes, dxRes, covRes] = await Promise.all([
    internalId != null
      ? sb
          .from("note")
          .select("id, note_type, effective_date, note_text, created_by")
          .eq("patient_id", internalId)
          .order("effective_date", { ascending: false })
      : Promise.resolve({ data: [] as RawNoteRow[] }),
    internalId != null
      ? sb.from("assessment").select("id, assessment_type, assessment_date, raw_json").eq("patient_id", internalId)
      : Promise.resolve({ data: [] as RawAssessmentRow[] }),
    sb.from("diagnosis").select("icd10_code, icd10_description, clinical_status").eq("patient_id", patientId),
    sb.from("coverage").select("payer_code, payer_name, payer_type, effective_to").eq("patient_id", patientId),
  ]);

  return {
    triage: (triageRes.data as TriageRow | null) ?? null,
    internalId,
    notes: (notesRes.data as RawNoteRow[]) ?? [],
    assessments: (assessRes.data as RawAssessmentRow[]) ?? [],
    diagnoses: (dxRes.data as RawDiagnosisRow[]) ?? [],
    coverage: (covRes.data as RawCoverageRow[]) ?? [],
  };
}

export interface QaStats {
  total: number;
  distribution: Record<string, number>;
  rejectBreakdown: Record<string, number>;
  structured: number;
  narrative: number;
  signals: { multi_wound: number; no_dx_code: number; depth_gap: number; laterality_conflict: number };
}

/** QA aggregates for the panel (decision mix, structured/narrative, signal counts). */
export async function getQaStats(rows: TriageRow[]): Promise<QaStats> {
  const sb = getSupabaseAdmin();
  const distribution: Record<string, number> = {};
  const rejectBreakdown: Record<string, number> = {};
  const signals = { multi_wound: 0, no_dx_code: 0, depth_gap: 0, laterality_conflict: 0 };
  // Count from per-patient columns + field_status (present for ALL 300 rows,
  // including rejects) — NOT `flags`, which only exist on scored rows.
  for (const r of rows) {
    const dec = r.routing_decision ?? "unknown";
    distribution[dec] = (distribution[dec] ?? 0) + 1;
    if (r.reject_reason) rejectBreakdown[r.reject_reason] = (rejectBreakdown[r.reject_reason] ?? 0) + 1;
    if (r.is_multi_wound) signals.multi_wound++;
    if (r.has_wound_dx_code === false) signals.no_dx_code++;
    if (r.depth_cm == null) signals.depth_gap++;
    if (r.field_status?.laterality?.tier === "suggested") signals.laterality_conflict++;
  }

  let structured = 0;
  let narrative = 0;
  const { data: assess } = await sb.from("assessment").select("raw_json");
  for (const a of assess ?? []) {
    if (JSON.stringify((a as { raw_json: unknown }).raw_json).includes("Wound narrative")) narrative++;
    else structured++;
  }

  return { total: rows.length, distribution, rejectBreakdown, structured, narrative, signals };
}

export interface PipelineRunRow {
  phase: string | null;
  patients: number | null;
  retries: number | null;
  started_at: string | null;
  finished_at: string | null;
}
export interface PipelineStats {
  runs: PipelineRunRow[];
  counts: Record<string, number>;
  watermark: string | null;
}

/** Ingestion evidence for the Pipeline page: run log (retries), raw row counts, watermark. */
export async function getPipelineStats(): Promise<PipelineStats> {
  const sb = getSupabaseAdmin();
  const { data: runs } = await sb
    .from("pipeline_run")
    .select("phase, patients, retries, started_at, finished_at")
    .order("started_at", { ascending: true });
  const tables = ["patient", "diagnosis", "coverage", "note", "assessment", "triage"];
  const counts: Record<string, number> = {};
  for (const tbl of tables) {
    const { count } = await sb.from(tbl).select("*", { count: "exact", head: true });
    counts[tbl] = count ?? 0;
  }
  const { data: ss } = await sb
    .from("sync_state")
    .select("watermark")
    .eq("resource", "patients")
    .maybeSingle();
  return { runs: (runs as PipelineRunRow[]) ?? [], counts, watermark: (ss?.watermark as string) ?? null };
}
