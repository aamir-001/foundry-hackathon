import type { RawPatient } from "@/lib/pcc/types";

// The dual-key contract (BUILD_PLAN §6, CLAUDE.md — a silent-bug trap):
//   string patient_id  -> /diagnoses, /coverage
//   integer id         -> /notes, /assessments
// These helpers make the contract explicit and assertable at every call site.

export function stringKey(p: RawPatient): string {
  if (typeof p.patient_id !== "string") {
    throw new Error(`diagnoses/coverage need string patient_id, got ${typeof p.patient_id}`);
  }
  return p.patient_id;
}

export function intKey(p: RawPatient): number {
  if (typeof p.id !== "number") {
    throw new Error(`notes/assessments need integer id, got ${typeof p.id}`);
  }
  return p.id;
}

/** Returned diagnosis/coverage rows must carry the string key we queried with. */
export function assertStringKeyMatch(
  resource: string,
  expected: string,
  rows: { patient_id: unknown }[],
): void {
  for (const r of rows) {
    if (r.patient_id !== expected) {
      throw new Error(`${resource}: expected patient_id="${expected}", got "${String(r.patient_id)}"`);
    }
  }
}

/** Returned note/assessment rows must carry the integer key we queried with. */
export function assertIntKeyMatch(
  resource: string,
  expected: number,
  rows: { patient_id: unknown }[],
): void {
  for (const r of rows) {
    if (r.patient_id !== expected) {
      throw new Error(`${resource}: expected patient_id=${expected}, got ${String(r.patient_id)}`);
    }
  }
}
