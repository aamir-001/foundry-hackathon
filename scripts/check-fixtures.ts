// Phase 0 verify: parse data/all_patient_data.json -> /fixtures, prove 300 records.
// Writes a manifest + two named sample bundles (FA-001, FA-002) used by later
// unit tests, and prints aggregate counts. Pure offline; no API, no DB.

import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { loadFixtures, getBundle } from "@/lib/fixtures";

const FIX_DIR = join(process.cwd(), "fixtures");
const SAMPLE_DIR = join(FIX_DIR, "samples");

function main() {
  const bundles = loadFixtures();

  // ── aggregate counts ──
  const facilities: Record<number, number> = {};
  let diagnoses = 0,
    coverage = 0,
    notes = 0,
    assessments = 0;
  const payerMix: Record<string, number> = {};
  for (const b of bundles) {
    facilities[b.patient.facility_id] = (facilities[b.patient.facility_id] ?? 0) + 1;
    diagnoses += b.diagnoses.length;
    coverage += b.coverage.length;
    notes += b.notes.length;
    assessments += b.assessments.length;
    for (const c of b.coverage) {
      const k = c.payer_code ?? "null";
      payerMix[k] = (payerMix[k] ?? 0) + 1;
    }
  }

  const manifest = {
    generated_at: new Date().toISOString(),
    patients: bundles.length,
    facilities,
    totals: { diagnoses, coverage, notes, assessments },
    payer_mix: payerMix,
  };

  mkdirSync(SAMPLE_DIR, { recursive: true });
  writeFileSync(join(FIX_DIR, "manifest.json"), JSON.stringify(manifest, null, 2) + "\n");
  for (const id of ["FA-001", "FA-002"]) {
    const bundle = getBundle(id);
    if (!bundle) throw new Error(`Sample bundle ${id} not found in fixture`);
    writeFileSync(join(SAMPLE_DIR, `${id}.json`), JSON.stringify(bundle, null, 2) + "\n");
  }

  // ── report ──
  console.log("Fixtures loaded:", bundles.length, "patient bundles");
  console.log("Per facility   :", JSON.stringify(facilities));
  console.log("Totals         :", JSON.stringify(manifest.totals));
  console.log("Payer mix      :", JSON.stringify(payerMix));
  console.log("Wrote          : fixtures/manifest.json, fixtures/samples/FA-001.json, FA-002.json");

  if (bundles.length !== 300) {
    console.error(`\n✗ FAIL: expected 300 records, got ${bundles.length}`);
    process.exit(1);
  }
  console.log("\n✓ PASS: fixtures load 300 records");
}

main();
