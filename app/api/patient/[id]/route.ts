import { NextResponse } from "next/server";
import { getPatientDetail } from "@/lib/supabase/queries";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(_req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  try {
    const detail = await getPatientDetail(id);
    return NextResponse.json({
      triage: detail.triage,
      notes: detail.notes.slice(0, 1),
      diagnoses: detail.diagnoses,
      coverage: detail.coverage,
    });
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : "failed" },
      { status: 500 },
    );
  }
}
