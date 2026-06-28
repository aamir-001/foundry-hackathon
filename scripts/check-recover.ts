// Phase 3 verify (offline): every required field has a tier; depth present+
// recovered+unavailable sum to 300; no field is silently null without a tier.

import { loadFixtures } from "@/lib/fixtures";
import { recoverPatient } from "@/lib/extract/recover";
import type { RecoveryTier } from "@/lib/extract/types";

const REQUIRED = [
  "wound_type",
  "length_cm",
  "width_cm",
  "depth_cm",
  "location",
  "stage",
  "drainage_amount",
  "laterality",
  "wound_dx_code",
];

function main() {
  const bundles = loadFixtures();
  const tally: Record<string, Record<RecoveryTier, number>> = {};
  for (const fld of REQUIRED) tally[fld] = { present: 0, recovered: 0, suggested: 0, unavailable: 0 };

  let untiered = 0;
  let inconsistent = 0;
  let suggestedDx = 0;
  let suggestedPrimary = 0;

  for (const b of bundles) {
    const r = recoverPatient(b);
    for (const fld of REQUIRED) {
      const fs = r.field_status[fld];
      if (!fs || !fs.tier) {
        untiered++;
        continue;
      }
      tally[fld][fs.tier]++;
      // consistency: a null value must be unavailable (suggested may carry a candidate)
      if (fs.value == null && fs.tier !== "unavailable" && fs.tier !== "suggested") inconsistent++;
      if (fs.value != null && fs.tier === "unavailable") inconsistent++;
    }
    if (r.suggested_dx_code) suggestedDx++;
    if (r.suggested_primary) suggestedPrimary++;
  }

  console.log("Tier distribution per required field:");
  for (const fld of REQUIRED) {
    const t = tally[fld];
    const sum = t.present + t.recovered + t.suggested + t.unavailable;
    console.log(
      `  ${fld.padEnd(14)} present=${String(t.present).padStart(3)} recovered=${String(t.recovered).padStart(3)} suggested=${String(t.suggested).padStart(3)} unavailable=${String(t.unavailable).padStart(3)}  Σ=${sum}`,
    );
  }
  const depth = tally.depth_cm;
  const depthSum = depth.present + depth.recovered + depth.suggested + depth.unavailable;
  console.log(`\nsuggested dx-codes: ${suggestedDx} (≈ oracle no-dx 71)`);
  console.log(`suggested primary : ${suggestedPrimary} (≈ multi-wound 64)`);
  console.log(`untiered fields   : ${untiered}`);
  console.log(`tier/value inconsistencies: ${inconsistent}`);

  const pass =
    untiered === 0 &&
    inconsistent === 0 &&
    depthSum === 300 &&
    depth.present + depth.recovered === 285 &&
    depth.unavailable === 15;
  console.log(
    pass
      ? "\n✓ PASS: all required fields tiered; depth present+recovered=285, unavailable=15 (Σ300)"
      : "\n✗ FAIL: see above",
  );
  if (!pass) process.exit(1);
}

main();
