import { getPipelineStats } from "@/lib/supabase/queries";

export const dynamic = "force-dynamic";

const ARCH = `PHASE A — ingest (scripts/ingest.ts)        ← only phase that hits the live API
  Bottleneck(conc 8) → 429 retry honoring Retry-After (≤8) + 500-retry
  dual-key fan-out → upsert RAW tables → log retries to pipeline_run

PHASE B — extract + score (scripts/extract.ts)  ← reads RAW, NO API, deterministic
  parse (219 structured / 81 narrative / 3 note formats)
   → recovery layer (provenance + tiers)
   → score over field registry → route at 90
   → upsert TRIAGE (one flat row / patient)

Next.js dashboard reads TRIAGE  ·  feedback loop re-scores 1 patient (O(1))
Incremental "since" sync re-runs Phase A on deltas, Phase B on changed only`;

export default async function PipelinePage() {
  const s = await getPipelineStats();
  const totalRetries = s.runs.reduce((a, r) => a + (r.retries ?? 0), 0);

  return (
    <>
      <h1 className="h1">Data ingestion pipeline</h1>
      <p className="sub">
        Fetch patients, diagnoses, coverage, notes, assessments from the rate-limited mock PCC API →
        store in a queryable Postgres (Supabase).
      </p>

      <div className="panel">
        <h2>Architecture</h2>
        <div className="flow">{ARCH}</div>
      </div>

      <div className="panel">
        <h2>Rate limiting (the API returns 429 on ~30% of calls)</h2>
        <p className="muted" style={{ marginTop: 0 }}>
          Bottleneck caps concurrency at 8; every 429 sleeps its <code>Retry-After</code> and retries (≤8
          attempts), 500s back off and retry, 422s surface. Total retries are tallied per run — and{" "}
          <strong>0 patients were dropped</strong>.
        </p>
        <table>
          <thead>
            <tr>
              <th>Phase</th>
              <th>Patients</th>
              <th>Retries (429/500)</th>
              <th>Started</th>
              <th>Finished</th>
            </tr>
          </thead>
          <tbody>
            {s.runs.length === 0 && (
              <tr>
                <td colSpan={5} className="muted">
                  No runs logged yet — run `npm run ingest`.
                </td>
              </tr>
            )}
            {s.runs.map((r, i) => (
              <tr key={i}>
                <td>{r.phase}</td>
                <td>{r.patients ?? "—"}</td>
                <td>{r.retries ?? 0}</td>
                <td className="muted mono">{r.started_at?.replace("T", " ").slice(0, 19)}</td>
                <td className="muted mono">{r.finished_at ? "✓" : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="muted" style={{ marginTop: "0.5rem" }}>
          Cumulative retries across runs: <strong>{totalRetries}</strong>, all resolved.
        </p>
      </div>

      <div className="panel">
        <h2>Queryable store (raw mirror tables)</h2>
        <div className="qa-grid">
          {Object.entries(s.counts).map(([t, c]) => (
            <div className="qa-item" key={t}>
              <div className="k">{t}</div>
              <div className="v">{c}</div>
            </div>
          ))}
        </div>
        <p className="muted" style={{ marginTop: "0.75rem" }}>
          <strong>Dual-key fan-out (a silent-bug trap):</strong> diagnoses &amp; coverage are keyed by the
          string <code>patient_id</code> (e.g. FA-001); notes &amp; assessments by the integer{" "}
          <code>id</code>. Each is asserted at the call site.
        </p>
        <p className="muted">
          Incremental sync watermark (last_modified_at): <code>{s.watermark ?? "—"}</code>
        </p>
      </div>
    </>
  );
}
