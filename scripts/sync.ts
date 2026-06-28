// Phase 8 — incremental `since` sync (Phase A on deltas, Phase B on changed only).
// `npm run sync` uses the stored watermark; `npm run sync -- --since=<ISO>` overrides.

import { config } from "dotenv";
config({ path: ".env.local" });

import { getSupabaseAdmin } from "@/lib/supabase/client";
import { runSync } from "@/lib/pipeline/sync";

async function main() {
  const sinceArg = process.argv.find((a) => a.startsWith("--since="))?.split("=")[1];
  const sb = getSupabaseAdmin();
  const r = await runSync(sb, sinceArg ? { since: sinceArg } : {});

  console.log("── INCREMENTAL SYNC ──");
  console.log(`since                 : ${r.since ?? "(full — no watermark)"}`);
  console.log(`delta patients fetched: ${r.deltaPatients} (of 300)`);
  console.log(`triage rows updated   : ${r.triageUpdated}`);
  console.log(`untouched             : ${r.untouched}`);
  console.log(`watermark →           : ${r.watermark}`);
  console.log(`retries               : ${r.retries}`);
}

main().catch((e) => {
  console.error("✗ sync failed:", e instanceof Error ? (e.stack ?? e.message) : e);
  process.exit(1);
});
