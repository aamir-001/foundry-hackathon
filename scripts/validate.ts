// Phase 9 — validation. Reproduce the oracle's category counts and report per-
// category recall/precision of our engine, plus a cross-format sample audit.
// Pure offline (fixture + outliers_report.txt). No API, no DB.

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { loadFixtures } from "@/lib/fixtures";
import { extractPatient } from "@/lib/extract/reconcile";
import { recoverPatient } from "@/lib/extract/recover";
import { isNarrativeAssessment, flattenAssessment } from "@/lib/extract/structured";

const ORACLE = readFileSync(join(process.cwd(), "data", "outliers_report.txt"), "utf8");

/** Patient IDs on oracle SECTION-1 lines matching `re` (pid is on the same line). */
function oracleIds(re: RegExp): Set<string> {
  const ids = new Set<string>();
  for (const line of ORACLE.split("\n")) {
    if (re.test(line)) {
      const m = /\b(F[ABC]-\d+)\b/.exec(line);
      if (m) ids.add(m[1]);
    }
  }
  return ids;
}

const recall = (mine: Set<string>, oracle: Set<string>) => {
  const hit = [...oracle].filter((id) => mine.has(id)).length;
  const fp = [...mine].filter((id) => !oracle.has(id)).length;
  return {
    oracle: oracle.size,
    mine: mine.size,
    hit,
    missed: oracle.size - hit,
    falsePos: fp,
    recall: oracle.size ? (hit / oracle.size) : 1,
    precision: mine.size ? hit / mine.size : 1,
  };
};

const WOUND_PREFIX = /^(L89|L97|L98|I83|I70|T81|L02|T2)/i;

function main() {
  const bundles = loadFixtures();

  // ── my engine's per-category sets ──
  const mine = {
    noDx: new Set<string>(),
    multi: new Set<string>(),
    depthGap: new Set<string>(),
    stagePressure: new Set<string>(),
    laterality: new Set<string>(),
  };
  let structured = 0;
  let narrative = 0;
  const payer: Record<string, number> = {};

  for (const b of bundles) {
    const pid = b.patient.patient_id;
    const r = recoverPatient(b);
    const e = r.extracted;
    if (e.assessment_format === "narrative") narrative++;
    else structured++;
    for (const c of b.coverage) if (c.payer_code) payer[c.payer_code] = (payer[c.payer_code] ?? 0) + 1;

    if (!b.diagnoses.some((d) => d.clinical_status === "active" && WOUND_PREFIX.test(d.icd10_code ?? "")))
      mine.noDx.add(pid);
    if (e.is_multi_wound) mine.multi.add(pid);
    if (e.depth_cm == null) mine.depthGap.add(pid);
    if (e.wound_type === "pressure ulcer" && e.stage == null) mine.stagePressure.add(pid);
    if (r.laterality_conflict) mine.laterality.add(pid);
  }

  // ── oracle sets ──
  const oracle = {
    noDx: oracleIds(/NO wound-type ICD-10 diagnosis|wound dx present but NONE active/),
    multi: oracleIds(/describes MULTIPLE wounds/),
    depthGap: oracleIds(/NO depth anywhere/),
    stagePressure: oracleIds(/pressure ulcer with Stage/),
    laterality: oracleIds(/laterality '.*' contradicts location/),
  };

  console.log("════ ORACLE CATEGORY RECALL ════");
  const cats: [string, keyof typeof mine][] = [
    ["no codeable wound dx (B)", "noDx"],
    ["multi-wound (D)", "multi"],
    ["depth true-gap (C)", "depthGap"],
    ["stage missing/pressure (C)", "stagePressure"],
    ["laterality conflict (E)", "laterality"],
  ];
  for (const [label, key] of cats) {
    const s = recall(mine[key], oracle[key]);
    console.log(
      `  ${label.padEnd(28)} oracle=${String(s.oracle).padStart(3)} mine=${String(s.mine).padStart(3)} ` +
        `recall=${(s.recall * 100).toFixed(0)}% precision=${(s.precision * 100).toFixed(0)}% ` +
        `(missed ${s.missed}, fp ${s.falsePos})`,
    );
  }

  console.log("\n════ §2 DATA-REALITY REPRODUCTION ════");
  console.log(`  payer mix          : ${JSON.stringify(payer)}  (PRD: MCB 145 · MCA 56 · MCD 36 · HMO 63)`);
  console.log(`  assessment schemas : ${structured} structured · ${narrative} narrative  (PRD: 219 · 81)`);
  console.log(`  no codeable dx     : ${mine.noDx.size}  (PRD: 71)`);
  console.log(`  multi-wound        : ${mine.multi.size}  (PRD: 64)`);
  console.log(`  laterality conflict: ${mine.laterality.size}  (oracle: 61)`);

  console.log("\n════ SAMPLE AUDIT (cross-format) ════");
  const samples = pickSamples(bundles);
  for (const id of samples) {
    const b = bundles.find((x) => x.patient.patient_id === id)!;
    const e = extractPatient(b);
    const dims = [e.length_cm, e.width_cm, e.depth_cm].map((v) => (v == null ? "?" : v)).join("×");
    console.log(
      `  ${id.padEnd(7)} ${e.assessment_format.padEnd(10)} ${(e.wound_type ?? "?").padEnd(22)} ` +
        `${dims}cm  ${(e.drainage_amount ?? "?").padEnd(8)} loc=${e.location ?? "?"}${e.is_multi_wound ? " [multi]" : ""}`,
    );
  }

  // ── gate: high recall on the cleanly-mappable categories ──
  const ok =
    recall(mine.multi, oracle.multi).recall === 1 &&
    recall(mine.noDx, oracle.noDx).recall >= 0.95 &&
    recall(mine.laterality, oracle.laterality).recall >= 0.95 &&
    structured === 219 &&
    narrative === 81;
  console.log(ok ? "\n✓ PASS: category recall reproduces the oracle" : "\n✗ FAIL: recall below threshold");
  if (!ok) process.exit(1);
}

// ~20 patients spanning both assessment schemas and all three note formats.
function pickSamples(bundles: ReturnType<typeof loadFixtures>): string[] {
  const out: string[] = [];
  const seen = { structEnvive: 0, structMeas: 0, structProse: 0, narr: 0, multi: 0 };
  const noteFmt = (txt: string) =>
    /^\*?Envive/i.test(txt) ? "envive" : /\bMeas\b/i.test(txt) ? "meas" : "prose";
  for (const b of bundles) {
    const f = flattenAssessment(b.assessments[0]?.raw_json);
    const narr = isNarrativeAssessment(f);
    const e = extractPatient(b);
    const fmt = noteFmt(b.notes[0]?.note_text ?? "");
    let take = false;
    if (narr && seen.narr < 5) {
      seen.narr++;
      take = true;
    } else if (!narr && fmt === "envive" && seen.structEnvive < 4) {
      seen.structEnvive++;
      take = true;
    } else if (!narr && fmt === "meas" && seen.structMeas < 4) {
      seen.structMeas++;
      take = true;
    } else if (!narr && fmt === "prose" && seen.structProse < 4) {
      seen.structProse++;
      take = true;
    } else if (e.is_multi_wound && seen.multi < 3) {
      seen.multi++;
      take = true;
    }
    if (take) out.push(b.patient.patient_id);
    if (out.length >= 20) break;
  }
  return out;
}

main();
