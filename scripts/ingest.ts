// Phase 1 (Phase A) — Ingestion. The ONLY phase that hits the live API.
// Bottleneck(conc 8) + 429/500 retry → dual-key fan-out → idempotent upserts
// into the raw mirror tables. Tracks retries in pipeline_run; sweeps stragglers.

import { config } from "dotenv";
config({ path: ".env.local" });

import type { SupabaseClient } from "@supabase/supabase-js";
import { getSupabaseAdmin } from "@/lib/supabase/client";
import { PccClient } from "@/lib/pcc/client";
import {
  stringKey,
  intKey,
  assertStringKeyMatch,
  assertIntKeyMatch,
} from "@/lib/pcc/ids";
import type {
  RawPatient,
  RawDiagnosis,
  RawCoverage,
  RawNote,
  RawAssessment,
} from "@/lib/pcc/types";

const FACILITIES = [101, 102, 103];
const CHUNK = 500;

function dedupeById<T extends { id: number }>(rows: T[]): T[] {
  const m = new Map<number, T>();
  for (const r of rows) m.set(r.id, r);
  return [...m.values()];
}

async function upsert(
  sb: SupabaseClient,
  table: string,
  rows: { id: number }[],
  onConflict = "id",
): Promise<void> {
  const deduped = dedupeById(rows);
  for (let i = 0; i < deduped.length; i += CHUNK) {
    const chunk = deduped.slice(i, i + CHUNK);
    const { error } = await sb.from(table).upsert(chunk, { onConflict });
    if (error) throw new Error(`upsert ${table} failed: ${error.message}`);
  }
}

async function count(sb: SupabaseClient, table: string): Promise<number> {
  const { count: c, error } = await sb.from(table).select("*", { count: "exact", head: true });
  if (error) throw new Error(`count ${table}: ${error.message}`);
  return c ?? 0;
}

// raw_json is a JSON-encoded string from the API; store the parsed object as jsonb.
function normalizeAssessment(a: RawAssessment): Omit<RawAssessment, "raw_json"> & { raw_json: unknown } {
  let raw: unknown = a.raw_json;
  if (typeof a.raw_json === "string") {
    try {
      raw = JSON.parse(a.raw_json);
    } catch {
      raw = a.raw_json; // store as-is if it isn't valid JSON
    }
  }
  return { ...a, raw_json: raw };
}

