import { readFileSync } from "node:fs";
import { join } from "node:path";
import type { PatientBundle } from "@/lib/pcc/types";

// The authoritative offline fixture (300 patient bundles). Parse with code only;
// extraction/scoring is developed against this without touching the live API.
export const FIXTURE_PATH = join(process.cwd(), "data", "all_patient_data.json");

let cache: PatientBundle[] | null = null;

/** Load all 300 patient bundles from the offline fixture (memoized). */
export function loadFixtures(): PatientBundle[] {
  if (cache) return cache;
  const raw = readFileSync(FIXTURE_PATH, "utf8");
  const data = JSON.parse(raw);
  if (!Array.isArray(data)) {
    throw new Error(`Fixture root is not an array (got ${typeof data})`);
  }
  cache = data as PatientBundle[];
  return cache;
}

/** Look up a single bundle by its PCC string id (e.g. "FA-001"). */
export function getBundle(patientId: string): PatientBundle | undefined {
  return loadFixtures().find((b) => b.patient.patient_id === patientId);
}
