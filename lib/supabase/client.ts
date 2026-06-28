import { createClient, type SupabaseClient } from "@supabase/supabase-js";

function pick(...names: string[]): string {
  for (const n of names) {
    const v = process.env[n];
    if (v) return v;
  }
  throw new Error(`Missing required env var (one of: ${names.join(", ")})`);
}

/**
 * Server/script client using the service-role key — full read/write for the
 * ingest + extract pipelines. Never import this into client components.
 */
export function getSupabaseAdmin(): SupabaseClient {
  const url = pick("SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_URL");
  const key = pick("SUPABASE_SERVICE_ROLE_KEY");
  return createClient(url, key, { auth: { persistSession: false } });
}
