import { NextResponse } from "next/server";
import { getSupabaseAdmin } from "@/lib/supabase/client";
import { getBundle } from "@/lib/fixtures";
import { scorePatient } from "@/lib/routing/rules";
import { buildTriageRow } from "@/lib/routing/triage";
import { buildReason } from "@/lib/routing/reasons";

export const runtime = "nodejs";

const VALID_STATUS = ["pending", "reviewed", "submitted", "dismissed"];

// Feedback loop (§12): biller supplies a missing/ambiguous value OR changes status.
// On a field submit, re-run §8–§9 for THIS patient (deterministic, O(1)) and persist.
export async function POST(req: Request) {
  const body = (await req.json().catch(() => null)) as {
    patient_id?: string;
    field?: string;
    value?: unknown;
    status?: string;
  } | null;
  if (!body?.patient_id) {
    return NextResponse.json({ error: "patient_id required" }, { status: 400 });
  }
  const { patient_id, field, value, status } = body;

  const sb = getSupabaseAdmin();
  const { data: existing } = await sb
    .from("triage")
    .select("biller_inputs, status")
    .eq("patient_id", patient_id)
    .maybeSingle();
  if (!existing) {
    return NextResponse.json({ error: "patient not found" }, { status: 404 });
  }

  // Status-only transition (no re-score).
  if (status && !field) {
    if (!VALID_STATUS.includes(status)) {
      return NextResponse.json({ error: "invalid status" }, { status: 400 });
    }
    const { error } = await sb.from("triage").update({ status }).eq("patient_id", patient_id);
    if (error) return NextResponse.json({ error: error.message }, { status: 500 });
    return NextResponse.json({ ok: true, status });
  }

  if (!field) {
    return NextResponse.json({ error: "field or status required" }, { status: 400 });
  }

  const bundle = getBundle(patient_id);
  if (!bundle) {
    return NextResponse.json({ error: "no source bundle for patient" }, { status: 404 });
  }

  const billerInputs = {
    ...((existing.biller_inputs as Record<string, unknown> | null) ?? {}),
    [field]: value,
  };
  const sr = scorePatient(bundle, billerInputs);
  const row = buildTriageRow(bundle, sr, buildReason(sr));
  row.biller_inputs = billerInputs;
  row.status =
    status && VALID_STATUS.includes(status)
      ? (status as typeof row.status)
      : existing.status === "pending"
        ? "reviewed"
        : ((existing.status as typeof row.status) ?? "reviewed");
  row.narrative = null; // reason changed → stale; biller can re-summarize

  const { error } = await sb.from("triage").upsert(row, { onConflict: "patient_id" });
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  return NextResponse.json({
    ok: true,
    routing_decision: row.routing_decision,
    score: row.score,
    reason: row.reason,
    status: row.status,
  });
}
