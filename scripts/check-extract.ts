// Phase 2 verify (offline, no API/DB): run extraction over all 300 fixture
// bundles and report coverage against the gate:
//   type+L+W = 300/300 · drainage = 300/300 · depth ≥ 250/300.

import { loadFixtures } from "@/lib/fixtures";
import { extractPatient } from "@/lib/extract/reconcile";

function main() {
  const bundles = loadFixtures();
  let type = 0,
    length = 0,
    width = 0,
    depth = 0,
    drainage = 0,
    multi = 0,
    narr = 0;

  for (const b of bundles) {
    const e = extractPatient(b);
    if (e.wound_type) type++;
    if (e.length_cm != null) length++;
    if (e.width_cm != null) width++;
    if (e.depth_cm != null) depth++;
    if (e.drainage_amount != null) drainage++;
    if (e.is_multi_wound) multi++;
    if (e.assessment_format === "narrative") narr++;
  }

  const n = bundles.length;
  const typeLW = Math.min(type, length, width);
  const row = (label: string, got: number, need: string) =>
    console.log(`  ${label.padEnd(16)} ${String(got).padStart(3)}/${n}   ${need}`);

  console.log("Extraction coverage:");
  row("wound_type", type, "want 300");
  row("length_cm", length, "want 300");
  row("width_cm", width, "want 300");
  row("type+L+W", typeLW, "want 300");
  row("drainage_amount", drainage, "want 300");
  row("depth_cm", depth, "want ≥250");
  console.log(`  multi_wound      ${multi}   (oracle ~64)`);
  console.log(`  narrative format ${narr}   (want 81)`);

  const pass = typeLW === 300 && drainage === 300 && depth >= 250;
  console.log(pass ? "\n✓ PASS: Phase 2 coverage gate met" : "\n✗ FAIL: coverage gate not met");
  if (!pass) process.exit(1);
}

main();
