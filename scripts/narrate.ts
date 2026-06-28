// Phase 8 (bonus) — batch narratives. Generates the optional Haiku narrative for
// rows that don't have one yet. Defaults to the 5 worst-scoring flagged rows to
// keep cost trivial; `--limit=N` and `--all-decisions` widen it.

import { config } from "dotenv";
config({ path: ".env.local" });

import { getSupabaseAdmin } from "@/lib/supabase/client";
import { summarizeTriage } from "@/lib/llm/summarize";

async function main() {
  const limArg = process.argv.find((a) => a.startsWith("--limit="))?.split("=")[1];
  const limit = limArg ? Number.parseInt(limArg, 10) : 5;
  const onlyFlag = !process.argv.includes("--all-decisions");

  const sb = getSupabaseAdmin();
  let q = sb
    .from("triage")
    .select("patient_id, routing_decision, reason, score, narrative")
    .is("narrative", null)
    .order("score", { ascending: true, nullsFirst: false })
    .limit(limit);
  if (onlyFlag) q = q.eq("routing_decision", "flag_for_review");

  const { data, error } = await q;
  if (error) throw new Error(error.message);

  console.log(`Narrating ${data?.length ?? 0} rows (limit ${limit})...`);
  let n = 0;
  for (const r of data ?? []) {
    const narrative = await summarizeTriage(r);
    await sb.from("triage").update({ narrative }).eq("patient_id", r.patient_id);
    console.log(`  ${r.patient_id}: ${narrative.slice(0, 80)}…`);
    n++;
  }
  console.log(`✓ narrated ${n} rows`);
}

main().catch((e) => {
  console.error("✗ narrate failed:", e instanceof Error ? e.message : e);
  process.exit(1);
});
