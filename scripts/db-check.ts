// Phase 0 verify (DB half): `select 1` over Supabase + assert all tables exist.
// Run AFTER applying supabase/migrations/0001_init.sql and filling .env.local.

import { config } from "dotenv";
config({ path: ".env.local" });

import { getSupabaseAdmin } from "@/lib/supabase/client";

const TABLES = [
  "patient",
  "diagnosis",
  "coverage",
  "note",
  "assessment",
  "triage",
  "sync_state",
  "pipeline_run",
];

async function main() {
  const sb = getSupabaseAdmin();

  // connectivity (≡ select 1): a head count on patient round-trips to Postgres.
  const probe = await sb.from("patient").select("*", { count: "exact", head: true });
  if (probe.error && !/does not exist/i.test(probe.error.message)) {
    console.error("✗ FAIL: cannot reach Supabase —", probe.error.message);
    process.exit(1);
  }
  console.log("✓ Supabase reachable (select 1 ok)");

  let allExist = true;
  for (const t of TABLES) {
    const { count, error } = await sb.from(t).select("*", { count: "exact", head: true });
    if (error) {
      console.error(`  ✗ ${t.padEnd(14)} MISSING — ${error.message}`);
      allExist = false;
    } else {
      console.log(`  ✓ ${t.padEnd(14)} exists (rows: ${count ?? 0})`);
    }
  }

  if (!allExist) {
    console.error("\n✗ FAIL: some tables missing — apply supabase/migrations/0001_init.sql");
    process.exit(1);
  }
  console.log("\n✓ PASS: all 8 tables exist");
}

main().catch((e) => {
  console.error("✗ FAIL:", e instanceof Error ? e.message : e);
  process.exit(1);
});
