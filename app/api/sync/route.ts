import { NextResponse } from "next/server";
import { getSupabaseAdmin } from "@/lib/supabase/client";
import { runSync } from "@/lib/pipeline/sync";

export const runtime = "nodejs";
export const maxDuration = 120;

// Incremental sync triggered from the dashboard "Sync" button. Uses the stored
// watermark by default; ?since=<ISO> overrides.
export async function POST(req: Request) {
  const since = new URL(req.url).searchParams.get("since") ?? undefined;
  try {
    const report = await runSync(getSupabaseAdmin(), since ? { since } : {});
    return NextResponse.json(report);
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : "sync failed" },
      { status: 500 },
    );
  }
}
