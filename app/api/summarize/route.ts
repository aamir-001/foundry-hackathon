import { NextResponse } from "next/server";
import { getSupabaseAdmin } from "@/lib/supabase/client";
import { summarizeTriage } from "@/lib/llm/summarize";

export const runtime = "nodejs";

// On-demand "Summarize" — generate the optional Haiku narrative for one patient
// and persist it to triage.narrative. POST { patient_id }.
export async function POST(req: Request) {
  let patient_id: string | undefined;
  try {
    ({ patient_id } = await req.json());
  } catch {
    return NextResponse.json({ error: "invalid JSON body" }, { status: 400 });
  }
  if (!patient_id) {
    return NextResponse.json({ error: "patient_id required" }, { status: 400 });
  }

  const sb = getSupabaseAdmin();
  const { data, error } = await sb
    .from("triage")
    .select("routing_decision, reason, score, narrative")
    .eq("patient_id", patient_id)
    .single();
  if (error || !data) {
    return NextResponse.json({ error: error?.message ?? "not found" }, { status: 404 });
  }

  // Cached unless ?refresh=1 — narration is idempotent and cheap to reuse.
  const refresh = new URL(req.url).searchParams.get("refresh") === "1";
  if (data.narrative && !refresh) {
    return NextResponse.json({ narrative: data.narrative, cached: true });
  }

  try {
    const narrative = await summarizeTriage(data);
    await sb.from("triage").update({ narrative }).eq("patient_id", patient_id);
    return NextResponse.json({ narrative, cached: false });
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : "summarize failed" },
      { status: 500 },
    );
  }
}
