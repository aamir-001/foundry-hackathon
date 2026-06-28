import { createClient, type SupabaseClient } from "@supabase/supabase-js";

function pick(...names: string[]): string {
  for (const n of names) {
    const v = process.env[n];
    if (v) return v;
  }
  throw new Error(`Missing required env var (one of: ${names.join(", ")})`);
}

/**
 * Server/script client for the ingest + extract pipelines. Prefers the
 * service-role key (bypasses RLS); falls back to the anon key when no
 * service-role key is set — fine while RLS is disabled (the default for
 * tables created via raw SQL). Never import this into client components.
 */
export function getSupabaseAdmin(): SupabaseClient {
  const url = pick("SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_URL");
  const serviceKey = process.env.SUPABASE_SERVICE_ROLE_KEY;
  const key = serviceKey || pick("NEXT_PUBLIC_SUPABASE_ANON_KEY", "SUPABASE_ANON_KEY");
  if (!serviceKey) {
    console.warn(
      "⚠ Using anon key (no SUPABASE_SERVICE_ROLE_KEY). OK while RLS is off; " +
        "set the service-role key before relying on writes.",
    );
  }
  return createClient(url, key, {
    auth: { persistSession: false },
    // Next.js caches `fetch` (which supabase-js uses) by default, so server reads
    // can return stale rows after a write (e.g. a status change wouldn't show up
    // until a hard reload). Force every request fresh.
    global: {
      fetch: (input: RequestInfo | URL, init?: RequestInit) =>
        fetch(input, { ...init, cache: "no-store" }),
    },
  });
}
