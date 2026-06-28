import type { SupabaseClient } from "@supabase/supabase-js";
import { PccClient } from "@/lib/pcc/client";
import { stringKey, intKey, assertStringKeyMatch, assertIntKeyMatch } from "@/lib/pcc/ids";
import { scorePatient } from "@/lib/routing/rules";
import { buildTriageRow } from "@/lib/routing/triage";
import { buildReason } from "@/lib/routing/reasons";
import type { PatientBundle, RawAssessment } from "@/lib/pcc/types";
import type { TriageRow } from "@/lib/supabase/types";

const FACILITIES = [101, 102, 103];

function parseRawJson(a: RawAssessment): unknown {
  if (typeof a.raw_json === "string") {
    try {
      return JSON.parse(a.raw_json);
    } catch {
      return a.raw_json;
    }
  }
  return a.raw_json;
}

export interface SyncReport {
  since: string | null;
  deltaPatients: number;
  triageUpdated: number;
  untouched: number;
  watermark: string | null;
  retries: number;
}

/**
 * Incremental sync (BUILD_PLAN §13): pull only patients changed since the stored
 * watermark (last_modified_at), re-ingest their records, re-score them, and bump
 * the watermark. Unchanged patients are never fetched or touched. Idempotent.
 */
export async function runSync(
  sb: SupabaseClient,
  opts: { since?: string } = {},
): Promise<SyncReport> {
  const client = new PccClient(8);

  let since = opts.since;
  if (since === undefined) {
    const { data } = await sb
      .from("sync_state")
      .select("watermark")
      .eq("resource", "patients")
      .maybeSingle();
    since = (data?.watermark as string | undefined) ?? undefined;
  }

  const lists = await Promise.all(FACILITIES.map((f) => client.getPatients(f, since)));
  const delta = lists.flat();

  let triageUpdated = 0;
  let maxLm = since ?? "";

  for (const p of delta) {
    const [dx, cov, notes, assess] = await Promise.all([
      client.getDiagnoses(stringKey(p)),
      client.getCoverage(stringKey(p)),
      client.getNotes(intKey(p)),
      client.getAssessments(intKey(p)),
    ]);
    assertStringKeyMatch("diagnoses", p.patient_id, dx);
    assertStringKeyMatch("coverage", p.patient_id, cov);
    assertIntKeyMatch("notes", p.id, notes);
    assertIntKeyMatch("assessments", p.id, assess);

    await sb.from("patient").upsert([p], { onConflict: "id" });
    if (dx.length) await sb.from("diagnosis").upsert(dx, { onConflict: "id" });
    if (cov.length) await sb.from("coverage").upsert(cov, { onConflict: "id" });
    if (notes.length) await sb.from("note").upsert(notes, { onConflict: "id" });
    if (assess.length) {
      await sb
        .from("assessment")
        .upsert(assess.map((a) => ({ ...a, raw_json: parseRawJson(a) })), { onConflict: "id" });
    }

    const bundle: PatientBundle = { patient: p, diagnoses: dx, coverage: cov, notes, assessments: assess };
    const sr = scorePatient(bundle);
    const row = buildTriageRow(bundle, sr, buildReason(sr));
    // Preserve biller-set fields across a re-sync.
    const { data: ex } = await sb
      .from("triage")
      .select("status, biller_inputs, narrative")
      .eq("patient_id", p.patient_id)
      .maybeSingle();
    if (ex) {
      row.status = (ex.status as TriageRow["status"]) ?? row.status;
      row.biller_inputs = (ex.biller_inputs as TriageRow["biller_inputs"]) ?? null;
      row.narrative = (ex.narrative as string | null) ?? null;
    }
    await sb.from("triage").upsert(row, { onConflict: "patient_id" });
    triageUpdated++;
    if (p.last_modified_at && p.last_modified_at > maxLm) maxLm = p.last_modified_at;
  }

  if (maxLm) {
    await sb.from("sync_state").upsert({ resource: "patients", watermark: maxLm }, { onConflict: "resource" });
  }

  const { count } = await sb.from("triage").select("*", { count: "exact", head: true });
  return {
    since: since ?? null,
    deltaPatients: delta.length,
    triageUpdated,
    untouched: (count ?? 0) - triageUpdated,
    watermark: maxLm || since || null,
    retries: client.stats.retries,
  };
}
