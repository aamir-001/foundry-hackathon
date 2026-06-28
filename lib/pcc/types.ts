// Raw API mirror types — the exact shape of the mock PCC API responses and the
// offline fixture (data/all_patient_data.json). Never lose source detail here.

export interface RawPatient {
  id: number; // internal integer id -> /pcc/notes, /pcc/assessments
  facility_id: number; // 101 | 102 | 103
  patient_id: string; // PCC string id (e.g. FA-001) -> /pcc/diagnoses, /pcc/coverage
  first_name: string | null;
  last_name: string | null;
  birth_date: string | null; // YYYY-MM-DD
  gender: string | null;
  primary_payer_code: string | null;
  last_modified_at: string | null;
  is_new_admission: boolean;
}

export interface RawDiagnosis {
  id: number;
  patient_id: string;
  icd10_code: string | null;
  icd10_description: string | null;
  clinical_status: string | null; // active | resolved | inactive
  onset_date: string | null;
  last_modified_at: string | null;
}

export interface RawCoverage {
  id: number;
  patient_id: string;
  payer_name: string | null;
  payer_code: string | null; // MCB | MCA | MCD | HMO — eligibility keys on THIS
  payer_type: string | null; // TRAP: collapses MCB/MCA/MCD -> "Medicare"; never use for eligibility
  effective_from: string | null;
  effective_to: string | null; // null => currently active
  last_modified_at: string | null;
}

export interface RawNote {
  id: number;
  patient_id: number; // integer id
  org_id: string | null;
  pcc_note_id: number | null;
  note_type: string | null; // 4 undocumented variants; format is NOT indicated by type
  effective_date: string | null;
  note_text: string | null; // free-text wound narrative — primary NLP target
  created_by: string | null;
  note_label: string | null;
  sync_version: number | null;
  is_current: boolean;
}

export interface RawAssessment {
  id: number;
  patient_id: number; // integer id
  org_id: string | null;
  pcc_assessment_id: number | null;
  assessment_type: string | null;
  status: string | null;
  assessment_date: string | null;
  completion_date: string | null;
  template_id: number | null;
  assessment_type_description: string | null;
  raw_json: string | null; // JSON-encoded string; structured (219) OR narrative (81) sub-schema
  sync_version: number | null;
  is_current: boolean;
}

// One patient's full record, as stored in the offline fixture.
export interface PatientBundle {
  patient: RawPatient;
  diagnoses: RawDiagnosis[];
  coverage: RawCoverage[];
  notes: RawNote[];
  assessments: RawAssessment[];
}