async function main() {
  const sb = getSupabaseAdmin();
  const client = new PccClient(8);
  const startedAt = new Date().toISOString();

  const run = await sb
    .from("pipeline_run")
    .insert({ phase: "ingest", started_at: startedAt })
    .select("id")
    .single();
  if (run.error) throw new Error(`pipeline_run insert: ${run.error.message}`);
  const runId = run.data.id as string;

  // ── 1) Patients (3 facility calls) ──
  console.log(`Fetching patients for facilities ${FACILITIES.join(", ")}...`);
  const lists = await Promise.all(FACILITIES.map((f) => client.getPatients(f)));
  const patients: RawPatient[] = lists.flat();
  console.log(`  → ${patients.length} patients`);
  for (const p of patients) {
    stringKey(p); // assert string patient_id
    intKey(p); // assert integer id
  }
  await upsert(sb, "patient", patients);

  // ── 2) Dual-key fan-out for child resources ──
  const diagnoses: RawDiagnosis[] = [];
  const coverage: RawCoverage[] = [];
  const notes: RawNote[] = [];
  const assessments: RawAssessment[] = [];

  type Resource = "diagnoses" | "coverage" | "notes" | "assessments";
  type Fail = { p: RawPatient; resource: Resource; error: string };
  const failures: Fail[] = [];

  async function fetchOne(p: RawPatient, resource: Resource): Promise<void> {
    switch (resource) {
      case "diagnoses": {
        const r = await client.getDiagnoses(stringKey(p));
        assertStringKeyMatch("diagnoses", p.patient_id, r);
        diagnoses.push(...r);
        break;
      }
      case "coverage": {
        const r = await client.getCoverage(stringKey(p));
        assertStringKeyMatch("coverage", p.patient_id, r);
        coverage.push(...r);
        break;
      }
      case "notes": {
        const r = await client.getNotes(intKey(p));
        assertIntKeyMatch("notes", p.id, r);
        notes.push(...r);
        break;
      }
      case "assessments": {
        const r = await client.getAssessments(intKey(p));
        assertIntKeyMatch("assessments", p.id, r);
        assessments.push(...r);
        break;
      }
    }
  }

  const resources: Resource[] = ["diagnoses", "coverage", "notes", "assessments"];
  const tasks: Promise<void>[] = [];
  for (const p of patients) {
    for (const resource of resources) {
      tasks.push(
        fetchOne(p, resource).catch((e: unknown) => {
          failures.push({ p, resource, error: e instanceof Error ? e.message : String(e) });
        }),
      );
    }
  }
  console.log(`Fanning out ${tasks.length} child fetches (conc 8)...`);
  await Promise.all(tasks); // each task swallows its own error -> never rejects

  // ── 3) Sweep: retry the stragglers once more (fresh ≤8 attempts each) ──
  if (failures.length) {
    console.log(`Sweeping ${failures.length} unresolved fetch(es)...`);
    const pending = failures.splice(0);
    for (const f of pending) {
      try {
        await fetchOne(f.p, f.resource);
      } catch (e) {
        failures.push({ ...f, error: e instanceof Error ? e.message : String(e) });
      }
    }
  }

  // ── 4) Idempotent upserts (children) ──
  await upsert(sb, "diagnosis", diagnoses);
  await upsert(sb, "coverage", coverage);
  await upsert(sb, "note", notes);
  await upsert(sb, "assessment", assessments.map(normalizeAssessment) as { id: number }[]);

  // ── 5) Close out the run ──
  await sb
    .from("pipeline_run")
    .update({
      finished_at: new Date().toISOString(),
      patients: patients.length,
      retries: client.stats.retries,
    })
    .eq("id", runId);

  // ── 6) Report + verify ──
  const dbCounts = {
    patient: await count(sb, "patient"),
    diagnosis: await count(sb, "diagnosis"),
    coverage: await count(sb, "coverage"),
    note: await count(sb, "note"),
    assessment: await count(sb, "assessment"),
  };
  const distinct = {
    diagnoses: new Set(diagnoses.map((d) => d.patient_id)).size,
    coverage: new Set(coverage.map((c) => c.patient_id)).size,
    notes: new Set(notes.map((n) => n.patient_id)).size,
    assessments: new Set(assessments.map((a) => a.patient_id)).size,
  };

  console.log("\n──────── INGEST SUMMARY ────────");
  console.log("retry stats   :", JSON.stringify(client.stats));
  console.log("db row counts :", JSON.stringify(dbCounts));
  console.log("patients w/ ≥1:", JSON.stringify(distinct), "(want 300 each)");
  if (failures.length) {
    console.log(`unresolved    : ${failures.length} ->`, JSON.stringify(failures.map((f) => `${f.p.patient_id}/${f.resource}`)));
  } else {
    console.log("unresolved    : 0");
  }

  const ok =
    dbCounts.patient === 300 &&
    distinct.diagnoses === 300 &&
    distinct.coverage === 300 &&
    distinct.notes === 300 &&
    distinct.assessments === 300 &&
    client.stats.retries > 0 &&
    failures.length === 0;

  console.log(ok ? "\n✓ PASS: 300 patients, all children non-empty, retries>0" : "\n✗ FAIL: see summary above");
  if (!ok) process.exit(1);
}

main().catch((e) => {
  console.error("✗ ingest failed:", e instanceof Error ? e.stack ?? e.message : e);
  process.exit(1);
});
