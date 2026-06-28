import { getAllTriage, getQaStats } from "@/lib/supabase/queries";
import Worklist from "@/components/Worklist";

export const dynamic = "force-dynamic";

const REJECT_LABEL: Record<string, string> = {
  not_medicare_b: "not Medicare B",
  no_active_wound: "no active wound",
  extraction_unreliable: "extraction unreliable",
};

export default async function Home() {
  let rows;
  try {
    rows = await getAllTriage();
  } catch (e) {
    return (
      <main className="wrap">
        <h1>Wound-Care Billing Triage</h1>
        <p className="sub">Could not load triage data: {e instanceof Error ? e.message : String(e)}</p>
        <p className="muted">Run `npm run extract` to populate the triage table, then refresh.</p>
      </main>
    );
  }

  if (rows.length === 0) {
    return (
      <main className="wrap">
        <h1>Wound-Care Billing Triage</h1>
        <p className="sub">No triage rows yet — run `npm run extract` to populate them.</p>
      </main>
    );
  }

  const qa = await getQaStats(rows);
  const auto = qa.distribution.auto_accept ?? 0;
  const flag = qa.distribution.flag_for_review ?? 0;
  const reject = qa.distribution.reject ?? 0;

  return (
    <main className="wrap">
      <h1>Wound-Care Billing Triage</h1>
      <p className="sub">
        Medicare Part B eligibility · deterministic extraction · 0 required LLM calls · {qa.total} patients
      </p>

      <div className="lanes">
        <div className="lane act">
          <div className="label">Act on</div>
          <div className="count">{auto}</div>
          <div className="breakdown">all 3 criteria met · safe to bill</div>
        </div>
        <div className="lane review">
          <div className="label">Review</div>
          <div className="count">{flag}</div>
          <div className="breakdown">eligible · gap or conflict to confirm</div>
        </div>
        <div className="lane skip">
          <div className="label">Skip</div>
          <div className="count">{reject}</div>
          <div className="breakdown">
            {Object.entries(qa.rejectBreakdown)
              .map(([k, v]) => `${v} ${REJECT_LABEL[k] ?? k}`)
              .join(" · ")}
          </div>
        </div>
      </div>

      <div className="panel">
        <h2>QA panel</h2>
        <div className="qa-grid">
          <div className="qa-item">
            <div className="k">Decision mix</div>
            <div className="v">
              {auto} / {flag} / {reject}
            </div>
          </div>
          <div className="qa-item">
            <div className="k">Assessment format</div>
            <div className="v">
              {qa.structured} structured · {qa.narrative} narrative
            </div>
          </div>
          <div className="qa-item">
            <div className="k">Multi-wound (oracle 64)</div>
            <div className="v">{qa.signals.multi_wound}</div>
          </div>
          <div className="qa-item">
            <div className="k">No codeable dx (oracle 71)</div>
            <div className="v">{qa.signals.no_dx_code}</div>
          </div>
          <div className="qa-item">
            <div className="k">Depth unavailable</div>
            <div className="v">{qa.signals.depth_gap}</div>
          </div>
          <div className="qa-item">
            <div className="k">Laterality conflict (oracle 61)</div>
            <div className="v">{qa.signals.laterality_conflict}</div>
          </div>
        </div>
        <p className="muted" style={{ marginTop: "0.75rem", fontSize: "0.8rem" }}>
          Note: the PRD&apos;s 48/92/160 target is not reproducible from this data — every patient has a
          parseable wound type + L/W (type+L+W = 300/300), so &quot;extraction unreliable&quot; = 0 (not 5), and our
          note parser reads more depths than the oracle&apos;s. This is the honest, data-correct distribution.
        </p>
      </div>

      <Worklist rows={rows} />
    </main>
  );
}
